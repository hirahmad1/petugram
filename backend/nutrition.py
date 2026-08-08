"""Per-serving nutrition estimates (calories, protein, carbs, fat) for recipes."""

from __future__ import annotations

# Typical contribution per ingredient appearance in a home recipe (rough grams macros / kcal).
# Used when catalog recipes omit explicit protein/carbs/fat.
_INGREDIENT_MACROS: dict[str, tuple[float, float, float, float]] = {
    # kcal, protein_g, carbs_g, fat_g
    "pasta": (210, 7, 42, 1),
    "rice": (180, 4, 40, 0.5),
    "noodle": (190, 6, 38, 1),
    "bread": (120, 4, 22, 1.5),
    "flour": (110, 3, 23, 0.4),
    "potato": (90, 2, 20, 0.1),
    "tomato": (25, 1, 5, 0.2),
    "onion": (30, 1, 7, 0.1),
    "garlic": (10, 0.5, 2, 0),
    "carrot": (30, 0.7, 7, 0.1),
    "spinach": (15, 2, 2, 0.2),
    "lettuce": (10, 1, 2, 0.1),
    "cucumber": (10, 0.5, 2, 0.1),
    "pepper": (20, 1, 4, 0.2),
    "mushroom": (20, 2, 3, 0.3),
    "broccoli": (35, 3, 7, 0.4),
    "peas": (50, 3, 9, 0.2),
    "corn": (60, 2, 13, 0.7),
    "beans": (90, 6, 15, 0.5),
    "lentil": (100, 8, 17, 0.4),
    "chickpea": (110, 6, 18, 2),
    "chicken": (165, 31, 0, 3.5),
    "beef": (200, 26, 0, 10),
    "lamb": (210, 25, 0, 12),
    "fish": (140, 25, 0, 4),
    "salmon": (180, 22, 0, 10),
    "tuna": (130, 28, 0, 1),
    "shrimp": (90, 18, 0, 1),
    "egg": (90, 7, 0.5, 6),
    "milk": (60, 3, 5, 3),
    "cheese": (110, 7, 1, 9),
    "butter": (100, 0.1, 0, 11),
    "yogurt": (70, 5, 6, 3),
    "cream": (90, 1, 2, 9),
    "olive oil": (120, 0, 0, 14),
    "oil": (120, 0, 0, 14),
    "ghee": (120, 0, 0, 14),
    "soy sauce": (10, 1, 1, 0),
    "basil": (2, 0.2, 0.3, 0),
    "ginger": (5, 0.1, 1, 0),
    "lemon": (10, 0.2, 3, 0.1),
    "apple": (50, 0.3, 13, 0.2),
    "banana": (90, 1, 23, 0.3),
    "avocado": (120, 1.5, 6, 11),
    "tofu": (100, 10, 3, 6),
    "paneer": (150, 11, 2, 11),
    "pizza": (250, 10, 30, 10),
    "burger": (280, 15, 28, 12),
    "sugar": (50, 0, 13, 0),
    "honey": (40, 0, 11, 0),
    "coconut": (80, 1, 3, 8),
    "peanut": (100, 4, 3, 8),
    "almond": (90, 3, 3, 8),
}


def _lookup_macros(ingredient: str) -> tuple[float, float, float, float] | None:
    key = (ingredient or "").strip().lower()
    if not key:
        return None
    if key in _INGREDIENT_MACROS:
        return _INGREDIENT_MACROS[key]
    for name, macros in _INGREDIENT_MACROS.items():
        if name in key or key in name:
            return macros
    return None


def _round_macros(calories: float, protein: float, carbs: float, fat: float) -> dict:
    return {
        "calories": int(round(calories)),
        "protein": round(protein, 1),
        "carbs": round(carbs, 1),
        "fat": round(fat, 1),
        "calories_note": "per serving (estimate)",
    }


def estimate_nutrition(recipe: dict) -> dict:
    """Return calories/protein/carbs/fat for one serving; preserve explicit values when set."""
    servings = max(1, int(recipe.get("servings") or 2))
    has_p = recipe.get("protein") is not None
    has_c = recipe.get("carbs") is not None
    has_f = recipe.get("fat") is not None
    has_cal = recipe.get("calories") is not None

    if has_p and has_c and has_f and has_cal:
        return {
            "calories": int(recipe["calories"]),
            "protein": float(recipe["protein"]),
            "carbs": float(recipe["carbs"]),
            "fat": float(recipe["fat"]),
            "calories_note": recipe.get("calories_note") or "per serving",
        }

    cal = pro = carb = fat = 0.0
    matched = 0
    for raw in recipe.get("ingredients") or []:
        macros = _lookup_macros(str(raw))
        if not macros:
            continue
        matched += 1
        cal += macros[0]
        pro += macros[1]
        carb += macros[2]
        fat += macros[3]

    if matched:
        cal /= servings
        pro /= servings
        carb /= servings
        fat /= servings
    else:
        # Fallback ratios from calories or a light default plate
        base_cal = float(recipe["calories"]) if has_cal else 350.0
        cal = base_cal
        pro = base_cal * 0.18 / 4
        carb = base_cal * 0.50 / 4
        fat = base_cal * 0.32 / 9

    if has_cal:
        # Scale estimated macros to known calorie total
        target = float(recipe["calories"])
        current = max(cal, 1.0)
        scale = target / current
        cal = target
        pro *= scale
        carb *= scale
        fat *= scale
    if has_p:
        pro = float(recipe["protein"])
    if has_c:
        carb = float(recipe["carbs"])
    if has_f:
        fat = float(recipe["fat"])

    return _round_macros(cal, pro, carb, fat)


def attach_nutrition(recipe: dict) -> dict:
    out = dict(recipe)
    nutrition = estimate_nutrition(out)
    out["calories"] = nutrition["calories"]
    out["protein"] = nutrition["protein"]
    out["carbs"] = nutrition["carbs"]
    out["fat"] = nutrition["fat"]
    out["calories_note"] = nutrition["calories_note"]
    out["nutrition"] = {
        "calories": nutrition["calories"],
        "protein_g": nutrition["protein"],
        "carbs_g": nutrition["carbs"],
        "fat_g": nutrition["fat"],
        "note": nutrition["calories_note"],
    }
    return out
