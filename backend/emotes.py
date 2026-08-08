"""Emoji catalog + curated sticker packs for Inbox."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TWEMOJI_CDN = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@15.1.0/assets/72x72"
EMOJI_API = "https://www.getemoji.online/api/v1/emojis"
EMOJI_CACHE_TTL = 3600

_emoji_cache: dict[str, Any] = {"at": 0.0, "items": []}

FALLBACK_EMOJIS = [
    {"char": "😀", "name": "Grinning Face", "category": "smileys", "slug": "grinning-face"},
    {"char": "😃", "name": "Grinning Face With Big Eyes", "category": "smileys", "slug": "grinning-face-with-big-eyes"},
    {"char": "😄", "name": "Grinning Face With Smiling Eyes", "category": "smileys", "slug": "grinning-face-with-smiling-eyes"},
    {"char": "😁", "name": "Beaming Face With Smiling Eyes", "category": "smileys", "slug": "beaming-face-with-smiling-eyes"},
    {"char": "😆", "name": "Grinning Squinting Face", "category": "smileys", "slug": "grinning-squinting-face"},
    {"char": "😅", "name": "Grinning Face With Sweat", "category": "smileys", "slug": "grinning-face-with-sweat"},
    {"char": "😂", "name": "Face With Tears of Joy", "category": "smileys", "slug": "face-with-tears-of-joy"},
    {"char": "🤣", "name": "Rolling on the Floor Laughing", "category": "smileys", "slug": "rolling-on-the-floor-laughing"},
    {"char": "😊", "name": "Smiling Face With Smiling Eyes", "category": "smileys", "slug": "smiling-face-with-smiling-eyes"},
    {"char": "😍", "name": "Smiling Face With Heart-Eyes", "category": "smileys", "slug": "smiling-face-with-heart-eyes"},
    {"char": "🥰", "name": "Smiling Face With Hearts", "category": "smileys", "slug": "smiling-face-with-hearts"},
    {"char": "😘", "name": "Face Blowing a Kiss", "category": "smileys", "slug": "face-blowing-a-kiss"},
    {"char": "😎", "name": "Smiling Face With Sunglasses", "category": "smileys", "slug": "smiling-face-with-sunglasses"},
    {"char": "🥳", "name": "Partying Face", "category": "smileys", "slug": "partying-face"},
    {"char": "🤔", "name": "Thinking Face", "category": "smileys", "slug": "thinking-face"},
    {"char": "😢", "name": "Crying Face", "category": "smileys", "slug": "crying-face"},
    {"char": "😭", "name": "Loudly Crying Face", "category": "smileys", "slug": "loudly-crying-face"},
    {"char": "😤", "name": "Face With Steam From Nose", "category": "smileys", "slug": "face-with-steam-from-nose"},
    {"char": "🥺", "name": "Pleading Face", "category": "smileys", "slug": "pleading-face"},
    {"char": "👍", "name": "Thumbs Up", "category": "people", "slug": "thumbs-up"},
    {"char": "👎", "name": "Thumbs Down", "category": "people", "slug": "thumbs-down"},
    {"char": "👏", "name": "Clapping Hands", "category": "people", "slug": "clapping-hands"},
    {"char": "🙌", "name": "Raising Hands", "category": "people", "slug": "raising-hands"},
    {"char": "🙏", "name": "Folded Hands", "category": "people", "slug": "folded-hands"},
    {"char": "💪", "name": "Flexed Biceps", "category": "people", "slug": "flexed-biceps"},
    {"char": "❤️", "name": "Red Heart", "category": "symbols", "slug": "red-heart"},
    {"char": "🧡", "name": "Orange Heart", "category": "symbols", "slug": "orange-heart"},
    {"char": "💛", "name": "Yellow Heart", "category": "symbols", "slug": "yellow-heart"},
    {"char": "💚", "name": "Green Heart", "category": "symbols", "slug": "green-heart"},
    {"char": "🔥", "name": "Fire", "category": "symbols", "slug": "fire"},
    {"char": "✨", "name": "Sparkles", "category": "symbols", "slug": "sparkles"},
    {"char": "⭐", "name": "Star", "category": "symbols", "slug": "star"},
    {"char": "💯", "name": "Hundred Points", "category": "symbols", "slug": "hundred-points"},
    {"char": "🎉", "name": "Party Popper", "category": "symbols", "slug": "party-popper"},
    {"char": "🍕", "name": "Pizza", "category": "food", "slug": "pizza"},
    {"char": "🍔", "name": "Hamburger", "category": "food", "slug": "hamburger"},
    {"char": "🌮", "name": "Taco", "category": "food", "slug": "taco"},
    {"char": "🍣", "name": "Sushi", "category": "food", "slug": "sushi"},
    {"char": "🍜", "name": "Steaming Bowl", "category": "food", "slug": "steaming-bowl"},
    {"char": "🥗", "name": "Green Salad", "category": "food", "slug": "green-salad"},
    {"char": "🍝", "name": "Spaghetti", "category": "food", "slug": "spaghetti"},
    {"char": "🍛", "name": "Curry Rice", "category": "food", "slug": "curry-rice"},
    {"char": "🥑", "name": "Avocado", "category": "food", "slug": "avocado"},
    {"char": "🍓", "name": "Strawberry", "category": "food", "slug": "strawberry"},
    {"char": "☕", "name": "Hot Beverage", "category": "food", "slug": "hot-beverage"},
    {"char": "♻️", "name": "Recycling Symbol", "category": "symbols", "slug": "recycling-symbol"},
]

QUICK_REACTIONS = ["❤️", "😂", "🔥", "👍", "😮", "😢", "👏", "🎉"]


def emoji_codepoint(emoji: str) -> str:
    """Twemoji-style codepoint path for an emoji character."""
    chars = [c for c in emoji if ord(c) != 0xFE0F]
    return "-".join(f"{ord(c):x}" for c in chars)


def twemoji_url(emoji: str) -> str:
    code = emoji_codepoint(emoji)
    return f"{TWEMOJI_CDN}/{code}.png" if code else ""


def _sticker(emoji: str, sticker_id: str, label: str) -> dict:
    return {
        "id": sticker_id,
        "label": label,
        "emoji": emoji,
        "image_url": twemoji_url(emoji),
    }


STICKER_PACKS = [
    {
        "id": "foodie",
        "name": "Foodie",
        "description": "Meals, snacks, and cravings",
        "cover": "🍕",
        "stickers": [
            _sticker("🍕", "pizza", "Pizza"),
            _sticker("🍔", "burger", "Burger"),
            _sticker("🌮", "taco", "Taco"),
            _sticker("🍣", "sushi", "Sushi"),
            _sticker("🍜", "ramen", "Ramen"),
            _sticker("🍝", "pasta", "Pasta"),
            _sticker("🥗", "salad", "Salad"),
            _sticker("🍛", "curry", "Curry"),
            _sticker("🥘", "pan", "Skillet"),
            _sticker("🍲", "stew", "Stew"),
            _sticker("🥪", "sandwich", "Sandwich"),
            _sticker("🍳", "egg", "Breakfast"),
            _sticker("🥑", "avocado", "Avocado"),
            _sticker("🧀", "cheese", "Cheese"),
            _sticker("🍞", "bread", "Bread"),
            _sticker("🥐", "croissant", "Croissant"),
        ],
    },
    {
        "id": "sweet-tooth",
        "name": "Sweet Tooth",
        "description": "Desserts and drinks",
        "cover": "🍰",
        "stickers": [
            _sticker("🍰", "cake", "Cake"),
            _sticker("🧁", "cupcake", "Cupcake"),
            _sticker("🍪", "cookie", "Cookie"),
            _sticker("🍩", "donut", "Donut"),
            _sticker("🍦", "icecream", "Ice cream"),
            _sticker("🍫", "chocolate", "Chocolate"),
            _sticker("🍬", "candy", "Candy"),
            _sticker("☕", "coffee", "Coffee"),
            _sticker("🍵", "tea", "Tea"),
            _sticker("🧃", "juice", "Juice"),
            _sticker("🧋", "boba", "Boba"),
            _sticker("🥂", "cheers", "Cheers"),
        ],
    },
    {
        "id": "vibes",
        "name": "Vibes",
        "description": "Reactions with energy",
        "cover": "🔥",
        "stickers": [
            _sticker("🔥", "fire", "Fire"),
            _sticker("✨", "sparkle", "Sparkle"),
            _sticker("💯", "hundred", "100"),
            _sticker("🎉", "party", "Party"),
            _sticker("🥳", "celebrate", "Celebrate"),
            _sticker("😎", "cool", "Cool"),
            _sticker("😍", "love", "Love it"),
            _sticker("😂", "lol", "LOL"),
            _sticker("🤯", "mindblown", "Mind blown"),
            _sticker("🙌", "hands", "Yes"),
            _sticker("💪", "strong", "Strong"),
            _sticker("👏", "clap", "Clap"),
        ],
    },
    {
        "id": "zero-waste",
        "name": "Zero Waste",
        "description": "Cook more, waste less",
        "cover": "♻️",
        "stickers": [
            _sticker("♻️", "recycle", "Recycle"),
            _sticker("🌍", "earth", "Earth"),
            _sticker("🌱", "sprout", "Sprout"),
            _sticker("🌿", "herb", "Herb"),
            _sticker("🥦", "broccoli", "Greens"),
            _sticker("🥕", "carrot", "Carrot"),
            _sticker("🍎", "apple", "Apple"),
            _sticker("🍌", "banana", "Banana"),
            _sticker("🍅", "tomato", "Tomato"),
            _sticker("🌽", "corn", "Corn"),
            _sticker("🧑‍🍳", "chef", "Chef"),
            _sticker("💚", "greenheart", "Green heart"),
        ],
    },
]


def list_sticker_packs() -> list[dict]:
    return [
        {
            "id": pack["id"],
            "name": pack["name"],
            "description": pack["description"],
            "cover": pack["cover"],
            "cover_image": twemoji_url(pack["cover"]),
            "count": len(pack["stickers"]),
            "stickers": pack["stickers"],
        }
        for pack in STICKER_PACKS
    ]


def get_sticker(pack_id: str, sticker_id: str) -> dict | None:
    for pack in STICKER_PACKS:
        if pack["id"] != pack_id:
            continue
        for sticker in pack["stickers"]:
            if sticker["id"] == sticker_id:
                return {**sticker, "pack_id": pack_id, "pack_name": pack["name"]}
    return None


def _normalize_remote_emoji(item: dict) -> dict | None:
    char = (item.get("char") or item.get("emoji") or "").strip()
    if not char:
        return None
    name = (item.get("name") or item.get("slug") or char).strip()
    category = (item.get("category") or item.get("group") or "smileys").strip().lower()
    slug = (item.get("slug") or name.lower().replace(" ", "-")).strip()
    return {
        "char": char,
        "name": name,
        "category": category,
        "slug": slug,
        "image_url": twemoji_url(char),
    }


def _fetch_remote_emojis(limit: int = 240) -> list[dict]:
    url = f"{EMOJI_API}?limit={min(max(limit, 20), 500)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Petugram/1.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    rows = payload.get("data") or payload.get("emojis") or []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_remote_emoji(row)
        if normalized:
            out.append(normalized)
    return out


def list_emojis(category: str | None = None, q: str | None = None, limit: int = 120) -> dict:
    now = time.time()
    items = _emoji_cache.get("items") or []
    if not items or now - float(_emoji_cache.get("at") or 0) > EMOJI_CACHE_TTL:
        try:
            items = _fetch_remote_emojis(300)
            source = "getemoji.online"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
            items = [
                {
                    **row,
                    "image_url": twemoji_url(row["char"]),
                }
                for row in FALLBACK_EMOJIS
            ]
            source = "fallback"
        _emoji_cache["items"] = items
        _emoji_cache["at"] = now
        _emoji_cache["source"] = source
    else:
        source = _emoji_cache.get("source") or "cache"

    filtered = items
    cat = (category or "").strip().lower()
    if cat and cat != "all":
        filtered = [e for e in filtered if cat in str(e.get("category") or "").lower()]
    query = (q or "").strip().lower()
    if query:
        filtered = [
            e
            for e in filtered
            if query in str(e.get("name") or "").lower()
            or query in str(e.get("slug") or "").lower()
            or query in str(e.get("char") or "")
        ]

    limit = max(1, min(int(limit or 120), 300))
    categories = sorted({str(e.get("category") or "smileys") for e in items})
    return {
        "emojis": filtered[:limit],
        "categories": categories,
        "quick_reactions": QUICK_REACTIONS,
        "source": source,
        "total": len(filtered),
    }
