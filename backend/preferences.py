"""Learn user taste from profile, cook history, favorites, posts, and restaurants."""

from __future__ import annotations

from collections import Counter
from typing import Any

from backend.generator import normalize_token, soft_match_ingredient


def _bump(counter: Counter, key: str | None, weight: float = 1.0) -> None:
    if not key:
        return
    text = str(key).strip()
    if not text:
        return
    counter[text] += weight


class PreferenceEngine:
    """Implicit preference learning — no separate ML model."""

    def __init__(self, store=None, post_store=None) -> None:
        self.store = store
        self.post_store = post_store

    def load(self, user_id: str | None) -> dict[str, Any]:
        empty = {
            "user_id": user_id,
            "allergies": [],
            "cuisine_weights": {},
            "favorite_recipe_ids": set(),
            "cooked_recipe_ids": set(),
            "cooked_names": Counter(),
            "liked_recipe_tags": Counter(),
            "liked_restaurants": Counter(),
            "liked_hashtags": Counter(),
            "following_ids": set(),
            "top_cuisines": [],
            "signals": 0,
        }
        if not user_id or self.store is None:
            return empty

        profile = {}
        try:
            profile = self.store.get_profile(user_id) or {}
        except Exception:
            profile = {}

        allergies = [str(a).strip() for a in (profile.get("allergies") or []) if a]
        cuisine_weights: Counter = Counter()
        for c in profile.get("cuisines") or []:
            _bump(cuisine_weights, c, 3.0)

        favorite_ids: set[str] = set()
        try:
            for fav in self.store.list_favorites(user_id) or []:
                rid = str(fav.get("recipe_id") or (fav.get("recipe") or {}).get("id") or "")
                if rid:
                    favorite_ids.add(rid)
                recipe = fav.get("recipe") or {}
                _bump(cuisine_weights, recipe.get("cuisine"), 2.5)
                _bump(cuisine_weights, None)
        except Exception:
            pass

        cooked_ids: set[str] = set()
        cooked_names: Counter = Counter()
        try:
            for row in self.store.cook_history(user_id, limit=40) or []:
                rid = str(row.get("recipe_id") or "")
                if rid:
                    cooked_ids.add(rid)
                name = row.get("recipe_name")
                if name:
                    cooked_names[str(name).strip().lower()] += 1
        except Exception:
            pass

        following_ids: set[str] = set()
        try:
            following_ids = set(self.store.list_following_ids(user_id) or [])
        except Exception:
            pass

        liked_restaurants: Counter = Counter()
        try:
            for row in self.store.list_saved_restaurants(user_id) or []:
                _bump(liked_restaurants, row.get("restaurant_name"), 3.0)
        except Exception:
            pass

        liked_recipe_tags: Counter = Counter()
        liked_hashtags: Counter = Counter()
        if self.post_store is not None:
            try:
                for post in self._engagement_posts(user_id):
                    _bump(liked_recipe_tags, post.get("recipe_tag"), 2.0)
                    _bump(liked_restaurants, post.get("restaurant_tag"), 2.0)
                    for tag in post.get("hashtags") or []:
                        _bump(liked_hashtags, tag, 1.0)
                    # Soft cuisine guess from recipe tag text
                    recipe_tag = str(post.get("recipe_tag") or "")
                    for known in list(cuisine_weights.keys()) or []:
                        if known.lower() in recipe_tag.lower():
                            _bump(cuisine_weights, known, 0.5)
            except Exception:
                pass

        # Meal plan filter history
        try:
            plan = self.store.get_meal_plan(user_id)
            if plan and plan.get("filters", {}).get("cuisine"):
                _bump(cuisine_weights, plan["filters"]["cuisine"], 1.5)
        except Exception:
            pass

        top_cuisines = [name for name, _ in cuisine_weights.most_common(5)]
        signals = (
            len(allergies)
            + len(cuisine_weights)
            + len(favorite_ids)
            + len(cooked_ids)
            + len(liked_restaurants)
            + len(liked_recipe_tags)
            + len(following_ids)
        )

        return {
            "user_id": user_id,
            "allergies": allergies,
            "cuisine_weights": dict(cuisine_weights),
            "favorite_recipe_ids": favorite_ids,
            "cooked_recipe_ids": cooked_ids,
            "cooked_names": cooked_names,
            "liked_recipe_tags": liked_recipe_tags,
            "liked_restaurants": liked_restaurants,
            "liked_hashtags": liked_hashtags,
            "following_ids": following_ids,
            "top_cuisines": top_cuisines,
            "signals": signals,
        }

    def _engagement_posts(self, user_id: str, limit: int = 40) -> list[dict]:
        posts: list[dict] = []
        seen: set[str] = set()
        if self.post_store is None:
            return posts
        try:
            for post in self.post_store.list_bookmarks(user_id, limit=min(20, limit)) or []:
                pid = post.get("post_id")
                if pid and pid not in seen:
                    seen.add(pid)
                    posts.append(post)
        except Exception:
            pass
        # Liked posts via likes collection if available
        try:
            likes = getattr(self.post_store, "_likes", None)
            posts_col = getattr(self.post_store, "_posts", None)
            if likes and posts_col:
                liked_ids = [
                    doc["post_id"]
                    for doc in likes().find({"user_id": user_id}).sort("created_at", -1).limit(limit)
                    if doc.get("post_id")
                ]
                if liked_ids:
                    for doc in posts_col().find({"post_id": {"$in": liked_ids}}):
                        pid = doc.get("post_id")
                        if pid and pid not in seen:
                            seen.add(pid)
                            posts.append(self.post_store._serialize(doc, user_id))
        except Exception:
            pass
        return posts[:limit]

    def blocks_allergy(self, recipe: dict, taste: dict) -> bool:
        allergies = taste.get("allergies") or []
        if not allergies:
            return False
        blob_parts = [
            str(recipe.get("name") or ""),
            " ".join(str(x) for x in (recipe.get("ingredients") or [])),
            str(recipe.get("instructions") or ""),
        ]
        for row in recipe.get("measurements") or []:
            if isinstance(row, dict) and row.get("ingredient"):
                blob_parts.append(str(row["ingredient"]))
        blob = " ".join(blob_parts).lower()
        for allergy in allergies:
            token = normalize_token(allergy)
            if not token or len(token) < 2:
                continue
            if token in blob:
                return True
            for ing in recipe.get("ingredients") or []:
                if soft_match_ingredient(allergy, str(ing)):
                    return True
        return False

    def boost_recipe(self, recipe: dict, taste: dict | None, base_score: float | None = None) -> float:
        score = float(base_score if base_score is not None else recipe.get("match_score") or 0)
        if not taste or not taste.get("signals"):
            return score
        cuisine = str(recipe.get("cuisine") or "").strip()
        weights = taste.get("cuisine_weights") or {}
        if cuisine:
            # Exact or soft key match
            bump = float(weights.get(cuisine) or 0)
            if not bump:
                for key, w in weights.items():
                    if key.lower() in cuisine.lower() or cuisine.lower() in key.lower():
                        bump = max(bump, float(w))
            score += bump * 4.0

        rid = str(recipe.get("id") or "")
        if rid and rid in (taste.get("favorite_recipe_ids") or set()):
            score += 12
        if rid and rid in (taste.get("cooked_recipe_ids") or set()):
            score += 8
        name = str(recipe.get("name") or "").strip().lower()
        if name and name in (taste.get("cooked_names") or {}):
            score += 6 + float(taste["cooked_names"][name])

        for tag, w in (taste.get("liked_recipe_tags") or {}).items():
            if tag and tag.lower() in name:
                score += float(w) * 2.0
        return score

    def score_post(self, post: dict, taste: dict | None) -> float:
        score = float(post.get("likes_count") or 0) + 2.0 * float(post.get("comments_count") or 0)
        if not taste or not taste.get("signals"):
            return score
        author = post.get("user_id")
        if author and author in (taste.get("following_ids") or set()):
            score += 25
        recipe_tag = str(post.get("recipe_tag") or "").strip()
        restaurant_tag = str(post.get("restaurant_tag") or "").strip()
        for tag, w in (taste.get("liked_recipe_tags") or {}).items():
            if recipe_tag and tag.lower() in recipe_tag.lower():
                score += float(w) * 6
        for name, w in (taste.get("liked_restaurants") or {}).items():
            if restaurant_tag and name.lower() in restaurant_tag.lower():
                score += float(w) * 8
        for tag in post.get("hashtags") or []:
            score += float((taste.get("liked_hashtags") or {}).get(tag, 0)) * 3
        for cuisine, w in (taste.get("cuisine_weights") or {}).items():
            blob = f"{recipe_tag} {post.get('caption') or ''}".lower()
            if cuisine.lower() in blob:
                score += float(w) * 2
        return score

    def recommend_restaurants(self, taste: dict | None, limit: int = 8) -> list[dict]:
        if not taste:
            return []
        items = []
        for name, weight in (taste.get("liked_restaurants") or Counter()).most_common(limit):
            items.append(
                {
                    "restaurant_name": name,
                    "score": float(weight),
                    "reason": "Based on saved places and posts you liked",
                }
            )
        return items

    def personalize_filters(self, filters: dict | None, taste: dict | None) -> dict:
        out = dict(filters or {})
        if not taste or not taste.get("top_cuisines"):
            return out
        if not out.get("cuisine"):
            out["cuisine"] = taste["top_cuisines"][0]
            out["_cuisine_from_prefs"] = True
        return out

    def rank_recipes(self, recipes: list[dict], taste: dict | None) -> list[dict]:
        if not recipes:
            return []
        kept = []
        for recipe in recipes:
            if taste and self.blocks_allergy(recipe, taste):
                continue
            row = dict(recipe)
            row["pref_score"] = round(self.boost_recipe(row, taste), 1)
            kept.append(row)
        kept.sort(
            key=lambda r: (float(r.get("pref_score") or 0), float(r.get("match_score") or 0)),
            reverse=True,
        )
        return kept

    def summary(self, taste: dict | None) -> dict:
        if not taste:
            return {"active": False, "signals": 0}
        return {
            "active": bool(taste.get("signals")),
            "signals": taste.get("signals") or 0,
            "top_cuisines": taste.get("top_cuisines") or [],
            "allergies": taste.get("allergies") or [],
            "favorite_count": len(taste.get("favorite_recipe_ids") or []),
            "cooked_count": len(taste.get("cooked_recipe_ids") or []),
            "restaurant_affinities": [n for n, _ in (taste.get("liked_restaurants") or Counter()).most_common(5)],
        }
