"""Generate recipes from leftovers with flax-community/t5-recipe-generation."""

from __future__ import annotations

import hashlib
import os
import re
import time
from urllib.parse import quote_plus

import httpx

from backend.filters import passes_diet

MODEL_ID = "flax-community/t5-recipe-generation"
PREFIX = "items: "

TOKENS_MAP = {
    "<sep>": "--",
    "<section>": "\n",
}

SPECIAL_TOKEN_RE = re.compile(r"</?(?:pad|s|unk|eos|bos|sep|section)(?:_id)?>", re.I)

MEAT = {
    "chicken", "beef", "pork", "bacon", "ham", "lamb", "mutton", "turkey",
    "sausage", "meat", "steak", "fish", "salmon", "tuna", "shrimp", "prawn",
    "anchovy", "crab", "lobster",
}
DAIRY_EGG = {
    "egg", "eggs", "milk", "butter", "cheese", "cream", "yogurt", "yoghurt",
    "mayo", "mayonnaise", "ghee",
}
NON_HALAL = {"pork", "bacon", "ham", "lard", "wine", "beer", "alcohol", "gelatin"}

# Normalize plurals / aliases so "tomato" matches "tomatoes"
ALIASES = {
    "tomatoes": "tomato",
    "potatoes": "potato",
    "onions": "onion",
    "eggs": "egg",
    "carrots": "carrot",
    "peppers": "pepper",
    "chilies": "chili",
    "chillies": "chili",
    "mushrooms": "mushroom",
    "beans": "bean",
    "peas": "pea",
    "leaves": "leaf",
    "cloves": "garlic",
    "chickens": "chicken",
    "noodles": "noodle",
    "chillies": "chili",
}

# Culinary swaps: missing item → common substitutes (prefer pantry leftovers when possible)
SUBSTITUTIONS: dict[str, list[str]] = {
    "butter": ["olive oil", "oil", "ghee", "margarine", "coconut oil"],
    "oil": ["butter", "ghee", "olive oil", "coconut oil"],
    "olive oil": ["oil", "butter", "ghee", "avocado oil"],
    "milk": ["almond milk", "oat milk", "soy milk", "coconut milk", "yogurt"],
    "cream": ["milk", "yogurt", "coconut cream", "evaporated milk", "sour cream"],
    "sour cream": ["yogurt", "greek yogurt", "creme fraiche", "cottage cheese"],
    "yogurt": ["sour cream", "greek yogurt", "buttermilk", "milk"],
    "egg": ["flax egg", "chia egg", "applesauce", "mashed banana", "silken tofu"],
    "cheese": ["nutritional yeast", "vegan cheese", "cottage cheese", "feta"],
    "parmesan": ["nutritional yeast", "pecorino", "romano", "aged cheddar"],
    "heavy cream": ["coconut cream", "evaporated milk", "milk", "cashew cream"],
    "chicken": ["turkey", "tofu", "chickpeas", "mushroom", "paneer"],
    "beef": ["lamb", "turkey", "mushroom", "lentils", "tofu"],
    "pork": ["chicken", "turkey", "tofu", "mushroom"],
    "bacon": ["turkey bacon", "smoked paprika", "mushroom", "tempeh"],
    "fish": ["tofu", "chickpeas", "jackfruit", "chicken"],
    "shrimp": ["chicken", "tofu", "firm white fish", "mushrooms"],
    "rice": ["quinoa", "couscous", "cauliflower rice", "bulgur", "pasta"],
    "pasta": ["rice", "zucchini noodles", "spaghetti squash", "couscous"],
    "bread": ["tortilla", "pita", "rice", "lettuce wrap", "naan"],
    "flour": ["almond flour", "oat flour", "rice flour", "cornstarch"],
    "cornstarch": ["flour", "arrowroot", "potato starch", "tapioca starch"],
    "sugar": ["honey", "maple syrup", "agave", "brown sugar", "stevia"],
    "honey": ["maple syrup", "agave", "sugar", "date syrup"],
    "soy sauce": ["tamari", "coconut aminos", "worcestershire", "fish sauce"],
    "vinegar": ["lemon juice", "lime juice", "apple cider vinegar", "white wine vinegar"],
    "lemon": ["lime", "vinegar", "lemon juice", "citric acid"],
    "lime": ["lemon", "vinegar", "lime juice"],
    "garlic": ["garlic powder", "shallot", "onion", "asafoetida"],
    "onion": ["shallot", "leek", "green onion", "onion powder"],
    "shallot": ["onion", "leek", "green onion"],
    "tomato": ["tomato paste", "canned tomato", "passata", "red pepper"],
    "tomato paste": ["tomato sauce", "ketchup", "pureed tomato"],
    "potato": ["sweet potato", "cauliflower", "turnip", "parsnip"],
    "bell pepper": ["poblano", "anaheim", "tomato", "zucchini"],
    "pepper": ["bell pepper", "paprika", "chili"],
    "chili": ["cayenne", "red pepper flakes", "hot sauce", "paprika"],
    "basil": ["oregano", "parsley", "spinach", "mint"],
    "cilantro": ["parsley", "basil", "mint", "green onion"],
    "parsley": ["cilantro", "basil", "celery leaves"],
    "ginger": ["galangal", "ground ginger", "allspice"],
    "cumin": ["coriander", "chili powder", "garam masala"],
    "broth": ["stock", "bouillon", "water", "miso water"],
    "stock": ["broth", "bouillon", "water"],
    "wine": ["broth", "grape juice", "vinegar", "apple juice"],
    "mayonnaise": ["greek yogurt", "sour cream", "avocado", "hummus"],
    "peanut butter": ["almond butter", "sunflower seed butter", "tahini"],
    "tahini": ["peanut butter", "almond butter", "sesame oil"],
    "coconut milk": ["cream", "evaporated milk", "almond milk", "cashew cream"],
    "tofu": ["paneer", "tempeh", "chickpeas", "egg"],
    "chickpeas": ["white beans", "lentils", "tofu", "edamame"],
    "lentils": ["chickpeas", "split peas", "beans", "quinoa"],
}

