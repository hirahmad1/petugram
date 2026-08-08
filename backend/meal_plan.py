"""Build multi-day meal plans (breakfast, lunch, dinner, snacks) from leftovers."""

from __future__ import annotations

from backend.filters import enrich_recipe, passes_search_filters
from backend.generator import attach_substitutions

MEAL_SLOTS = ("breakfast", "lunch", "dinner", "snack")

SLOT_LABELS = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "snack": "Snack",
}

# Soft boosts so matcher leans toward slot-appropriate dishes
SLOT_HINTS: dict[str, list[str]] = {
    "breakfast": ["egg", "milk", "bread", "oat", "yogurt", "banana", "butter"],
    "lunch": ["rice", "salad", "chicken", "tomato", "bread", "bean", "pasta"],
    "dinner": ["chicken", "rice", "potato", "onion", "garlic", "tomato", "fish"],
    "snack": ["yogurt", "fruit", "banana", "nuts", "cheese", "apple", "hummus"],
}

# Prefer shorter cook times for breakfast / snacks when user didn't set a cap
SLOT_MAX_TIME: dict[str, int | None] = {
    "breakfast": 30,
    "lunch": 45,
    "dinner": None,
    "snack": 20,
}


def _recipe_key(recipe: dict) -> str:
    rid = str(recipe.get("id") or "").strip().lower()
    if rid:
        return f"id:{rid}"
    name = str(recipe.get("name") or "").strip().lower()
    return f"name:{name}" if name else ""


