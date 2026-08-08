"""AI food scanner: detect ingredients from a photo using a vision-language model."""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import httpx

INGREDIENT_PROMPT = (
    "You are a kitchen assistant. Look at this photo carefully. "
    "List EVERY edible food ingredient you can see (produce, meat, dairy, grains, spices, leftovers). "
    "Ignore plates, bowls, utensils, packaging text, and non-food objects. "
    "Reply with ONLY a JSON array of lowercase ingredient names, e.g. "
    '["tomato","onion","chicken","rice"]. '
    "Use common grocery names (tomato not tomatoes; bell pepper not capsicum). "
    "If unsure, still include likely foods. Empty array if no food is visible."
)

RECEIPT_PROMPT = (
    "You are a grocery assistant reading a store receipt photo. "
    "Extract every food or grocery line item (ignore tax, total, payment, store address). "
    "Reply with ONLY a JSON array of lowercase ingredient/product names, e.g. "
    '["milk","eggs","bread","yogurt","chicken"]. '
    "Use short pantry-friendly names (milk not Full Cream Milk 1L). "
    "Skip non-food items (bags, magazines). Empty array if this is not a receipt."
)

FOOD_CHECK_PROMPT = (
    "Does this image show food, a cooked meal, leftovers, groceries, ingredients, "
    "a plate of food, or someone cooking? "
    "Reply with ONLY one word: yes or no."
)

# Canonical pantry names (longer first when matching)
KNOWN_INGREDIENTS: tuple[str, ...] = tuple(
    sorted(
        {
            "apple",
            "avocado",
            "banana",
            "basil",
            "beans",
            "beef",
            "bell pepper",
            "bread",
            "broccoli",
            "butter",
            "cabbage",
            "carrot",
            "cauliflower",
            "celery",
            "cheese",
            "chicken",
            "chickpea",
            "chili",
            "cilantro",
            "coconut",
            "corn",
            "cream",
            "cucumber",
            "egg",
            "eggplant",
            "fish",
            "flour",
            "garlic",
            "ginger",
            "grape",
            "honey",
            "lamb",
            "lemon",
            "lettuce",
            "lime",
            "mango",
            "milk",
            "mint",
            "mushroom",
            "noodles",
            "oats",
            "oil",
            "olive oil",
            "onion",
            "orange",
            "paneer",
            "pasta",
            "peach",
            "peanut",
            "peas",
            "pepper",
            "pineapple",
            "pork",
            "potato",
            "pumpkin",
            "rice",
            "salmon",
            "shrimp",
            "spinach",
            "strawberry",
            "sugar",
            "sweet potato",
            "tomato",
            "tofu",
            "tuna",
            "turkey",
            "yogurt",
            "zucchini",
            "okra",
            "radish",
            "beetroot",
            "pomegranate",
            "watermelon",
            "coriander",
            "parsley",
            "curry leaves",
            "green chili",
            "red chili",
            "soy sauce",
            "tomato paste",
            "lentils",
            "dal",
            "chapati",
            "roti",
            "naan",
            "edamame",
            "red cabbage",
        },
        key=len,
        reverse=True,
    )
)

SYNONYMS: dict[str, str] = {
    "tomatoes": "tomato",
    "potatoes": "potato",
    "onions": "onion",
    "eggs": "egg",
    "carrots": "carrot",
    "mushrooms": "mushroom",
    "peppers": "pepper",
    "capsicum": "bell pepper",
    "capsicums": "bell pepper",
    "bell peppers": "bell pepper",
    "chillies": "chili",
    "chilli": "chili",
    "chilies": "chili",
    "green chilli": "green chili",
    "red chilli": "red chili",
    "coriander leaves": "cilantro",
    "coriander": "cilantro",
    "dhania": "cilantro",
    "jeera": "cumin",
    "haldi": "turmeric",
    "aubergine": "eggplant",
    "brinjal": "eggplant",
    "courgette": "zucchini",
    "prawn": "shrimp",
    "prawns": "shrimp",
    "mince": "beef",
    "ground beef": "beef",
    "chicken breast": "chicken",
    "chicken thighs": "chicken",
    "drumstick": "chicken",
    "yoghurt": "yogurt",
    "curd": "yogurt",
    "mozzarella": "cheese",
    "cheddar": "cheese",
    "parmesan": "cheese",
    "basmati": "rice",
    "basmati rice": "rice",
    "brown rice": "rice",
    "spaghetti": "pasta",
    "macaroni": "pasta",
    "penne": "pasta",
    "noodles": "noodles",
    "ramen noodles": "noodles",
    "oliveoil": "olive oil",
    "veg": "vegetable",
    "vegetables": "vegetable",
    "leafy greens": "spinach",
    "baby spinach": "spinach",
    "spring onion": "onion",
    "green onion": "onion",
    "scallion": "onion",
    "shallot": "onion",
    "red cabbage": "cabbage",
    "purple cabbage": "cabbage",
    "soya bean": "edamame",
    "soybean": "edamame",
    "garlic clove": "garlic",
    "garlic cloves": "garlic",
    "cherry tomato": "tomato",
    "cherry tomatoes": "tomato",
    "roma tomato": "tomato",
    "sweet potatoes": "sweet potato",
    "lady finger": "okra",
    "bhindi": "okra",
    "aloo": "potato",
    "pyaz": "onion",
    "adrak": "ginger",
    "lehsun": "garlic",
    "tamatar": "tomato",
    "murgh": "chicken",
    "gosht": "lamb",
    "daal": "dal",
    "dhal": "dal",
    "chana": "chickpea",
    "channa": "chickpea",
    "chickpeas": "chickpea",
    "kidney beans": "beans",
    "black beans": "beans",
    "green beans": "beans",
    "soy": "soy sauce",
    "soya sauce": "soy sauce",
}


