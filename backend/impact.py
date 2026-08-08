"""Location-aware money saved and food-waste impact estimates."""

from __future__ import annotations

# Approximate local value of one leftover ingredient kept out of the bin,
# and typical edible weight / CO₂ avoided per ingredient.
LOCATIONS: dict[str, dict] = {
    "PK": {
        "code": "PK",
        "label": "Pakistan",
        "currency": "PKR",
        "symbol": "Rs",
        "cost_per_ingredient": 120.0,
        "kg_per_ingredient": 0.18,
        "co2_kg_per_ingredient": 0.45,
    },
    "IN": {
        "code": "IN",
        "label": "India",
        "currency": "INR",
        "symbol": "₹",
        "cost_per_ingredient": 45.0,
        "kg_per_ingredient": 0.16,
        "co2_kg_per_ingredient": 0.42,
    },
    "BD": {
        "code": "BD",
        "label": "Bangladesh",
        "currency": "BDT",
        "symbol": "৳",
        "cost_per_ingredient": 55.0,
        "kg_per_ingredient": 0.16,
        "co2_kg_per_ingredient": 0.42,
    },
    "AE": {
        "code": "AE",
        "label": "United Arab Emirates",
        "currency": "AED",
        "symbol": "AED",
        "cost_per_ingredient": 6.5,
        "kg_per_ingredient": 0.2,
        "co2_kg_per_ingredient": 0.5,
    },
    "SA": {
        "code": "SA",
        "label": "Saudi Arabia",
        "currency": "SAR",
        "symbol": "SAR",
        "cost_per_ingredient": 6.0,
        "kg_per_ingredient": 0.2,
        "co2_kg_per_ingredient": 0.5,
    },
    "GB": {
        "code": "GB",
        "label": "United Kingdom",
        "currency": "GBP",
        "symbol": "£",
        "cost_per_ingredient": 1.8,
        "kg_per_ingredient": 0.22,
        "co2_kg_per_ingredient": 0.55,
    },
    "US": {
        "code": "US",
        "label": "United States",
        "currency": "USD",
        "symbol": "$",
        "cost_per_ingredient": 2.25,
        "kg_per_ingredient": 0.22,
        "co2_kg_per_ingredient": 0.55,
    },
    "CA": {
        "code": "CA",
        "label": "Canada",
        "currency": "CAD",
        "symbol": "CA$",
        "cost_per_ingredient": 2.4,
        "kg_per_ingredient": 0.22,
        "co2_kg_per_ingredient": 0.55,
    },
    "AU": {
        "code": "AU",
        "label": "Australia",
        "currency": "AUD",
        "symbol": "A$",
        "cost_per_ingredient": 2.5,
        "kg_per_ingredient": 0.22,
        "co2_kg_per_ingredient": 0.55,
    },
    "GLOBAL": {
        "code": "GLOBAL",
        "label": "Worldwide average",
        "currency": "USD",
        "symbol": "$",
        "cost_per_ingredient": 1.75,
        "kg_per_ingredient": 0.2,
        "co2_kg_per_ingredient": 0.5,
    },
}

DEFAULT_LOCATION = "PK"


def list_locations() -> list[dict]:
    return [
        {"code": loc["code"], "label": loc["label"], "currency": loc["currency"], "symbol": loc["symbol"]}
        for code, loc in LOCATIONS.items()
        if code != "GLOBAL"
    ] + [
        {
            "code": "GLOBAL",
            "label": LOCATIONS["GLOBAL"]["label"],
            "currency": LOCATIONS["GLOBAL"]["currency"],
            "symbol": LOCATIONS["GLOBAL"]["symbol"],
        }
    ]


def resolve_location(code: str | None) -> dict:
    key = (code or DEFAULT_LOCATION).strip().upper()
    return LOCATIONS.get(key) or LOCATIONS[DEFAULT_LOCATION]


def _money_display(amount: float, loc: dict) -> str:
    symbol = loc["symbol"]
    currency = loc["currency"]
    if currency in {"PKR", "INR", "BDT"}:
        rounded = int(round(amount))
        return f"{symbol} {rounded:,}"
    return f"{symbol}{amount:,.2f}"


def compute_impact(
    *,
    ingredients_saved: int,
    meals: int = 0,
    location_code: str | None = None,
) -> dict:
    loc = resolve_location(location_code)
    ingredients = max(0, int(ingredients_saved or 0))
    meal_count = max(0, int(meals or 0))
    money = ingredients * float(loc["cost_per_ingredient"])
    waste_kg = ingredients * float(loc["kg_per_ingredient"])
    co2_kg = ingredients * float(loc["co2_kg_per_ingredient"])
    return {
        "location_code": loc["code"],
        "location_label": loc["label"],
        "currency": loc["currency"],
        "currency_symbol": loc["symbol"],
        "ingredients_saved": ingredients,
        "meals_cooked": meal_count,
        "money_saved": round(money, 2),
        "money_saved_display": _money_display(money, loc),
        "waste_reduced_kg": round(waste_kg, 2),
        "co2_avoided_kg": round(co2_kg, 2),
        "rates": {
            "cost_per_ingredient": loc["cost_per_ingredient"],
            "kg_per_ingredient": loc["kg_per_ingredient"],
            "co2_kg_per_ingredient": loc["co2_kg_per_ingredient"],
        },
    }