def _clean_ingredients(ingredients: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in ingredients:
        item = str(raw or "").strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _day_subset(ingredients: list[str], day_index: int, days: int) -> list[str]:
    """Rotate pantry ingredients so each day emphasizes a different slice."""
    n = len(ingredients)
    if n == 0:
        return []
    if n <= 3:
        return list(ingredients)
    window = min(5, max(3, n // 2))
    start = (day_index * max(1, n // max(days, 1))) % n
    subset = [ingredients[(start + i) % n] for i in range(window)]
    if ingredients[0] not in subset:
        subset = [ingredients[0], *subset[:-1]]
    return subset


def _slot_query(base: list[str], slot: str, slot_index: int) -> list[str]:
    """Blend user leftovers with light slot hints (prefer ingredients the user already has)."""
    hints = SLOT_HINTS.get(slot) or []
    have = {x.lower() for x in base}
    preferred = [h for h in hints if h.lower() in have or any(h.lower() in b.lower() for b in base)]
    extras = [h for h in hints if h not in preferred]
    # Rotate hint extras so slots within a day diverge
    rotated = extras[slot_index:] + extras[:slot_index]
    blended = list(base)
    for tip in preferred[:2] + rotated[:2]:
        if tip.lower() not in {b.lower() for b in blended}:
            blended.append(tip)
    return blended[:8] if blended else list(hints[:4])


def _slot_filters(base_filters: dict, slot: str) -> dict:
    filters = dict(base_filters)
    soft_cap = SLOT_MAX_TIME.get(slot)
    user_cap = filters.get("max_time_min")
    if soft_cap is not None:
        if user_cap is None:
            filters["max_time_min"] = soft_cap
        else:
            filters["max_time_min"] = min(int(user_cap), soft_cap)
    # Breakfast cuisine bias when user didn't pick one
    if slot == "breakfast" and not filters.get("cuisine"):
        filters = {**filters, "cuisine": None}  # no hard filter; scoring via hints
    return filters


def _slot_score_bonus(recipe: dict, slot: str) -> float:
    """Light ranking nudge by cuisine / time / name keywords."""
    bonus = 0.0
    name = str(recipe.get("name") or "").lower()
    cuisine = str(recipe.get("cuisine") or "").lower()
    time_min = recipe.get("time_min")
    try:
        time_val = int(time_min) if time_min is not None else 99
    except (TypeError, ValueError):
        time_val = 99

    if slot == "breakfast":
        if "breakfast" in cuisine or any(w in name for w in ("omelette", "pancake", "toast", "oatmeal", "shakshuka", "egg")):
            bonus += 0.35
        if time_val <= 25:
            bonus += 0.15
    elif slot == "lunch":
        if any(w in name for w in ("salad", "sandwich", "soup", "wrap", "bowl")):
            bonus += 0.25
        if time_val <= 40:
            bonus += 0.1
    elif slot == "dinner":
        if time_val >= 25:
            bonus += 0.1
        if any(w in name for w in ("curry", "stew", "roast", "pasta", "biryani")):
            bonus += 0.2
    elif slot == "snack":
        if time_val <= 15:
            bonus += 0.35
        if any(w in name for w in ("smoothie", "yogurt", "dip", "hummus", "fruit", "toast", "snack")):
            bonus += 0.3
        if time_val > 30:
            bonus -= 0.2
    return bonus


def _pick_recipe(
    candidates: list[dict],
    *,
    used: set[str],
    exclude_ids: set[str],
    filters: dict,
    slot: str,
    taste: dict | None = None,
) -> dict | None:
    ranked: list[tuple[float, dict]] = []
    engine = None
    if taste:
        try:
            from backend.preferences import PreferenceEngine

            engine = PreferenceEngine()
        except Exception:
            engine = None
    for recipe in candidates:
        key = _recipe_key(recipe)
        if not key or key in used:
            continue
        rid = str(recipe.get("id") or "").strip()
        if rid and rid in exclude_ids:
            continue
        if key in exclude_ids:
            continue
        enriched = enrich_recipe(recipe)
        if not passes_search_filters(enriched, **filters):
            continue
        if engine and taste and engine.blocks_allergy(enriched, taste):
            continue
        score = float(enriched.get("match_score") or 0) + _slot_score_bonus(enriched, slot) * 100
        if engine and taste:
            score = engine.boost_recipe(enriched, taste, score)
        ranked.append((score, enriched))
    if not ranked:
        return None
    ranked.sort(key=lambda t: t[0], reverse=True)
    return ranked[0][1]


def _fetch_candidates(matcher, query: list[str], filters: dict, top_k: int, google_search=None) -> list[dict]:
    candidates: list[dict] = []
    if matcher is not None and query:
        try:
            candidates = matcher.match(
                query,
                top_k=top_k,
                diet=filters.get("diet"),
                halal=filters.get("halal"),
                goal=filters.get("goal"),
            )
        except Exception:
            candidates = []
    if google_search is not None and query and len(candidates) < max(3, top_k // 2):
        try:
            extra = google_search.search(query, top_k=min(4, top_k))
            seen = {_recipe_key(r) for r in candidates}
            for recipe in extra:
                key = _recipe_key(recipe)
                if key and key not in seen:
                    candidates.append(recipe)
                    seen.add(key)
        except Exception:
            pass
    return candidates


def build_plan(
    ingredients: list[str],
    days: int,
    filters: dict | None,
    matcher,
    exclude_ids: list[str] | None = None,
    google_search=None,
    taste: dict | None = None,
) -> dict:
    """Generate breakfast / lunch / dinner / snack per day from leftovers."""
    cleaned = _clean_ingredients(ingredients)
    days = max(3, min(7, int(days or 3)))
    filter_kwargs = {
        "cuisine": (filters or {}).get("cuisine"),
        "max_time_min": (filters or {}).get("max_time_min"),
        "difficulty": (filters or {}).get("difficulty"),
        "diet": (filters or {}).get("diet"),
        "max_calories": (filters or {}).get("max_calories"),
        "halal": (filters or {}).get("halal"),
        "goal": (filters or {}).get("goal"),
    }
    exclude = {str(x).strip() for x in (exclude_ids or []) if str(x).strip()}
    used: set[str] = set()
    plan_days: list[dict] = []

    pool_top = min(40, max(days * len(MEAL_SLOTS) * 2, 16))
    pool = _fetch_candidates(matcher, cleaned, filter_kwargs, pool_top, google_search=google_search)

    for day_i in range(days):
        subset = _day_subset(cleaned, day_i, days)
        meals: list[dict] = []
        for slot_i, slot in enumerate(MEAL_SLOTS):
            slot_filters = _slot_filters(filter_kwargs, slot)
            query = _slot_query(subset or cleaned, slot, slot_i + day_i)
            day_candidates = _fetch_candidates(matcher, query, slot_filters, 10, google_search=None)
            merged = day_candidates + [
                r for r in pool if _recipe_key(r) not in {_recipe_key(x) for x in day_candidates}
            ]
            recipe = _pick_recipe(
                merged,
                used=used,
                exclude_ids=exclude,
                filters=slot_filters,
                slot=slot,
                taste=taste,
            )
            if recipe is None and pool:
                recipe = _pick_recipe(
                    pool,
                    used=used,
                    exclude_ids=exclude,
                    filters=slot_filters,
                    slot=slot,
                    taste=taste,
                )
            if recipe is None:
                meals.append({"slot": slot, "label": SLOT_LABELS[slot], "recipe": None})
                continue
            used.add(_recipe_key(recipe))
            attach_substitutions([recipe], query or cleaned)
            meals.append({"slot": slot, "label": SLOT_LABELS[slot], "recipe": recipe})

        plan_days.append(
            {
                "day": day_i + 1,
                "label": f"Day {day_i + 1}",
                "meals": meals,
                "meal": next((m for m in meals if m["slot"] == "dinner" and m.get("recipe")), meals[0] if meals else None),
            }
        )

    filled = sum(1 for d in plan_days for m in d.get("meals") or [] if m.get("recipe"))
    return {
        "days": plan_days,
        "ingredients_used": cleaned,
        "filters": {k: v for k, v in filter_kwargs.items() if v is not None},
        "days_count": days,
        "slots": list(MEAL_SLOTS),
        "meals_filled": filled,
        "preferences_applied": bool(taste and taste.get("signals")),
    }


def swap_day(
    ingredients: list[str],
    day: int,
    filters: dict | None,
    matcher,
    exclude_ids: list[str] | None = None,
    google_search=None,
    slot: str = "dinner",
    taste: dict | None = None,
) -> dict:
    """Pick a replacement recipe for one day + slot."""
    cleaned = _clean_ingredients(ingredients)
    day_index = max(1, int(day)) - 1
    slot = (slot or "dinner").strip().lower()
    if slot not in MEAL_SLOTS:
        slot = "dinner"
    filter_kwargs = {
        "cuisine": (filters or {}).get("cuisine"),
        "max_time_min": (filters or {}).get("max_time_min"),
        "difficulty": (filters or {}).get("difficulty"),
        "diet": (filters or {}).get("diet"),
        "max_calories": (filters or {}).get("max_calories"),
        "halal": (filters or {}).get("halal"),
        "goal": (filters or {}).get("goal"),
    }
    exclude = {str(x).strip() for x in (exclude_ids or []) if str(x).strip()}
    subset = _day_subset(cleaned, day_index, 7)
    slot_filters = _slot_filters(filter_kwargs, slot)
    query = _slot_query(subset or cleaned, slot, MEAL_SLOTS.index(slot) + day_index)
    candidates = _fetch_candidates(matcher, query, slot_filters, 14, google_search=google_search)
    recipe = _pick_recipe(
        candidates,
        used=set(),
        exclude_ids=exclude,
        filters=slot_filters,
        slot=slot,
        taste=taste,
    )
    meal = {"slot": slot, "label": SLOT_LABELS[slot], "recipe": recipe}
    if recipe:
        attach_substitutions([recipe], query or cleaned)
    return {
        "day": day_index + 1,
        "label": f"Day {day_index + 1}",
        "slot": slot,
        "meal": meal,
    }