PLACEHOLDER_IMG = (
    "https://images.unsplash.com/photo-1546069901-ba9599a7e63c"
    "?auto=format&fit=crop&w=900&q=80"
)


def normalize_token(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s in ALIASES:
        return ALIASES[s]
    if s.endswith("oes") and len(s) > 4:
        return s[:-2]  # tomatoes → tomato (approx)
    if s.endswith("ies") and len(s) > 4:
        return s[:-3] + "y"
    if s.endswith("s") and not s.endswith("ss") and len(s) > 3:
        return s[:-1]
    return s


def _tokens(text: str) -> set[str]:
    parts = re.split(r"[\s/\-]+", normalize_token(text))
    return {p for p in parts if len(p) > 1}


def soft_match_ingredient(user_ing: str, recipe_ing: str) -> bool:
    u = normalize_token(user_ing)
    r = normalize_token(recipe_ing)
    if not u or not r:
        return False
    if u == r:
        return True
    if u in r or r in u:
        return True
    ut, rt = _tokens(u), _tokens(r)
    if ut & rt:
        return True
    return False


def match_leftovers(leftovers: list[str], recipe_ingredients: list[str]) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    used_recipe: set[int] = set()
    for leftover in leftovers:
        for i, ring in enumerate(recipe_ingredients):
            if i in used_recipe:
                continue
            if soft_match_ingredient(leftover, ring):
                matched.append(leftover.strip().lower())
                used_recipe.add(i)
                break
    missing = [
        recipe_ingredients[i]
        for i in range(len(recipe_ingredients))
        if i not in used_recipe
    ]
    return sorted(set(matched)), missing


def _sub_key_match(a: str, b: str) -> bool:
    """Stricter than soft_match — avoid linking 'soy sauce' to 'soy milk' via one shared token."""
    u = normalize_token(a)
    r = normalize_token(b)
    if not u or not r:
        return False
    if u == r:
        return True
    # Phrase containment only when both are multi-char and not a tiny token collision
    if len(u) >= 4 and len(r) >= 4 and (u in r or r in u):
        return True
    return False


def _substitution_candidates(ingredient: str) -> list[str]:
    """Return alternate ingredients for a missing item (excluding itself)."""
    seen: set[str] = set()
    out: list[str] = []
    ing_norm = normalize_token(ingredient)
    for canon, alts in SUBSTITUTIONS.items():
        group = [canon, *alts]
        if not any(_sub_key_match(ingredient, g) for g in group):
            continue
        for g in group:
            key = normalize_token(g)
            if key == ing_norm or key in seen:
                continue
            seen.add(key)
            out.append(g)
    return out[:6]


def suggest_substitutions(
    missing: list[str],
    available: list[str] | None = None,
) -> list[dict]:
    """Suggest swaps for missing ingredients; flag ones the user already has."""
    available = [a for a in (available or []) if a and str(a).strip()]
    suggestions: list[dict] = []
    for item in missing:
        if not item or not str(item).strip():
            continue
        substitutes = _substitution_candidates(str(item))
        if not substitutes:
            continue
        you_have = [
            s
            for s in substitutes
            if any(_sub_key_match(a, s) for a in available)
        ]
        suggestions.append(
            {
                "ingredient": str(item).strip(),
                "substitutes": substitutes,
                "you_have": you_have,
            }
        )
    return suggestions


def attach_substitutions(recipes: list[dict], leftovers: list[str]) -> list[dict]:
    """Add substitution hints onto each recipe from its missing_ingredients."""
    for recipe in recipes:
        missing = recipe.get("missing_ingredients") or []
        if not isinstance(missing, list):
            missing = []
        recipe["substitutions"] = suggest_substitutions(missing, leftovers)
    return recipes


def relevance_ok(matched: list[str], leftovers: list[str]) -> bool:
    """Require real overlap with what the user typed."""
    n = len([x for x in leftovers if x.strip()])
    if n == 0:
        return False
    m = len(matched)
    if m == 0:
        return False
    # Always need >=1. For 3+ leftovers require at least 2 so results stay on-topic.
    # Ranking by uses_count prefers recipes that cover more keywords.
    if n >= 3:
        return m >= 2
    return m >= 1


def score_relevance(matched: list[str], leftovers: list[str], recipe_ingredients: list[str]) -> float:
    n_user = max(len(leftovers), 1)
    n_recipe = max(len(recipe_ingredients), 1)
    precision = len(matched) / n_user
    coverage = len(matched) / n_recipe
    # Heavily reward using the user's keywords
    return round((0.7 * precision + 0.3 * coverage) * 100, 1)


def _postprocess_raw(text: str) -> str:
    text = SPECIAL_TOKEN_RE.sub("", text)
    for old, new in TOKENS_MAP.items():
        text = text.replace(old, new)
    return text.strip()


def _split_list(blob: str) -> list[str]:
    parts = re.split(r"--|\n|;", blob)
    return [p.strip(" .-•\t") for p in parts if p.strip(" .-•\t")]


def _ingredient_name(raw: str) -> str:
    """Reduce '2 c. macaroni' / '3 cloves garlic, minced' to a short name."""
    s = raw.strip().lower()
    s = re.sub(
        r"^[\d./\s\-to]+"
        r"(?:cups?|c\.|tbsp\.?|tsp\.?|tablespoons?|teaspoons?|"
        r"oz\.?|ounces?|lbs?\.?|pounds?|g|kg|ml|l|cans?|pkg\.?|"
        r"packages?|slices?|cloves?|pinch(?:es)?|dash(?:es)?)?\s*",
        "",
        s,
        flags=re.I,
    )
    s = re.split(r"[,;(]", s)[0].strip()
    s = re.sub(r"\s+", " ", s)
    return s or raw.strip().lower()


def _infer_diet(names: list[str]) -> str:
    lower = {normalize_token(n) for n in names}
    if lower & MEAT or lower & DAIRY_EGG:
        return "non-vegan"
    return "vegan"


def _infer_halal(names: list[str]) -> str:
    blob = " ".join(normalize_token(n) for n in names)
    for bad in NON_HALAL:
        if bad in blob:
            return "non-halal"
    return "halal"


def _passes_filters(
    recipe: dict,
    diet: str | None,
    halal: str | None,
    goal: str | None,
) -> bool:
    if not passes_diet(recipe, diet):
        return False
    if halal and recipe.get("halal") != halal:
        return False
    if goal and recipe.get("goal") and recipe.get("goal") != goal:
        return False
    return True


def parse_generated_recipe(raw: str, leftovers: list[str], goal: str | None = None) -> dict | None:
    text = _postprocess_raw(raw)
    if not text:
        return None

    text = re.sub(r"\s*(title:)", r"\n\1", text, flags=re.I)
    text = re.sub(r"\s*(ingredients:)", r"\n\1", text, flags=re.I)
    text = re.sub(r"\s*(directions:)", r"\n\1", text, flags=re.I)

    title = ""
    ingredients_raw: list[str] = []
    directions: list[str] = []

    for section in text.split("\n"):
        section = section.strip()
        if not section:
            continue
        lower = section.lower()
        if lower.startswith("title:"):
            title = section.split(":", 1)[1].strip()
        elif lower.startswith("ingredients:"):
            ingredients_raw = _split_list(section.split(":", 1)[1])
        elif lower.startswith("directions:"):
            directions = _split_list(section.split(":", 1)[1])
        elif not title and not ingredients_raw and not directions:
            title = section

    if not title and not directions and not ingredients_raw:
        return None

    names = [_ingredient_name(x) for x in ingredients_raw]
    names = [n for n in names if n]
    if not names:
        return None

    # Score against T5 output only — never inject leftovers before the gate
    matched, missing = match_leftovers(leftovers, names)
    if not relevance_ok(matched, leftovers):
        return None

    title = (title or "Leftover special").strip().title()

    if not directions and text:
        directions = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()][:8]

    score = score_relevance(matched, leftovers, names)
    steps = [d[0].upper() + d[1:] if d else d for d in directions]
    instructions = " ".join(steps)
    diet = _infer_diet(names)
    halal = _infer_halal(names)
    rid = "t5-" + hashlib.sha1(f"{title}|{','.join(names)}".encode()).hexdigest()[:10]

    measurements = []
    for raw_line, name in zip(ingredients_raw, names):
        amount = raw_line.strip()
        if name and amount.lower().endswith(name):
            qty = amount[: -len(name)].strip(" ,")
            amount = qty or amount
        measurements.append({"ingredient": name, "amount": amount or "to taste"})

    if not measurements:
        measurements = [{"ingredient": n, "amount": "as needed"} for n in names]

    search = quote_plus(f"{title} {' '.join(matched)}")
    return {
        "id": rid,
        "name": title,
        "cuisine": "Chef Transformer",
        "time_min": max(15, min(60, 8 + 4 * len(steps))),
        "ingredients": names,
        "instructions": instructions,
        "steps": steps or [instructions or f"Cook with {', '.join(matched)} until done."],
        "image": PLACEHOLDER_IMG,
        "calories": None,
        "video_url": f"https://www.youtube.com/results?search_query={search}+recipe",
        "diet": diet,
        "halal": halal,
        "goal": goal or "",
        "servings": 2,
        "measurements": measurements,
        "match_score": score,
        "semantic_score": score,
        "matched_ingredients": matched,
        "missing_ingredients": [normalize_token(x) for x in missing],
        "uses_count": len(matched),
        "source_model": MODEL_ID,
        "generated": True,
    }


