"""Build consolidated grocery lists from meal plans / missing ingredients."""

from __future__ import annotations

from collections import Counter

from backend.generator import normalize_token, soft_match_ingredient, suggest_substitutions


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if "," in text:
            return [p.strip() for p in text.split(",") if p.strip()]
        return [text]
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            if isinstance(item, dict) and item.get("ingredient"):
                out.append(str(item["ingredient"]).strip())
            else:
                text = str(item or "").strip()
                if text:
                    out.append(text)
        return out
    text = str(value).strip()
    return [text] if text else []


def _have_item(need: str, have: list[str]) -> bool:
    return any(soft_match_ingredient(h, need) for h in have if h)


def missing_from_plan(plan: dict | None) -> list[str]:
    """Collect every missing ingredient mentioned across plan meals."""
    items: list[str] = []
    for day in (plan or {}).get("days") or []:
        meals = day.get("meals") or []
        if not meals and day.get("meal"):
            meals = [day["meal"]]
        for meal in meals:
            recipe = (meal or {}).get("recipe") or {}
            items.extend(_as_list(recipe.get("missing_ingredients")))
    return items


def build_grocery_list(
    *,
    plan: dict | None = None,
    missing: list[str] | None = None,
    have: list[str] | None = None,
) -> dict:
    """
    Aggregate missing ingredients, drop anything already on hand,
    attach store tips and optional substitutes.
    """
    raw = list(missing or [])
    raw.extend(missing_from_plan(plan))
    have_list = [str(h).strip() for h in (have or []) if h and str(h).strip()]

    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    for item in raw:
        name = str(item or "").strip()
        if not name:
            continue
        if _have_item(name, have_list):
            continue
        key = normalize_token(name) or name.lower()
        counts[key] += 1
        display.setdefault(key, name)

    # Also skip if a substitute they already have covers it? Keep simple: only direct have.

    items = []
    for key, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        name = display[key]
        subs = suggest_substitutions([name], have_list)
        you_have_sub = (subs[0].get("you_have") if subs else None) or []
        items.append(
            {
                "ingredient": name,
                "key": key,
                "count": count,
                "meals_needed": count,
                "substitutes": (subs[0].get("substitutes") if subs else [])[:4],
                "you_have_substitute": you_have_sub[:2],
            }
        )

    covered = []
    for item in raw:
        name = str(item or "").strip()
        if name and _have_item(name, have_list):
            covered.append(name)

    return {
        "items": items,
        "count": len(items),
        "have": have_list,
        "already_have": sorted(set(covered), key=str.lower),
        "source": "meal_plan" if plan else "missing",
    }