def _normalize_token(text: str) -> str:
    return re.sub(r"[^a-z0-9\s\-]", " ", (text or "").lower()).strip()


def _canonicalize(name: str) -> str | None:
    raw = _normalize_token(name).strip(" -_")
    if not raw or len(raw) < 2:
        return None
    if raw in SYNONYMS:
        raw = SYNONYMS[raw]
    if raw in KNOWN_INGREDIENTS:
        return raw
    # soft plural
    if raw.endswith("oes") and raw[:-2] in KNOWN_INGREDIENTS:
        return raw[:-2]
    if raw.endswith("ies") and (raw[:-3] + "y") in KNOWN_INGREDIENTS:
        return raw[:-3] + "y"
    if raw.endswith("s") and raw[:-1] in KNOWN_INGREDIENTS:
        return raw[:-1]
    for known in KNOWN_INGREDIENTS:
        if known in raw or raw in known:
            return known
    # Allow novel but plausible single/multi-word grocery terms from the VLM
    if re.fullmatch(r"[a-z]+(?:[ -][a-z]+){0,3}", raw) and len(raw) <= 40:
        return raw
    return None


def extract_ingredients_from_text(text: str) -> list[str]:
    blob = f" {_normalize_token(text)} "
    for src, dst in SYNONYMS.items():
        blob = re.sub(rf"\b{re.escape(src)}\b", dst, blob)
    found: list[str] = []
    seen: set[str] = set()
    for name in KNOWN_INGREDIENTS:
        if f" {name} " in blob:
            if name not in seen:
                seen.add(name)
                found.append(name)
            blob = blob.replace(name, " ")
    return found


def parse_ingredient_list(text: str) -> list[str]:
    """Parse VLM output: JSON array, bullets, or comma-separated names."""
    raw = (text or "").strip()
    if not raw:
        return []

    # Prefer JSON array anywhere in the response
    match = re.search(r"\[[\s\S]*?\]", raw)
    candidates: list[str] = []
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                candidates = [str(x) for x in data]
        except json.JSONDecodeError:
            candidates = []

    if not candidates:
        # Strip markdown fences / labels
        cleaned = re.sub(r"```(?:json)?|```", "", raw, flags=re.I)
        cleaned = re.sub(r"(?i)^(?:ingredients?|foods?|items?)\s*[:\-]\s*", "", cleaned.strip())
        # Split on commas / newlines / bullets
        parts = re.split(r"[\n,;/|]+", cleaned)
        for part in parts:
            part = re.sub(r"^[\s\-\*\d\.\)\(]+", "", part).strip()
            if part:
                candidates.append(part)

    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        canon = _canonicalize(item)
        if canon and canon not in seen and canon not in {"vegetable", "food", "ingredient", "none", "n/a"}:
            seen.add(canon)
            out.append(canon)
    # Also harvest known names from free text if JSON was sparse
    for item in extract_ingredients_from_text(raw):
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _guess_mime(image_bytes: bytes, filename: str = "") -> str:
    name = (filename or "").lower()
    if name.endswith(".png") or image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if name.endswith(".webp") or image_bytes[:4] == b"RIFF":
        return "image/webp"
    if name.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def _data_url(image_bytes: bytes, filename: str = "") -> str:
    mime = _guess_mime(image_bytes, filename)
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


