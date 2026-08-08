"""Hugging Face embedding-based recipe matcher + dish-name search."""

from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

import httpx

from backend.filters import passes_diet
from backend.generator import match_leftovers, normalize_token, relevance_ok, score_relevance

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RECIPES_PATH = DATA / "recipes.json"
EMB_PATH = DATA / "embeddings.json"
INDEX_PATH = DATA / "recipe_index.json"

COMMON_INGREDIENTS = {
    "tomato", "egg", "onion", "rice", "chicken", "potato", "spinach", "garlic",
    "cheese", "milk", "butter", "bread", "pasta", "beef", "fish", "carrot",
    "pepper", "mushroom", "beans", "lentil", "tofu", "lemon", "yogurt",
    "banana", "apple", "corn", "cabbage", "shrimp", "pork", "basil", "oil",
}


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: list[float]) -> float:
    return math.sqrt(sum(x * x for x in a)) + 1e-9


def _cosine(a: list[float], b: list[float]) -> float:
    return _dot(a, b) / (_norm(a) * _norm(b))


def _mean_pool(matrix) -> list[float]:
    if hasattr(matrix, "tolist"):
        matrix = matrix.tolist()
    if not matrix:
        return []
    first = matrix[0]
    if isinstance(first, (int, float)):
        return [float(x) for x in matrix]
    if isinstance(first, list) and first and isinstance(first[0], (int, float)):
        dim = len(first)
        acc = [0.0] * dim
        for row in matrix:
            for i, v in enumerate(row):
                acc[i] += float(v)
        n = float(len(matrix))
        return [v / n for v in acc]
    flat = [_mean_pool(item) if isinstance(item, list) else float(item) for item in matrix]
    if flat and isinstance(flat[0], list):
        return _mean_pool(flat)
    return [float(x) for x in flat]


def _l2_normalize(vec: list[float]) -> list[float]:
    n = _norm(vec)
    return [v / n for v in vec]


def _recipe_text(recipe: dict) -> str:
    ingredients = ", ".join(recipe["ingredients"])
    steps = recipe.get("steps") or []
    body = " ".join(steps) if steps else recipe.get("instructions", "")
    return (
        f"Recipe: {recipe['name']}. Cuisine: {recipe['cuisine']}. "
        f"Ingredients: {ingredients}. Steps: {body}"
    )


def looks_like_dish_name(parts: list[str]) -> bool:
    """True when the query is likely a dish title rather than a leftover list."""
    if not parts:
        return False
    if len(parts) == 1:
        token = parts[0].strip().lower()
        words = token.split()
        if len(words) >= 2:
            return True
        if normalize_token(token) not in COMMON_INGREDIENTS and len(token) >= 4:
            return True
        return False
    # Multiple comma-separated items → leftovers, unless one long phrase only
    return False


def dish_query_text(parts: list[str]) -> str:
    return " ".join(p.strip() for p in parts if p.strip())


