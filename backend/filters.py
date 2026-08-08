"""Shared recipe search filters: diet, cuisine, time, difficulty, calories."""

from __future__ import annotations

from backend.nutrition import attach_nutrition

MEAT_TERMS = (
    "chicken",
    "beef",
    "pork",
    "lamb",
    "fish",
    "salmon",
    "tuna",
    "shrimp",
    "prawn",
    "bacon",
    "ham",
    "sausage",
    "turkey",
    "duck",
    "anchovy",
    "crab",
    "lobster",
    "mutton",
    "veal",
    "meat",
)

DAIRY_EGG_TERMS = ("milk", "cheese", "butter", "cream", "yogurt", "egg", "honey", "ghee")


def _ingredient_blob(recipe: dict) -> str:
    parts: list[str] = [str(x) for x in recipe.get("ingredients") or []]
    for row in recipe.get("measurements") or []:
        if row.get("ingredient"):
            parts.append(str(row["ingredient"]))
    return " ".join(parts).lower()


def has_meat(recipe: dict) -> bool:
    blob = _ingredient_blob(recipe)
    return any(term in blob for term in MEAT_TERMS)


def has_dairy_egg(recipe: dict) -> bool:
    blob = _ingredient_blob(recipe)
    return any(term in blob for term in DAIRY_EGG_TERMS)


def infer_diet_label(recipe: dict) -> str:
    explicit = str(recipe.get("diet") or "").strip().lower()
    if explicit in {"vegan", "non-vegan"}:
        return explicit
    if is_vegan_recipe(recipe):
        return "vegan"
    return "non-vegan"


def is_vegan_recipe(recipe: dict) -> bool:
    explicit = str(recipe.get("diet") or "").strip().lower()
    if explicit == "vegan":
        return True
    if explicit == "non-vegan":
        return False
    return not has_meat(recipe) and not has_dairy_egg(recipe)


def infer_difficulty(recipe: dict) -> str | None:
    if recipe.get("difficulty") in {"easy", "medium", "hard"}:
        return str(recipe["difficulty"])
    time_min = recipe.get("time_min")
    if time_min is None:
        return None
    if int(time_min) <= 25:
        return "easy"
    if int(time_min) <= 45:
        return "medium"
    return "hard"


def recipe_search_text(recipe: dict) -> str:
    chunks = [
        str(recipe.get("cuisine", "")),
        str(recipe.get("name", "")),
        str(recipe.get("instructions", "")),
        " ".join(str(x) for x in recipe.get("ingredients") or []),
    ]
    return " ".join(chunks).lower()


def matches_cuisine(recipe: dict, cuisine: str | None) -> bool:
    if not cuisine:
        return True
    needle = cuisine.strip().lower()
    if not needle:
        return True
    return needle in recipe_search_text(recipe)


def enrich_recipe(recipe: dict) -> dict:
    out = dict(recipe)
    out["diet"] = infer_diet_label(out)
    difficulty = infer_difficulty(out)
    if difficulty:
        out["difficulty"] = difficulty
    if out.get("time_min") is None:
        out["time_min"] = 30
    return attach_nutrition(out)


def passes_diet(recipe: dict, diet: str | None) -> bool:
    if not diet:
        return True
    label = infer_diet_label(recipe)
    if diet == "vegan":
        return label == "vegan"
    if diet == "non-vegan":
        return label == "non-vegan"
    return label == diet


def passes_search_filters(
    recipe: dict,
    *,
    cuisine: str | None = None,
    max_time_min: int | None = None,
    difficulty: str | None = None,
    diet: str | None = None,
    max_calories: int | None = None,
    halal: str | None = None,
    goal: str | None = None,
) -> bool:
    row = dict(recipe)

    if not matches_cuisine(row, cuisine):
        return False

    if max_time_min is not None:
        time_min = row.get("time_min")
        if time_min is not None and int(time_min) > int(max_time_min):
            return False

    if difficulty:
        recipe_difficulty = infer_difficulty(row)
        if recipe_difficulty is not None and recipe_difficulty != difficulty:
            return False

    if max_calories is not None:
        calories = row.get("calories")
        if calories is not None and int(calories) > int(max_calories):
            return False

    if not passes_diet(row, diet):
        return False

    if halal and row.get("halal") and row.get("halal") != halal:
        return False

    if goal and row.get("goal") and row.get("goal") != goal:
        return False

    return True


def normalize_filter_value(value: str | int | None) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value
