"""Barcode → grocery product lookup (Open Food Facts)."""

from __future__ import annotations

import re

import httpx

from backend.vision import parse_ingredient_list


def _clean_barcode(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) < 8 or len(digits) > 14:
        raise ValueError("Enter a valid barcode (8–14 digits)")
    return digits


def _product_to_ingredient(product: dict) -> str:
    name = (
        product.get("product_name")
        or product.get("product_name_en")
        or product.get("generic_name")
        or ""
    ).strip()
    if not name:
        cats = product.get("categories_tags") or []
        if cats:
            name = str(cats[0]).replace("en:", "").replace("-", " ")
    parsed = parse_ingredient_list(f'["{name}"]') if name else []
    if parsed:
        return parsed[0]
    # Fallback: first 2–3 words of product name
    words = re.sub(r"[^a-zA-Z0-9\s]", " ", name).split()
    return " ".join(words[:3]).lower() if words else "grocery item"


def lookup_barcode(barcode: str, timeout: float = 12.0) -> dict:
    code = _clean_barcode(barcode)
    url = f"https://world.openfoodfacts.org/api/v2/product/{code}.json"
    with httpx.Client(timeout=timeout, headers={"User-Agent": "Petugram/1.0 (food-waste-app)"}) as client:
        res = client.get(url)
        if res.status_code == 404:
            raise ValueError("Product not found for this barcode")
        if res.status_code >= 400:
            raise RuntimeError(f"Barcode lookup failed ({res.status_code})")
        data = res.json()
    if int(data.get("status") or 0) != 1 or not data.get("product"):
        raise ValueError("Product not found for this barcode")
    product = data["product"]
    ingredient = _product_to_ingredient(product)
    brand = (product.get("brands") or "").split(",")[0].strip()
    full_name = (product.get("product_name") or ingredient).strip()
    return {
        "barcode": code,
        "detections": [{"ingredient": ingredient, "confidence": 0.95, "qty": "1"}],
        "ingredients": [ingredient],
        "caption": f"{full_name}" + (f" · {brand}" if brand else ""),
        "count": 1,
        "is_food": True,
        "source": "openfoodfacts",
        "mode": "barcode",
        "product_name": full_name,
        "brand": brand or None,
        "message": f"Found {full_name}. Confirm to add to your fridge.",
    }