class RecipeMatcher:
    def __init__(self, token: str, model: str) -> None:
        self.token = token
        self.model = model
        self.api_url = (
            f"https://router.huggingface.co/hf-inference/models/"
            f"{model}/pipeline/feature-extraction"
        )
        with open(RECIPES_PATH, encoding="utf-8") as f:
            self.recipes: list[dict] = json.load(f)
        self._by_id = {
            str(r.get("id")): r for r in self.recipes if r.get("id") is not None
        }
        self.embeddings: list[list[float]] = []

    def get_by_id(self, recipe_id: str) -> dict | None:
        if not recipe_id:
            return None
        hit = self._by_id.get(str(recipe_id))
        return dict(hit) if hit else None

    def load(self) -> None:
        if EMB_PATH.exists() and INDEX_PATH.exists():
            with open(INDEX_PATH, encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("model") == self.model and meta.get("count") == len(self.recipes):
                with open(EMB_PATH, encoding="utf-8") as f:
                    self.embeddings = json.load(f)
                return

        texts = [_recipe_text(r) for r in self.recipes]
        self.embeddings = []
        for i, text in enumerate(texts):
            self.embeddings.append(self._embed(text))
            if i < len(texts) - 1:
                time.sleep(0.15)

        EMB_PATH.write_text(json.dumps(self.embeddings), encoding="utf-8")
        INDEX_PATH.write_text(
            json.dumps({"model": self.model, "count": len(self.recipes)}),
            encoding="utf-8",
        )

    def _embed(self, text: str) -> list[float]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {"inputs": text, "options": {"wait_for_model": True}}
        last_error = None
        embed_timeout = float(os.getenv("EMBED_HTTP_TIMEOUT", "12"))
        for attempt in range(2):
            try:
                with httpx.Client(timeout=embed_timeout) as client:
                    resp = client.post(self.api_url, headers=headers, json=payload)
                if resp.status_code == 503:
                    time.sleep(1 + attempt)
                    continue
                if resp.status_code >= 400:
                    last_error = f"{resp.status_code}: {resp.text[:300]}"
                    continue
                data = resp.json()
                vec = _mean_pool(data)
                if not vec:
                    raise RuntimeError("Empty embedding from Hugging Face")
                return _l2_normalize(vec)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        raise RuntimeError(f"Hugging Face embedding failed: {last_error}")

    def _passes_pref(
        self,
        recipe: dict,
        diet: str | None,
        halal: str | None,
        goal: str | None,
    ) -> bool:
        if not passes_diet(recipe, diet):
            return False
        if halal is not None and recipe.get("halal") != halal:
            return False
        if goal and recipe.get("goal") != goal:
            return False
        return True

    def search_by_name(
        self,
        query: str,
        top_k: int = 5,
        diet: str | None = None,
        halal: str | None = None,
        goal: str | None = None,
    ) -> list[dict]:
        """Find catalog recipes by dish name."""
        q = (query or "").strip().lower()
        q = re.sub(r"^(recipe\s+for|how\s+to\s+make|make\s+me|cook)\s+", "", q)
        q = re.sub(r"[^a-z0-9\s&']", " ", q)
        q = re.sub(r"\s+", " ", q).strip()
        if not q:
            return []

        q_tokens = {t for t in q.split() if len(t) > 1}
        scored: list[tuple[float, int]] = []

        for idx, recipe in enumerate(self.recipes):
            if not self._passes_pref(recipe, diet, halal, goal):
                continue
            name = str(recipe.get("name", "")).lower()
            cuisine = str(recipe.get("cuisine", "")).lower()
            name_norm = re.sub(r"[^a-z0-9\s&']", " ", name)
            name_norm = re.sub(r"\s+", " ", name_norm).strip()
            name_tokens = {t for t in name_norm.split() if len(t) > 1}

            if q == name_norm:
                score = 1.0
            elif q in name_norm or name_norm in q:
                score = 0.92
            else:
                overlap = len(q_tokens & name_tokens)
                if overlap == 0:
                    continue
                score = 0.55 * (overlap / max(len(q_tokens), 1)) + 0.35 * (
                    overlap / max(len(name_tokens), 1)
                )
                if cuisine and cuisine in q:
                    score += 0.08
                if overlap == len(q_tokens) and len(q_tokens) >= 2:
                    score = max(score, 0.88)

            if score < 0.45:
                continue
            scored.append((score, idx))

        scored.sort(key=lambda t: t[0], reverse=True)
        results = []
        for score, idx in scored[:top_k]:
            recipe = dict(self.recipes[idx])
            ingredients = [str(x).lower() for x in recipe.get("ingredients", [])]
            recipe["match_score"] = round(float(score) * 100, 1)
            recipe["semantic_score"] = recipe["match_score"]
            recipe["matched_ingredients"] = ingredients[: min(4, len(ingredients))]
            recipe["missing_ingredients"] = ingredients[min(4, len(ingredients)) :]
            recipe["uses_count"] = max(1, len(q_tokens & set(ingredients)) or len(ingredients[:2]))
            recipe["generated"] = False
            recipe["search_mode"] = "dish_name"
            results.append(recipe)
        return results

    def fetch_mealdb(self, query: str, top_k: int = 3) -> list[dict]:
        """Fallback: look up a dish name on TheMealDB."""
        q = (query or "").strip()
        if not q:
            return []
        url = f"https://www.themealdb.com/api/json/v1/1/search.php?s={quote_plus(q)}"
        try:
            with httpx.Client(timeout=12.0) as client:
                resp = client.get(url)
            if resp.status_code >= 400:
                return []
            meals = (resp.json() or {}).get("meals") or []
        except Exception:  # noqa: BLE001
            return []

        results = []
        for meal in meals[:top_k]:
            name = meal.get("strMeal") or "Recipe"
            ingredients = []
            measurements = []
            for i in range(1, 21):
                ing = (meal.get(f"strIngredient{i}") or "").strip()
                amt = (meal.get(f"strMeasure{i}") or "").strip()
                if not ing:
                    continue
                ingredients.append(ing.lower())
                measurements.append({"ingredient": ing.lower(), "amount": amt or "to taste"})
            instructions = (meal.get("strInstructions") or "").strip()
            steps = [s.strip() for s in re.split(r"\r?\n+", instructions) if s.strip()]
            if not steps and instructions:
                steps = [s.strip() for s in re.split(r"(?<=\.)\s+", instructions) if s.strip()]
            thumb = meal.get("strMealThumb") or (
                "https://images.unsplash.com/photo-1546069901-ba9599a7e63c"
                "?auto=format&fit=crop&w=900&q=80"
            )
            youtube = meal.get("strYoutube") or (
                f"https://www.youtube.com/results?search_query={quote_plus(name)}+recipe"
            )
            results.append(
                {
                    "id": f"mealdb-{meal.get('idMeal', hash(name))}",
                    "name": name,
                    "cuisine": meal.get("strArea") or "International",
                    "time_min": max(20, min(75, 10 + 3 * len(steps))),
                    "ingredients": ingredients,
                    "instructions": instructions,
                    "steps": steps or [instructions or "Follow classic preparation for this dish."],
                    "image": thumb,
                    "calories": None,
                    "video_url": youtube,
                    "diet": "non-vegan",
                    "halal": "halal",
                    "goal": "",
                    "servings": 2,
                    "measurements": measurements,
                    "match_score": 90.0,
                    "semantic_score": 90.0,
                    "matched_ingredients": ingredients[:4],
                    "missing_ingredients": ingredients[4:],
                    "uses_count": min(4, len(ingredients)),
                    "generated": False,
                    "search_mode": "dish_name",
                    "source_model": "themealdb",
                }
            )
        return results

    def match(
        self,
        ingredients: list[str],
        top_k: int = 5,
        diet: str | None = None,
        halal: str | None = None,
        goal: str | None = None,
    ) -> list[dict]:
        if not ingredients:
            return []

        cleaned = [i.strip() for i in ingredients if i and i.strip()]
        semantic: list[float] = [0.0] * len(self.recipes)

        try:
            if not self.embeddings and EMB_PATH.exists() and INDEX_PATH.exists():
                with open(INDEX_PATH, encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("model") == self.model and meta.get("count") == len(self.recipes):
                    with open(EMB_PATH, encoding="utf-8") as f:
                        self.embeddings = json.load(f)
            if self.embeddings and len(self.embeddings) == len(self.recipes):
                query = (
                    "Ingredients: "
                    + ", ".join(normalize_token(x) for x in cleaned)
                    + ". Recipe using these exact leftovers."
                )
                q = self._embed(query)
                semantic = [_cosine(q, e) for e in self.embeddings]
        except Exception:
            semantic = [0.0] * len(self.recipes)

        candidates: list[tuple[float, float, int, list[str], list[str]]] = []

        for idx, recipe in enumerate(self.recipes):
            if not self._passes_pref(recipe, diet, halal, goal):
                continue

            matched, missing = match_leftovers(cleaned, recipe["ingredients"])
            if not relevance_ok(matched, cleaned):
                continue

            overlap_score = score_relevance(matched, cleaned, recipe["ingredients"]) / 100.0
            sem = semantic[idx] if idx < len(semantic) else 0.0
            combined = 0.8 * overlap_score + 0.2 * max(0.0, sem)
            candidates.append((combined, sem, idx, matched, missing))

        candidates.sort(key=lambda t: (t[0], len(t[3])), reverse=True)

        results = []
        for combined, sem, idx, matched, missing in candidates[:top_k]:
            recipe = dict(self.recipes[idx])
            recipe["match_score"] = round(float(combined) * 100, 1)
            recipe["semantic_score"] = round(float(sem) * 100, 1)
            recipe["matched_ingredients"] = matched
            recipe["missing_ingredients"] = missing
            recipe["uses_count"] = len(matched)
            recipe["generated"] = False
            results.append(recipe)
        return results