class FoodScanner:
    """Detect ingredients with a vision-language model (HF + optional Gemini)."""

    def __init__(self, token: str, timeout: float = 60.0) -> None:
        self.token = (token or "").strip()
        self.timeout = timeout
        self.vlm_model = os.getenv(
            "HF_VISION_VLM_MODEL",
            "google/gemma-3-12b-it",
        ).strip()
        self.vlm_fallbacks = [
            m.strip()
            for m in os.getenv(
                "HF_VISION_VLM_FALLBACKS",
                "google/gemma-3-4b-it",
            ).split(",")
            if m.strip() and m.strip() != self.vlm_model
        ]
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_model = os.getenv("GEMINI_VISION_MODEL", "gemini-2.0-flash").strip()
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_model = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini").strip()

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _chat_completions(
        self, model: str, image_bytes: bytes, filename: str = "", prompt: str | None = None
    ) -> str:
        """OpenAI-compatible multimodal chat via HF router."""
        url = "https://router.huggingface.co/v1/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _data_url(image_bytes, filename)}},
                        {"type": "text", "text": prompt or INGREDIENT_PROMPT},
                    ],
                }
            ],
            "max_tokens": 256,
            "temperature": 0.1,
        }
        with httpx.Client(timeout=self.timeout) as client:
            res = client.post(url, headers=self._auth_headers(), json=payload)
            if res.status_code >= 400:
                raise RuntimeError(f"HF chat {res.status_code}: {res.text[:240]}")
            data = res.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Empty VLM response")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            texts = []
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    texts.append(str(part["text"]))
                elif isinstance(part, str):
                    texts.append(part)
            return "\n".join(texts).strip()
        return str(content or "").strip()

    def _legacy_caption(self, model: str, image_bytes: bytes) -> str:
        """BLIP-style captioning fallback (raw image bytes)."""
        urls = [
            f"https://router.huggingface.co/hf-inference/models/{model}",
            f"https://api-inference.huggingface.co/models/{model}",
        ]
        last_error: Exception | None = None
        for url in urls:
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    res = client.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {self.token}",
                            "Content-Type": "application/octet-stream",
                        },
                        content=image_bytes,
                        params={"wait_for_model": "true"},
                    )
                    if res.status_code >= 400:
                        last_error = RuntimeError(f"{res.status_code}: {res.text[:200]}")
                        continue
                    data = res.json()
                if isinstance(data, list) and data:
                    row = data[0]
                    if isinstance(row, dict):
                        return str(row.get("generated_text") or row.get("caption") or "")
                    return str(row)
                if isinstance(data, dict):
                    if data.get("error"):
                        raise RuntimeError(str(data["error"]))
                    return str(data.get("generated_text") or data.get("caption") or "")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if last_error:
            raise last_error
        return ""

    def _ask_vlm(
        self, image_bytes: bytes, filename: str = "", prompt: str | None = None
    ) -> tuple[str, str]:
        """Try VLMs in order; return (raw_text, model_id)."""
        models = [self.vlm_model, *[m for m in self.vlm_fallbacks if m != self.vlm_model]]
        errors: list[str] = []
        for model in models:
            try:
                if "blip" in model.lower() and "vl" not in model.lower():
                    text = self._legacy_caption(model, image_bytes)
                else:
                    text = self._chat_completions(model, image_bytes, filename, prompt)
                if text.strip():
                    return text, model
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{model}: {exc}")
                continue
        raise RuntimeError("; ".join(errors) or "All vision models failed")

    def _ask_gemini(self, image_bytes: bytes, filename: str = "", prompt: str | None = None) -> str:
        if not self.gemini_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        mime = _guess_mime(image_bytes, filename)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.gemini_model}:generateContent?key={self.gemini_key}"
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt or INGREDIENT_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 256},
        }
        with httpx.Client(timeout=self.timeout) as client:
            res = client.post(url, json=payload)
            if res.status_code >= 400:
                raise RuntimeError(f"Gemini {res.status_code}: {res.text[:240]}")
            data = res.json()
        parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
        texts = [str(p.get("text") or "") for p in parts if isinstance(p, dict)]
        return "\n".join(t for t in texts if t).strip()

    def _ask_openai(self, image_bytes: bytes, filename: str = "", prompt: str | None = None) -> str:
        if not self.openai_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        payload = {
            "model": self.openai_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt or INGREDIENT_PROMPT},
                        {"type": "image_url", "image_url": {"url": _data_url(image_bytes, filename)}},
                    ],
                }
            ],
            "max_tokens": 256,
            "temperature": 0.1,
        }
        with httpx.Client(timeout=self.timeout) as client:
            res = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if res.status_code >= 400:
                raise RuntimeError(f"OpenAI {res.status_code}: {res.text[:240]}")
            data = res.json()
        return str((((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "").strip()

    def classify_is_food(self, image_bytes: bytes, filename: str = "") -> dict[str, Any]:
        """Return whether an image is food/meal/grocery related (yes/no VLM check)."""
        if not image_bytes:
            raise ValueError("Empty image")
        if len(image_bytes) > 8 * 1024 * 1024:
            raise ValueError("Image too large (max 8 MB)")

        raw_text = ""
        source = ""
        warnings: list[str] = []

        for name, fn in (
            ("openai", lambda: self._ask_openai(image_bytes, filename, FOOD_CHECK_PROMPT)),
            ("gemini", lambda: self._ask_gemini(image_bytes, filename, FOOD_CHECK_PROMPT)),
        ):
            try:
                raw_text = fn()
                if raw_text:
                    source = name
                    break
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{name}: {exc}")

        if not raw_text and self.token:
            models = [self.vlm_model, *[m for m in self.vlm_fallbacks if m != self.vlm_model]]
            for model in models:
                try:
                    if "blip" in model.lower() and "vl" not in model.lower():
                        continue
                    raw_text = self._chat_completions(model, image_bytes, filename, FOOD_CHECK_PROMPT)
                    if raw_text.strip():
                        source = f"huggingface:{model}"
                        break
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"{model}: {exc}")

        if not raw_text:
            raise RuntimeError("; ".join(warnings) or "Food check failed")

        answer = raw_text.strip().lower()
        first = re.split(r"[\s,.:;!?]", answer, maxsplit=1)[0]
        if first in {"yes", "y", "true"}:
            is_food = True
        elif first in {"no", "n", "false"}:
            is_food = False
        elif re.search(r"\byes\b", answer) and not re.search(r"\bno\b", answer):
            is_food = True
        elif re.search(r"\bno\b", answer):
            is_food = False
        else:
            is_food = "yes" in answer[:40]

        return {
            "is_food": is_food,
            "raw": raw_text[:120],
            "source": source,
            "warnings": warnings,
        }

    def scan(self, image_bytes: bytes, filename: str = "", mode: str = "photo") -> dict:
        if not image_bytes:
            raise ValueError("Empty image")
        if len(image_bytes) > 8 * 1024 * 1024:
            raise ValueError("Image too large (max 8 MB)")
        if len(image_bytes) < 24:
            raise ValueError("File does not look like an image")

        scan_mode = (mode or "photo").strip().lower()
        if scan_mode not in {"photo", "receipt"}:
            scan_mode = "photo"
        prompt = RECEIPT_PROMPT if scan_mode == "receipt" else INGREDIENT_PROMPT
        max_items = 40 if scan_mode == "receipt" else 20

        raw_text = ""
        source = ""
        warnings: list[str] = []

        # Prefer dedicated vision APIs when configured (usually more accurate)
        for name, fn in (
            ("openai", lambda: self._ask_openai(image_bytes, filename, prompt)),
            ("gemini", lambda: self._ask_gemini(image_bytes, filename, prompt)),
        ):
            try:
                raw_text = fn()
                if raw_text:
                    source = name
                    break
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{name}: {exc}")

        if not raw_text:
            if not self.token:
                raise RuntimeError("HF_TOKEN is required for AI food scanning")
            try:
                raw_text, model_used = self._ask_vlm(image_bytes, filename, prompt)
                source = f"huggingface:{model_used}"
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"huggingface: {exc}")
                raise RuntimeError(
                    "Could not detect ingredients. Check HF_TOKEN / model access, "
                    "or set GEMINI_API_KEY for better results."
                ) from exc

        ingredients = parse_ingredient_list(raw_text)
        no_food_hint = bool(
            re.search(
                r"\b(no food|not food|no ingredients?|nothing edible|empty array|\[\s*\])\b",
                raw_text or "",
                re.I,
            )
        )
        detections = [
            {"ingredient": name, "confidence": round(0.92 - i * 0.03, 3), "qty": "1"}
            for i, name in enumerate(ingredients[:max_items])
        ]
        is_food = len(detections) > 0

        return {
            "detections": detections,
            "ingredients": [d["ingredient"] for d in detections],
            "caption": raw_text[:500],
            "labels": [],
            "count": len(detections),
            "is_food": is_food,
            "no_food_hint": no_food_hint and not is_food,
            "warnings": warnings,
            "source": source or "vision",
            "model": source,
            "mode": scan_mode,
        }
