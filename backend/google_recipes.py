"""Recipe discovery via Google Custom Search API, with web fallback when keys are absent."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import quote_plus

import httpx

from backend.generator import PLACEHOLDER_IMG, match_leftovers, normalize_token

API_URL = "https://www.googleapis.com/customsearch/v1"

TITLE_SUFFIX_RE = re.compile(
    r"\s*[-|–—:]\s*(Allrecipes|Food Network|BBC Good Food|Serious Eats|Tasty|"
    r"Simply Recipes|Bon Appétit|Epicurious|Delish|The Spruce Eats|NYT Cooking|"
    r"Recipe Tin Eats|Jamie Oliver|Recipetin Eats).*",
    re.I,
)

RECIPE_DOMAINS = (
    "allrecipes.com", "foodnetwork.com", "bbcgoodfood.com", "seriouseats.com",
    "tasty.co", "simplyrecipes.com", "recipetineats.com", "delish.com",
    "epicurious.com", "thespruceeats.com", "jamieoliver.com",
)


class GoogleRecipeSearch:
    def __init__(self, api_key: str, cse_id: str) -> None:
        self.api_key = (api_key or "").strip()
        self.cse_id = (cse_id or "").strip()
        self.use_api = bool(self.api_key and self.cse_id)
        self.enabled = True

    def _build_query(
        self,
        parts: list[str],
        dish_mode: bool,
        name_q: str | None,
        cuisine: str | None = None,
    ) -> str:
        cuisine_bit = f" {cuisine.strip()}" if cuisine and cuisine.strip() else ""
        if dish_mode and name_q:
            return f"{name_q}{cuisine_bit} recipe ingredients"
        joined = " ".join(parts[:6])
        return f"{joined}{cuisine_bit} recipe using leftovers"

    def _clean_title(self, title: str) -> str:
        name = TITLE_SUFFIX_RE.sub("", title or "").strip()
        name = re.sub(r"\s+recipe\s*$", "", name, flags=re.I).strip()
        return name or title or "Web recipe"

    def _extract_image(self, item: dict) -> str:
        pagemap = item.get("pagemap") or {}
        for block in pagemap.get("cse_image") or []:
            src = block.get("src")
            if src:
                return src
        for block in pagemap.get("cse_thumbnail") or []:
            src = block.get("src")
            if src:
                return src
        for block in pagemap.get("metatags") or []:
            for key in ("og:image", "twitter:image", "og:image:url"):
                if block.get(key):
                    return block[key]
        return PLACEHOLDER_IMG

    def _score(self, title: str, snippet: str, leftovers: list[str]) -> tuple[float, list[str], list[str]]:
        text = f"{title} {snippet}".lower()
        matched: list[str] = []
        for ing in leftovers:
            tok = normalize_token(ing)
            if not tok:
                continue
            if tok in text or any(part in text for part in tok.split() if len(part) > 2):
                matched.append(ing.strip())
        if not matched and leftovers:
            matched, _missing = match_leftovers(leftovers, self._guess_ingredients(snippet))
        missing = [i for i in leftovers if i not in matched]
        base = 55.0
        if matched:
            base += min(35.0, len(matched) * 12.0)
        if "recipe" in text:
            base += 5.0
        return min(92.0, base), matched, missing

    def _guess_ingredients(self, snippet: str) -> list[str]:
        words = re.findall(r"[a-z]{3,}", snippet.lower())
        stop = {
            "the", "and", "with", "this", "that", "from", "your", "for", "are", "was",
            "you", "can", "will", "has", "have", "into", "about", "recipe", "minutes",
        }
        return [w for w in words if w not in stop][:12]

    def _to_recipe(
        self,
        *,
        link: str,
        title: str,
        snippet: str,
        leftovers: list[str],
        rank: int,
        image: str | None = None,
        via_api: bool,
    ) -> dict | None:
        if not link:
            return None
        name = self._clean_title(title)
        snippet = (snippet or "").strip()
        score, matched, missing = self._score(name, snippet, leftovers)
        steps = [s.strip() for s in re.split(r"(?<=[.!?])\s+", snippet) if s.strip()]
        if not steps:
            steps = [snippet or f"Open the full recipe for {name}."]
        ingredients = matched + self._guess_ingredients(snippet)
        ingredients = list(dict.fromkeys(i.lower() for i in ingredients if i))[:10]
        rid = hashlib.sha1(link.encode()).hexdigest()[:12]
        return {
            "id": f"google-{rid}",
            "name": name,
            "cuisine": "Web",
            "time_min": max(15, min(60, 20 + rank * 5)),
            "ingredients": ingredients or [normalize_token(x) for x in leftovers[:4]],
            "instructions": snippet,
            "steps": steps[:6],
            "image": image or PLACEHOLDER_IMG,
            "calories": None,
            "video_url": link,
            "source_url": link,
            "diet": "",
            "halal": "",
            "goal": "",
            "servings": 2,
            "measurements": [{"ingredient": i, "amount": "see recipe"} for i in ingredients[:8]],
            "match_score": round(score, 1),
            "semantic_score": round(score, 1),
            "matched_ingredients": matched or leftovers[: min(3, len(leftovers))],
            "missing_ingredients": missing,
            "uses_count": max(1, len(matched)),
            "generated": False,
            "search_mode": "google",
            "source_model": "google" if via_api else "google-web",
        }

    def _search_api(self, query: str, top_k: int) -> list[dict]:
        params = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": query,
            "num": min(10, max(top_k, 5)),
            "safe": "active",
        }
        try:
            with httpx.Client(timeout=12.0) as client:
                resp = client.get(API_URL, params=params)
            if resp.status_code >= 400:
                return []
            items = (resp.json() or {}).get("items") or []
        except Exception:  # noqa: BLE001
            return []

        out: list[dict] = []
        for i, item in enumerate(items):
            recipe = self._to_recipe(
                link=item.get("link") or "",
                title=item.get("title") or "Recipe",
                snippet=(item.get("snippet") or "").strip(),
                leftovers=[],
                rank=i,
                image=self._extract_image(item),
                via_api=True,
            )
            if recipe:
                out.append(recipe)
            if len(out) >= top_k:
                break
        return out

    def _search_web_fallback(self, query: str, top_k: int) -> list[dict]:
        """Search the open web for recipe pages (no Google API key required)."""
        recipe_query = f"{query} recipe"
        try:
            from ddgs import DDGS

            rows = DDGS().text(recipe_query, max_results=min(12, max(top_k * 2, 6)))
        except ImportError:
            from duckduckgo_search import DDGS

            rows = DDGS().text(recipe_query, max_results=min(12, max(top_k * 2, 6)))
        except Exception:  # noqa: BLE001
            rows = []
        if not rows:
            rows = self._search_google_html_fallback(query, top_k)

        out: list[dict] = []
        for i, row in enumerate(rows or []):
            link = row.get("href") or row.get("link") or ""
            title = row.get("title") or "Recipe"
            snippet = row.get("body") or row.get("snippet") or ""
            if not link or "google.com/search" in link:
                continue
            lower_link = link.lower()
            if not any(domain in lower_link for domain in RECIPE_DOMAINS):
                if "recipe" not in f"{title} {snippet}".lower():
                    continue
            recipe = self._to_recipe(
                link=link,
                title=title,
                snippet=snippet,
                leftovers=[],
                rank=i,
                via_api=False,
            )
            if recipe:
                out.append(recipe)
            if len(out) >= top_k:
                break
        if not out and rows:
            for i, row in enumerate(rows[:top_k]):
                link = row.get("href") or row.get("link") or ""
                if not link:
                    continue
                recipe = self._to_recipe(
                    link=link,
                    title=row.get("title") or "Recipe",
                    snippet=row.get("body") or row.get("snippet") or "",
                    leftovers=[],
                    rank=i,
                    via_api=False,
                )
                if recipe:
                    out.append(recipe)
        return out

    def _search_google_html_fallback(self, query: str, top_k: int) -> list[dict]:
        """Last-resort: return direct Google search links as recipe cards."""
        q = quote_plus(f"{query} recipe")
        link = f"https://www.google.com/search?q={q}"
        return [
            {
                "href": link,
                "title": f"Google recipes: {query}",
                "body": f"Browse recipe results on Google for {query}.",
            }
        ][:top_k]

    def search(
        self,
        leftovers: list[str],
        *,
        dish_mode: bool = False,
        name_q: str | None = None,
        top_k: int = 4,
        cuisine: str | None = None,
    ) -> list[dict]:
        if not self.enabled or top_k < 1:
            return []
        query = self._build_query(leftovers, dish_mode, name_q, cuisine)

        if self.use_api:
            raw = self._search_api(query, top_k)
        else:
            raw = self._search_web_fallback(query, top_k)

        out: list[dict] = []
        for i, recipe in enumerate(raw):
            title = recipe.get("name") or ""
            snippet = recipe.get("instructions") or ""
            score, matched, missing = self._score(title, snippet, leftovers)
            recipe["match_score"] = round(score, 1)
            recipe["semantic_score"] = round(score, 1)
            recipe["matched_ingredients"] = matched or leftovers[: min(3, len(leftovers))]
            recipe["missing_ingredients"] = missing
            recipe["uses_count"] = max(1, len(matched))
            if cuisine and str(recipe.get("cuisine", "")).lower() in {"", "web"}:
                recipe["cuisine"] = cuisine
            out.append(recipe)
            if len(out) >= top_k:
                break
        return out

    @staticmethod
    def youtube_fallback(name: str) -> str:
        return f"https://www.youtube.com/results?search_query={quote_plus(name + ' recipe')}"