class RecipeGenerator:
    """Hugging Face Inference API client for T5 recipe generation."""

    def __init__(self, token: str, model: str = MODEL_ID) -> None:
        self.token = token
        self.model = model
        self.api_url = (
            f"https://router.huggingface.co/hf-inference/models/{model}"
        )
        self.api_url_legacy = (
            f"https://api-inference.huggingface.co/models/{model}"
        )

    def _extract_texts(self, data) -> list[str]:
        texts: list[str] = []
        if isinstance(data, str):
            return [data]
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    texts.append(item)
                elif isinstance(item, dict):
                    for key in ("generated_text", "translation_text", "summary_text", "text"):
                        if key in item and item[key]:
                            texts.append(str(item[key]))
                            break
        elif isinstance(data, dict):
            if "error" in data:
                raise RuntimeError(str(data["error"]))
            for key in ("generated_text", "translation_text", "summary_text"):
                if key in data:
                    texts.append(str(data[key]))
        return [t for t in texts if t and t.strip()]

    def _gen_params(self, seed: int | None = None, n: int = 1) -> dict:
        # Lower temperature / beam-ish settings = stick closer to input items
        params: dict = {
            "max_new_tokens": 200,
            "min_length": 24,
            "do_sample": True,
            "top_k": 40,
            "top_p": 0.85,
            "temperature": 0.7,
            "repetition_penalty": 1.15,
            "return_full_text": False,
        }
        if n > 1:
            params["num_return_sequences"] = n
        if seed is not None:
            params["seed"] = seed
        return params

    def _post(self, prompt: str, parameters: dict) -> list[str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "inputs": prompt,
            "parameters": parameters,
            "options": {"wait_for_model": True},
        }
        last_error = None
        timeout = float(os.getenv("T5_HTTP_TIMEOUT", "25"))
        max_attempts = 2
        for attempt in range(max_attempts):
            for url in (self.api_url, self.api_url_legacy):
                try:
                    with httpx.Client(timeout=timeout) as client:
                        resp = client.post(url, headers=headers, json=payload)
                    if resp.status_code == 503:
                        time.sleep(1 + attempt)
                        last_error = f"503 model loading ({url})"
                        continue
                    if resp.status_code >= 400:
                        last_error = f"{resp.status_code}: {resp.text[:300]}"
                        if parameters.get("num_return_sequences", 1) > 1:
                            parameters = dict(parameters)
                            parameters.pop("num_return_sequences", None)
                            continue
                        continue
                    texts = self._extract_texts(resp.json())
                    if texts:
                        return texts
                    last_error = "Empty generation response"
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
            if attempt + 1 < max_attempts:
                time.sleep(1)
        raise RuntimeError(f"T5 recipe generation failed: {last_error}")

    def generate(
        self,
        ingredients: list[str],
        top_k: int = 5,
        diet: str | None = None,
        halal: str | None = None,
        goal: str | None = None,
    ) -> list[dict]:
        cleaned = [i.strip() for i in ingredients if i and i.strip()]
        if not cleaned:
            return []

        # Model expects plain NER-style items (comma-separated food names)
        items = ", ".join(normalize_token(x) for x in cleaned)
        prompt = f"{PREFIX}{items}"

        results: list[dict] = []
        seen_titles: set[str] = set()

        try:
            queue = self._post(prompt, self._gen_params(n=min(top_k, 2)))
        except Exception:
            queue = []

        extras = 0
        while len(results) < top_k and (queue or extras < 1):
            if not queue:
                extras += 1
                try:
                    queue.extend(self._post(prompt, self._gen_params(seed=extras * 41 + len(cleaned))))
                except Exception:
                    break

            raw = queue.pop(0)
            recipe = parse_generated_recipe(raw, cleaned, goal=goal)
            if not recipe:
                continue
            if goal:
                recipe["goal"] = goal
            if (diet or halal) and not _passes_filters(recipe, diet, halal, None):
                continue
            key = recipe["name"].lower()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            results.append(recipe)

        results.sort(key=lambda r: (r.get("uses_count", 0), r.get("match_score", 0)), reverse=True)
        return results[:top_k]
