"""FastAPI app: leftover ingredients → HF-ranked recipes."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend.db import close_db, get_db
from backend.filters import enrich_recipe, passes_search_filters
from backend.generator import RecipeGenerator, attach_substitutions
from backend.google_recipes import GoogleRecipeSearch
from backend.matcher import RecipeMatcher, dish_query_text, looks_like_dish_name
from backend.meal_plan import build_plan, swap_day
from backend.grocery import build_grocery_list
from backend.places import PlacesService
from backend.preferences import PreferenceEngine
from backend.auth import validate_password, validate_username
from backend.emotes import list_emojis, list_sticker_packs
from backend.messaging import MessageStore
from backend.notifications import NotificationStore
from backend.oauth import OAuthError, oauth_providers_status, verify_oauth_credential
from backend.posts import PostStore, parse_hashtags
from backend.profiles import save_avatar
from backend.stories import StoryStore
from backend.store import UserStore
from backend.surplus import SurplusStore
from backend.vision import FoodScanner
from backend.barcode import lookup_barcode

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

generator: RecipeGenerator | None = None
matcher: RecipeMatcher | None = None
google_search: GoogleRecipeSearch | None = None
store: UserStore | None = None
post_store: PostStore | None = None
notification_store: NotificationStore | None = None
message_store: MessageStore | None = None
story_store: StoryStore | None = None
surplus_store: SurplusStore | None = None
places_service: PlacesService | None = None
food_scanner: FoodScanner | None = None
mongo_ok = False
recipe_model = "flax-community/t5-recipe-generation"
FAST_MATCH_TIMEOUT = float(os.getenv("FAST_MATCH_TIMEOUT", "22"))
T5_MATCH_TIMEOUT = float(os.getenv("T5_MATCH_TIMEOUT", "25"))


def _preference_engine() -> PreferenceEngine:
    return PreferenceEngine(store=store if mongo_ok else None, post_store=post_store if mongo_ok else None)


def _user_taste(user_id: str | None) -> dict | None:
    if not user_id or not mongo_ok:
        return None
    return _preference_engine().load(user_id)


def _merge_recipe_lists(
    by_name: list[dict],
    catalog: list[dict],
    generated: list[dict],
    from_google: list[dict],
    top_k: int,
) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()

    def _push(recipes: list[dict]) -> None:
        for recipe in recipes:
            key = str(recipe.get("name", "")).strip().lower()
            if not key or key in seen:
                continue
            if not recipe.get("matched_ingredients") and recipe.get("search_mode") not in {
                "dish_name",
                "google",
            }:
                continue
            seen.add(key)
            merged.append(recipe)
            if len(merged) >= top_k:
                return

    _push(sorted(by_name, key=lambda r: r.get("match_score", 0), reverse=True))

    google_sorted = sorted(from_google, key=lambda r: r.get("match_score", 0), reverse=True)
    local_sorted = sorted(
        catalog + generated,
        key=lambda r: (r.get("uses_count", 0), r.get("match_score", 0)),
        reverse=True,
    )
    reserve_google = 1 if google_sorted and len(merged) < top_k else 0
    local_budget = max(0, top_k - len(merged) - reserve_google)
    if local_budget:
        _push(local_sorted[:local_budget])
    if reserve_google:
        _push(google_sorted[:1])
    if len(merged) < top_k:
        _push(local_sorted)
    if len(merged) < top_k:
        _push(google_sorted)
    return merged


def _run_parallel_tasks(tasks: dict, timeout: float) -> tuple[dict[str, list[dict]], list[str]]:
    results: dict[str, list[dict]] = {}
    errors: list[str] = []
    if not tasks:
        return results, errors
    with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
        futures = {key: pool.submit(fn) for key, fn in tasks.items()}
        for key, fut in futures.items():
            try:
                results[key] = fut.result(timeout=timeout)
            except FuturesTimeoutError:
                errors.append(f"{key} timed out")
                fut.cancel()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{key}: {exc}")
    return results, errors


def _catalog_is_enough(merged: list[dict], top_k: int) -> bool:
    if len(merged) >= top_k:
        return True
    if len(merged) >= 2:
        best = max(float(r.get("match_score", 0)) for r in merged)
        if best >= 65:
            return True
    return False


@asynccontextmanager
async def lifespan(_: FastAPI):
    global generator, matcher, google_search, store, post_store, notification_store, message_store, story_store, surplus_store, places_service, food_scanner, mongo_ok, recipe_model
    token = os.getenv("HF_TOKEN", "").strip()
    recipe_model = os.getenv(
        "HF_RECIPE_MODEL", "flax-community/t5-recipe-generation"
    ).strip()
    embed_model = os.getenv(
        "HF_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    ).strip()
    if not token:
        # Don't crash the whole site in production — AI features degrade until HF_TOKEN is set.
        print("WARNING: HF_TOKEN missing. Recipe AI / food scan will be limited until it is set.")
        generator = None
        matcher = RecipeMatcher(token="", model=embed_model)
        food_scanner = FoodScanner(token="")
    else:
        generator = RecipeGenerator(token=token, model=recipe_model)
        # Catalog matcher kept as fallback if T5 generation fails
        matcher = RecipeMatcher(token=token, model=embed_model)
        food_scanner = FoodScanner(token=token)
    google_search = GoogleRecipeSearch(
        api_key=os.getenv("GOOGLE_API_KEY", "").strip(),
        cse_id=os.getenv("GOOGLE_CSE_ID", "").strip(),
    )
    places_service = PlacesService()
    store = UserStore()
    post_store = PostStore()
    notification_store = NotificationStore()
    message_store = MessageStore()
    story_store = StoryStore()
    surplus_store = SurplusStore()
    try:
        get_db()
        mongo_ok = True
        admin_user = os.getenv("ADMIN_USERNAME", "admin").strip()
        admin_pass = os.getenv("ADMIN_PASSWORD", "petugram123").strip()
        if admin_user and admin_pass:
            created = store.ensure_admin(admin_user, admin_pass)
            print(f"Admin account ready: {created['username']} (role: {created['role']})")
    except Exception as exc:  # noqa: BLE001
        mongo_ok = False
        print(f"MongoDB unavailable ({exc}). Start MongoDB for pantry & gamification features.")
    print(f"Recipe model: {recipe_model}")
    yield
    close_db()


app = FastAPI(
    title="Petugram — Food Waste Recipe Matcher",
    description=(
        "SDG 12: generate leftover recipes with flax-community/t5-recipe-generation."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_mongo():
    if not mongo_ok or store is None:
        raise HTTPException(
            503,
            "MongoDB is not connected. Install MongoDB and set MONGODB_URI in .env "
            "(default: mongodb://localhost:27017/petugram).",
        )


class MatchRequest(BaseModel):
    ingredients: list[str] = Field(..., min_length=1, description="Leftover ingredients")
    top_k: int = Field(5, ge=1, le=10)
    diet: str | None = Field(None, description="vegan | non-vegan")
    halal: str | None = Field(None, description="halal | non-halal")
    goal: str | None = Field(None, description="weight_gain | weight_loss")
    cuisine: str | None = Field(None, description="Filter by cuisine e.g. Italian")
    max_time_min: int | None = Field(None, ge=5, le=240, description="Max cooking time in minutes")
    difficulty: str | None = Field(None, description="easy | medium | hard")
    max_calories: int | None = Field(None, ge=50, le=2500, description="Max calories per serving")
    user_id: str | None = None

    @field_validator("diet", "halal", "goal", "cuisine", "difficulty", mode="before")
    @classmethod
    def _empty_str_to_none(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value


class CookRequest(BaseModel):
    user_id: str
    recipe: dict


class PantryItemRequest(BaseModel):
    user_id: str
    ingredient: str
    expiry_date: str
    qty: str = "1"


class PantryScanConfirmRequest(BaseModel):
    user_id: str
    ingredients: list[str] = Field(..., min_length=1)
    expiry_date: str
    qty: str = "1"


class BarcodeScanRequest(BaseModel):
    user_id: str
    barcode: str = Field(..., min_length=8, max_length=32)


class SurplusOfferRequest(BaseModel):
    user_id: str
    ingredient: str = Field(..., min_length=2, max_length=80)
    qty: str = "1"
    expiry_date: str | None = None
    note: str = Field("", max_length=400)
    area: str = Field("", max_length=80)
    lat: float | None = None
    lng: float | None = None
    pantry_item_id: str | None = None
    title: str | None = Field(None, max_length=100)


class SurplusClaimRequest(BaseModel):
    user_id: str


class ShoppingRequest(BaseModel):
    missing: list[str] = Field(default_factory=list)
    plan: dict | None = None
    have: list[str] = Field(default_factory=list)
    user_id: str | None = None


class GroceryListRequest(BaseModel):
    missing: list[str] = Field(default_factory=list)
    plan: dict | None = None
    have: list[str] = Field(default_factory=list)
    user_id: str | None = None


class MealPlanRequest(BaseModel):
    days: int = Field(5, ge=3, le=7)
    ingredients: list[str] = Field(default_factory=list)
    user_id: str | None = None
    diet: str | None = None
    halal: str | None = None
    goal: str | None = None
    cuisine: str | None = None
    max_time_min: int | None = Field(None, ge=5, le=240)
    difficulty: str | None = None
    max_calories: int | None = Field(None, ge=50, le=2500)

    @field_validator("diet", "halal", "goal", "cuisine", "difficulty", mode="before")
    @classmethod
    def _empty_str_to_none(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value


class MealPlanSwapRequest(BaseModel):
    day: int = Field(..., ge=1, le=7)
    slot: str = Field("dinner", description="breakfast | lunch | dinner | snack")
    ingredients: list[str] = Field(default_factory=list)
    exclude_ids: list[str] = Field(default_factory=list)
    user_id: str | None = None
    diet: str | None = None
    halal: str | None = None
    goal: str | None = None
    cuisine: str | None = None
    max_time_min: int | None = Field(None, ge=5, le=240)
    difficulty: str | None = None
    max_calories: int | None = Field(None, ge=50, le=2500)

    @field_validator("diet", "halal", "goal", "cuisine", "difficulty", mode="before")
    @classmethod
    def _empty_str_to_none(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("slot", mode="before")
    @classmethod
    def _normalize_slot(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return "dinner"
        slot = str(value).strip().lower()
        if slot not in {"breakfast", "lunch", "dinner", "snack"}:
            return "dinner"
        return slot


class MealPlanSaveRequest(BaseModel):
    user_id: str
    plan: dict


class ProfileRequest(BaseModel):
    user_id: str
    allergies: list[str] | None = None
    cuisines: list[str] | None = None
    bio: str | None = Field(None, max_length=500)
    display_name: str | None = Field(None, max_length=80)
    country: str | None = Field(None, max_length=16)
    is_public: bool | None = None
    is_active: bool | None = None


class SavedRestaurantRequest(BaseModel):
    user_id: str
    restaurant_name: str = Field(..., min_length=1, max_length=120)
    area: str = Field("", max_length=80)
    place_id: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    rating: float | None = None
    price_level: int | None = None
    cuisine: str | None = None
    website: str | None = None
    maps_url: str | None = None
    directions_url: str | None = None
    halal: bool | None = None
    vegetarian: bool | None = None
    delivery: bool | None = None


class FollowRequest(BaseModel):
    user_id: str


class DirectChatRequest(BaseModel):
    user_id: str
    other_user_id: str


class MessageSendRequest(BaseModel):
    user_id: str
    text: str = Field(..., min_length=1, max_length=2000)


class MessageReactionRequest(BaseModel):
    user_id: str
    emoji: str = Field(..., min_length=1, max_length=16)


class FavoriteRequest(BaseModel):
    user_id: str
    recipe: dict


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=24)
    password: str = Field(..., min_length=6, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=24)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def _username_ok(cls, value: str) -> str:
        return validate_username(value)

    @field_validator("password")
    @classmethod
    def _password_ok(cls, value: str) -> str:
        return validate_password(value, strict=True)


class OAuthLoginRequest(BaseModel):
    provider: str = Field(..., pattern="^(google|facebook)$")
    credential: str = Field(..., min_length=10, max_length=8000)


class DeleteAccountRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    password: str | None = Field(None, min_length=6, max_length=128)
    confirm_text: str | None = Field(None, max_length=80)


class RoleRequest(BaseModel):
    admin_user_id: str
    target_user_id: str
    role: str = Field(..., pattern="^(user|admin)$")


def require_admin(user_id: str):
    require_mongo()
    assert store is not None
    if not store.is_admin(user_id):
        raise HTTPException(403, "Admin access required")


@app.get("/api/cuisines")
def list_cuisines():
    if matcher is None:
        return {"cuisines": []}
    extra = [
        "American",
        "Asian",
        "Breakfast",
        "Chinese",
        "Coastal",
        "French",
        "Healthy",
        "Home-style",
        "Indian",
        "Italian",
        "Japanese",
        "Mediterranean",
        "Mexican",
        "Middle Eastern",
        "Modern",
        "Pakistani",
        "Spanish",
        "Thai",
        "Turkish",
    ]
    from_catalog = {str(r.get("cuisine", "")).strip() for r in matcher.recipes if r.get("cuisine")}
    seen = sorted(from_catalog | set(extra), key=str.lower)
    return {"cuisines": seen}


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "recipe_model": recipe_model or os.getenv("HF_RECIPE_MODEL"),
        "embed_model": os.getenv("HF_MODEL"),
        "recipes": len(matcher.recipes) if matcher else 0,
        "mongodb": mongo_ok,
        "google_search": bool(google_search and google_search.use_api),
        "web_recipe_search": bool(google_search and google_search.enabled),
        "posts_api": post_store is not None,
        "vision_hf": bool(os.getenv("HF_TOKEN", "").strip()),
        "vision_gemini": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "vision_openai": bool(os.getenv("OPENAI_API_KEY", "").strip()),
    }


@app.post("/api/match")
def match_recipes(body: MatchRequest):
    if generator is None:
        raise HTTPException(503, "Model not ready")

    cleaned = [i.strip() for i in body.ingredients if i and i.strip()]
    if not cleaned:
        raise HTTPException(400, "Provide at least one ingredient")

    allowed_diet = {None, "vegan", "non-vegan"}
    allowed_halal = {None, "halal", "non-halal"}
    allowed_goal = {None, "weight_gain", "weight_loss"}
    allowed_difficulty = {None, "easy", "medium", "hard"}
    if body.diet not in allowed_diet:
        raise HTTPException(400, "diet must be vegan or non-vegan")
    if body.halal not in allowed_halal:
        raise HTTPException(400, "halal must be halal or non-halal")
    if body.goal not in allowed_goal:
        raise HTTPException(400, "goal must be weight_gain or weight_loss")
    if body.difficulty not in allowed_difficulty:
        raise HTTPException(400, "difficulty must be easy, medium, or hard")

    filter_kwargs = {
        "cuisine": body.cuisine,
        "max_time_min": body.max_time_min,
        "difficulty": body.difficulty,
        "diet": body.diet,
        "max_calories": body.max_calories,
        "halal": body.halal,
        "goal": body.goal,
    }
    taste = _user_taste(body.user_id)
    engine = _preference_engine()
    # Soft-default cuisine from learned prefs when user didn't pick one
    if taste and not filter_kwargs.get("cuisine") and taste.get("top_cuisines"):
        # Don't hard-filter; preference re-rank handles boost. Keep filters open.
        pass
    has_filters = any(v is not None for v in filter_kwargs.values())

    source = "hybrid"
    errors: list[str] = []
    catalog: list[dict] = []
    generated: list[dict] = []
    by_name: list[dict] = []
    from_google: list[dict] = []
    dish_mode = looks_like_dish_name(cleaned)
    name_q = dish_query_text(cleaned)
    top_k = body.top_k
    fetch_k = 20 if has_filters else min(max(top_k * 4, 12), 20)
    t5_k = min(top_k + 2, 5) if has_filters else min(top_k, 3)

    def _run_dish_name() -> list[dict]:
        if matcher is None or not name_q:
            return []
        raw_names = matcher.search_by_name(name_q, top_k=fetch_k)
        if dish_mode:
            for part in cleaned:
                part = part.strip()
                if " " in part and part.lower() != name_q.lower():
                    raw_names.extend(matcher.search_by_name(part, top_k=2))
        hits = (
            raw_names
            if dish_mode
            else [r for r in raw_names if float(r.get("match_score", 0)) >= 90]
        )
        if dish_mode and not hits:
            hits = matcher.fetch_mealdb(name_q, top_k=min(5, fetch_k))
        return hits

    def _run_catalog() -> list[dict]:
        if matcher is None or dish_mode:
            return []
        return matcher.match(cleaned, top_k=fetch_k)

    def _run_t5(limit: int) -> list[dict]:
        if dish_mode or generator is None or limit <= 0:
            return []
        return generator.generate(cleaned, top_k=limit)

    def _run_google() -> list[dict]:
        if google_search is None:
            return []
        return google_search.search(
            cleaned,
            dish_mode=dish_mode,
            name_q=name_q,
            top_k=min(8, fetch_k),
            cuisine=body.cuisine,
        )

    fast_tasks: dict = {}
    if matcher and name_q:
        fast_tasks["name"] = _run_dish_name
    if not dish_mode:
        fast_tasks["catalog"] = _run_catalog
    if google_search:
        fast_tasks["google"] = _run_google

    fast_out, errors = _run_parallel_tasks(fast_tasks, FAST_MATCH_TIMEOUT)
    by_name = fast_out.get("name", [])
    catalog = fast_out.get("catalog", [])
    from_google = fast_out.get("google", [])
    generated: list[dict] = []

    merged = _merge_recipe_lists(by_name, catalog, generated, from_google, fetch_k)
    skip_t5 = dish_mode or _catalog_is_enough(merged, top_k)

    if not skip_t5 and not dish_mode:
        need = fetch_k - len(merged)
        t5_limit = min(max(need, top_k), t5_k + 2)
        t5_tasks = {"t5": lambda: _run_t5(t5_limit)}
        t5_out, t5_errors = _run_parallel_tasks(t5_tasks, T5_MATCH_TIMEOUT)
        errors.extend(t5_errors)
        generated = t5_out.get("t5", [])
        merged = _merge_recipe_lists(by_name, catalog, generated, from_google, fetch_k)

    gen_error = "; ".join(errors) if errors else None

    pool = merged
    enriched = [enrich_recipe(r) for r in pool if passes_search_filters(r, **filter_kwargs)]
    if taste:
        enriched = engine.rank_recipes(enriched, taste)
    results = enriched[:top_k]
    if by_name and (catalog or generated or from_google):
        source = "dish+leftovers"
    elif by_name:
        source = "dish_name"
    elif from_google and not catalog and not generated:
        source = "google"
    elif from_google and (catalog or generated):
        source = "hybrid+google"
    elif catalog and generated:
        source = "hybrid"
    elif generated:
        source = "t5-recipe-generation"
    elif catalog:
        source = "catalog"
    elif from_google:
        source = "google"
    else:
        source = "none"

    if not results and pool:
        raise HTTPException(
            404,
            "No recipes match your filters. Try relaxing cuisine, time, difficulty, or calorie limits.",
        )
    if not results and gen_error:
        raise HTTPException(502, f"Recipe matching failed: {gen_error}")
    if not results:
        raise HTTPException(
            404,
            "No recipes found. Try a dish name (e.g. Shakshuka) or leftovers (tomato, egg, onion).",
        )

    ranked = attach_substitutions(results, cleaned)

    shopping = None
    if ranked and mongo_ok and store:
        missing = ranked[0].get("missing_ingredients", [])
        if missing:
            shopping = store.shopping_list(missing[:8])

    return {
        "query": cleaned,
        "filters": {
            "diet": body.diet,
            "halal": body.halal,
            "goal": body.goal,
            "cuisine": body.cuisine,
            "max_time_min": body.max_time_min,
            "difficulty": body.difficulty,
            "max_calories": body.max_calories,
        },
        "preferences": engine.summary(taste) if taste else {"active": False},
        "count": len(ranked),
        "model": recipe_model,
        "source": source,
        "shopping_suggestion": shopping,
        "recipes": ranked,
        "sdg": "SDG 12 — Responsible Consumption and Production",
    }


@app.get("/api/dashboard")
def dashboard(user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    return store.monthly_report(user_id)


@app.get("/api/impact/locations")
def impact_locations():
    from backend.impact import list_locations

    return {"locations": list_locations()}


@app.post("/api/cook")
def log_cook(body: CookRequest):
    require_mongo()
    assert store is not None
    recipe = body.recipe
    result = store.log_cook(body.user_id, recipe)
    return {"ok": True, **result}


@app.get("/api/pantry")
def list_pantry(user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    return {"items": store.list_pantry(user_id)}


@app.post("/api/pantry")
def add_pantry(body: PantryItemRequest):
    require_mongo()
    assert store is not None
    item = store.add_pantry_item(body.user_id, body.ingredient, body.expiry_date, body.qty)
    return {"ok": True, "item": item}


@app.post("/api/pantry/scan")
async def scan_pantry_image(
    user_id: str = Form(...),
    file: UploadFile = File(...),
    mode: str = Form("photo"),
):
    """AI Food Scanner: photo ingredients or receipt line items (does not auto-add)."""
    require_mongo()
    assert store is not None
    assert food_scanner is not None
    if not store.get_account(user_id):
        raise HTTPException(401, "Log in to scan food into your fridge")
    content_type = (file.content_type or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(400, "Please upload an image (JPG, PNG, or WebP)")
    raw = await file.read()
    scan_mode = (mode or "photo").strip().lower()
    if scan_mode not in {"photo", "receipt"}:
        scan_mode = "photo"
    try:
        result = food_scanner.scan(raw, filename=file.filename or "", mode=scan_mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Food scan failed: {exc}") from exc
    if not result.get("ingredients"):
        hint = (
            "Try a clearer receipt photo with grocery lines visible."
            if scan_mode == "receipt"
            else "Try a clearer photo of produce, leftovers, or grocery items — or add them manually below."
        )
        return {
            **result,
            "is_food": False,
            "message": "No groceries detected in that image.",
            "hint": hint,
        }
    label = "receipt item" if scan_mode == "receipt" else "ingredient"
    return {
        **result,
        "is_food": True,
        "message": f"Found {result['count']} {label}(s). Confirm to add them.",
    }


@app.post("/api/pantry/scan/barcode")
def scan_pantry_barcode(body: BarcodeScanRequest):
    require_mongo()
    assert store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to scan barcodes")
    try:
        return lookup_barcode(body.barcode)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Barcode lookup failed: {exc}") from exc


@app.post("/api/pantry/scan/confirm")
def confirm_pantry_scan(body: PantryScanConfirmRequest):
    require_mongo()
    assert store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to add scanned items")
    added = []
    for name in body.ingredients:
        clean = (name or "").strip()
        if not clean:
            continue
        item = store.add_pantry_item(body.user_id, clean, body.expiry_date, body.qty)
        added.append(item)
    if not added:
        raise HTTPException(400, "No ingredients to add")
    return {"ok": True, "added": added, "count": len(added)}


@app.delete("/api/pantry/{item_id}")
def remove_pantry(item_id: str, user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    if not store.delete_pantry_item(user_id, item_id):
        raise HTTPException(404, "Pantry item not found")
    return {"ok": True}


@app.get("/api/surplus")
def list_surplus(
    viewer_id: str | None = Query(None),
    lat: float | None = Query(None),
    lng: float | None = Query(None),
    radius_km: float = Query(25, ge=1, le=100),
    mine: bool = Query(False),
    limit: int = Query(40, ge=1, le=80),
):
    require_mongo()
    assert surplus_store is not None
    if mine and not viewer_id:
        raise HTTPException(401, "Log in to see your offers")
    offers = surplus_store.list_offers(
        viewer_id=viewer_id,
        lat=lat,
        lng=lng,
        radius_km=radius_km,
        mine=mine,
        limit=limit,
    )
    return {"offers": offers, "count": len(offers)}


@app.post("/api/surplus")
def create_surplus(body: SurplusOfferRequest):
    require_mongo()
    assert store is not None
    assert surplus_store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to share surplus food")
    try:
        offer = surplus_store.create_offer(
            body.user_id,
            ingredient=body.ingredient,
            qty=body.qty,
            expiry_date=body.expiry_date,
            note=body.note,
            area=body.area,
            lat=body.lat,
            lng=body.lng,
            pantry_item_id=body.pantry_item_id,
            title=body.title,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "offer": offer}


@app.post("/api/surplus/{offer_id}/claim")
def claim_surplus(offer_id: str, body: SurplusClaimRequest):
    require_mongo()
    assert store is not None
    assert surplus_store is not None
    assert message_store is not None
    assert notification_store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to claim surplus food")
    try:
        offer = surplus_store.claim_offer(offer_id, body.user_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    owner_id = offer.get("user_id")
    conversation_id = None
    if owner_id:
        try:
            conv = message_store.get_or_create_direct(body.user_id, owner_id)
            conversation_id = conv.get("conversation_id")
            preview = f"I'd like to claim your surplus: {offer.get('title') or offer.get('ingredient')}"
            message_store.send_message(conversation_id, body.user_id, preview)
        except Exception:
            conversation_id = None
        try:
            notification_store.create(
                owner_id,
                body.user_id,
                "surplus_claim",
                preview=f"claimed {offer.get('title') or offer.get('ingredient')}",
            )
        except Exception:
            pass
    return {"ok": True, "offer": offer, "conversation_id": conversation_id}


@app.delete("/api/surplus/{offer_id}")
def close_surplus(offer_id: str, user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    assert surplus_store is not None
    if not store.get_account(user_id):
        raise HTTPException(401, "Log in to close offers")
    try:
        surplus_store.close_offer(offer_id, user_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@app.get("/api/expiry-alerts")
def expiry_alerts(user_id: str = Query(..., min_length=1), days: int = Query(3, ge=0, le=14)):
    require_mongo()
    assert store is not None
    alerts = store.expiry_alerts(user_id, days=days)
    return {"alerts": alerts, "count": len(alerts)}


@app.get("/api/fridge/suggestions")
def fridge_suggestions(user_id: str = Query(..., min_length=1), days: int = Query(3, ge=0, le=14)):
    """Recipe ideas using fridge items that expire soon."""
    require_mongo()
    assert store is not None
    from datetime import date, timedelta

    alerts = store.expiry_alerts(user_id, days=days)
    ingredients = list(dict.fromkeys(a["ingredient"] for a in alerts))
    if not ingredients:
        week_cutoff = (date.today() + timedelta(days=7)).isoformat()
        for item in store.list_pantry(user_id):
            if item.get("expiry_date", "") <= week_cutoff:
                ingredients.append(item["ingredient"])
        ingredients = list(dict.fromkeys(ingredients))[:8]
    if not ingredients:
        return {"ingredients": [], "expiring": alerts, "recipes": []}

    recipes: list[dict] = []
    if matcher is not None:
        recipes = matcher.match(ingredients, top_k=4)
    if google_search is not None and len(recipes) < 3:
        extra = google_search.search(ingredients, top_k=4 - len(recipes))
        seen = {str(r.get("name", "")).lower() for r in recipes}
        for recipe in extra:
            key = str(recipe.get("name", "")).lower()
            if key and key not in seen:
                recipes.append(recipe)
                seen.add(key)
            if len(recipes) >= 4:
                break

    enriched = [enrich_recipe(r) for r in recipes[:4]]
    return {"ingredients": ingredients, "expiring": alerts, "recipes": enriched}


def _meal_plan_ingredients(user_id: str | None, body_ingredients: list[str]) -> list[str]:
    cleaned = [i.strip() for i in (body_ingredients or []) if i and str(i).strip()]
    if cleaned:
        return list(dict.fromkeys(cleaned))
    if not user_id or not mongo_ok or store is None:
        return []
    from datetime import date, timedelta

    alerts = store.expiry_alerts(user_id, days=3)
    ingredients = list(dict.fromkeys(a["ingredient"] for a in alerts))
    if not ingredients:
        week_cutoff = (date.today() + timedelta(days=7)).isoformat()
        for item in store.list_pantry(user_id):
            if item.get("expiry_date", "") <= week_cutoff:
                ingredients.append(item["ingredient"])
        ingredients = list(dict.fromkeys(ingredients))
    if not ingredients:
        ingredients = list(
            dict.fromkeys(item["ingredient"] for item in store.list_pantry(user_id) if item.get("ingredient"))
        )
    return ingredients[:16]


def _meal_plan_filters(body) -> dict:
    return {
        "diet": body.diet,
        "halal": body.halal,
        "goal": body.goal,
        "cuisine": body.cuisine,
        "max_time_min": body.max_time_min,
        "difficulty": body.difficulty,
        "max_calories": body.max_calories,
    }


@app.post("/api/meal-plan")
def create_meal_plan(body: MealPlanRequest):
    if matcher is None:
        raise HTTPException(503, "Recipe matcher not ready")
    ingredients = _meal_plan_ingredients(body.user_id, body.ingredients)
    if not ingredients:
        raise HTTPException(
            400,
            "Add ingredients or sign in with fridge items to generate a meal plan.",
        )
    plan = build_plan(
        ingredients,
        body.days,
        _meal_plan_filters(body),
        matcher,
        google_search=google_search,
        taste=_user_taste(body.user_id),
    )
    if not plan.get("meals_filled") and not any(
        (m.get("recipe") for d in plan.get("days") or [] for m in (d.get("meals") or []))
    ):
        raise HTTPException(404, "Could not build a meal plan. Try different ingredients or filters.")
    grocery = build_grocery_list(plan=plan, have=ingredients)
    plan["grocery"] = grocery
    return plan


@app.post("/api/meal-plan/swap")
def swap_meal_plan_day(body: MealPlanSwapRequest):
    if matcher is None:
        raise HTTPException(503, "Recipe matcher not ready")
    ingredients = _meal_plan_ingredients(body.user_id, body.ingredients)
    if not ingredients:
        raise HTTPException(400, "Add ingredients or load from fridge to swap a meal.")
    day = swap_day(
        ingredients,
        body.day,
        _meal_plan_filters(body),
        matcher,
        exclude_ids=body.exclude_ids,
        google_search=google_search,
        slot=body.slot or "dinner",
        taste=_user_taste(body.user_id),
    )
    if not (day.get("meal") or {}).get("recipe"):
        raise HTTPException(404, "No alternate recipe found. Try relaxing filters.")
    return day


@app.get("/api/meal-plan/saved")
def get_saved_meal_plan(user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    plan = store.get_meal_plan(user_id)
    if not plan:
        return {"plan": None}
    return {"plan": plan}


@app.put("/api/meal-plan/saved")
def put_saved_meal_plan(body: MealPlanSaveRequest):
    require_mongo()
    assert store is not None
    saved = store.save_meal_plan(body.user_id, body.plan)
    return {"ok": True, "plan": saved}


@app.delete("/api/meal-plan/saved")
def delete_saved_meal_plan(user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    if not store.get_account(user_id):
        raise HTTPException(401, "Log in to delete meal plans")
    deleted = store.delete_meal_plan(user_id)
    return {"ok": True, "deleted": deleted}


@app.post("/api/grocery-list")
def create_grocery_list(body: GroceryListRequest):
    have = [i.strip() for i in (body.have or []) if i and str(i).strip()]
    if body.user_id and mongo_ok and store is not None and not have:
        have = [item["ingredient"] for item in store.list_pantry(body.user_id) if item.get("ingredient")]
    if not body.plan and not body.missing:
        raise HTTPException(400, "Provide a meal plan or missing ingredients.")
    grocery = build_grocery_list(plan=body.plan, missing=body.missing, have=have)
    return grocery


@app.post("/api/shopping-list")
def shopping_list(body: ShoppingRequest):
    have = [i.strip() for i in (body.have or []) if i and str(i).strip()]
    if body.user_id and mongo_ok and store is not None and not have:
        have = [item["ingredient"] for item in store.list_pantry(body.user_id) if item.get("ingredient")]
    if body.plan or body.missing:
        grocery = build_grocery_list(plan=body.plan, missing=body.missing, have=have)
        return grocery
    raise HTTPException(400, "Provide missing ingredients or a meal plan.")


@app.get("/api/low-stock")
def low_stock(user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    return {"low_stock": store.low_stock(user_id)}


@app.get("/api/recipes/{recipe_id}")
def get_recipe(recipe_id: str):
    if matcher is None:
        raise HTTPException(503, "Recipe matcher not ready")
    recipe = matcher.get_by_id(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    from backend.filters import enrich_recipe

    return {"recipe": enrich_recipe(recipe)}


@app.post("/api/favorites")
def toggle_favorite(body: FavoriteRequest):
    require_mongo()
    assert store is not None
    return store.toggle_favorite(body.user_id, body.recipe)


@app.get("/api/favorites")
def list_favorites(user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    return {"favorites": store.list_favorites(user_id)}


@app.delete("/api/favorites/{favorite_id}")
def remove_favorite(favorite_id: str, user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    if not store.delete_favorite(user_id, favorite_id):
        raise HTTPException(404, "Favorite not found")
    return {"ok": True}


@app.delete("/api/favorites")
def clear_favorites(user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    removed = store.clear_favorites(user_id)
    return {"ok": True, "removed": removed}


@app.get("/api/history")
def cook_history(user_id: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50)):
    require_mongo()
    assert store is not None
    return {"history": store.cook_history(user_id, limit=limit)}


@app.delete("/api/history/{history_id}")
def remove_history_item(history_id: str, user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    if not store.delete_history_item(user_id, history_id):
        raise HTTPException(404, "History item not found")
    return {"ok": True}


@app.delete("/api/history")
def clear_history(user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    removed = store.clear_history(user_id)
    return {"ok": True, "removed": removed}


class CommentRequest(BaseModel):
    user_id: str
    text: str = Field(..., min_length=1, max_length=500)
    reply_to_comment_id: str | None = None


class CommentEditRequest(BaseModel):
    user_id: str
    text: str = Field(..., min_length=1, max_length=500)


class PostActionRequest(BaseModel):
    user_id: str


@app.get("/api/posts")
def list_posts(
    user_id: str | None = Query(None),
    view: str = Query("following", pattern="^(following|trending|all|for_you|reels)$"),
    limit: int = Query(20, ge=1, le=50),
    skip: int = Query(0, ge=0),
):
    require_mongo()
    assert store is not None
    assert post_store is not None
    if view == "reels":
        posts = post_store.list_reels(user_id, limit=limit, skip=skip)
        return {"posts": posts, "count": len(posts), "view": "reels"}
    if view == "for_you":
        if not user_id:
            posts = post_store.list_trending(None, limit=limit)
            view = "trending"
        else:
            taste = _user_taste(user_id)
            engine = _preference_engine()
            pool = post_store.list_feed(user_id, limit=min(80, limit * 4), skip=0)
            # Blend in trending so cold-start users still see content
            trending = post_store.list_trending(user_id, limit=min(40, limit * 2))
            seen = {p.get("post_id") for p in pool}
            for post in trending:
                if post.get("post_id") not in seen:
                    pool.append(post)
                    seen.add(post.get("post_id"))
            scored = sorted(pool, key=lambda p: engine.score_post(p, taste), reverse=True)
            posts = scored[:limit]
            for post in posts:
                post["pref_score"] = round(engine.score_post(post, taste), 1)
    elif view == "trending":
        posts = post_store.list_trending(user_id, limit=limit)
    elif view == "following":
        if user_id:
            following_ids = store.list_following_ids(user_id)
            posts = post_store.list_following_feed(user_id, following_ids, limit=limit)
        else:
            posts = post_store.list_feed(None, limit=limit, skip=skip)
            view = "all"
    else:
        posts = post_store.list_feed(user_id, limit=limit, skip=skip)
    return {"posts": posts, "count": len(posts), "view": view}


@app.get("/api/posts/bookmarks")
def list_bookmarked_posts(user_id: str = Query(..., min_length=1), limit: int = Query(30, ge=1, le=50)):
    require_mongo()
    assert post_store is not None
    posts = post_store.list_bookmarks(user_id, limit=limit)
    return {"posts": posts, "count": len(posts)}


@app.post("/api/posts")
async def create_post(
    user_id: str = Form(...),
    caption: str = Form(""),
    hashtags: str = Form(""),
    recipe_tag: str = Form(""),
    restaurant_tag: str = Form(""),
    is_reel: str = Form("false"),
    file: UploadFile = File(...),
):
    require_mongo()
    assert store is not None
    assert post_store is not None
    account = store.get_account(user_id)
    if not account:
        raise HTTPException(401, "Log in to share posts")
    try:
        raw = await file.read()
        tags = parse_hashtags(hashtags)
        reel_flag = str(is_reel or "").strip().lower() in {"1", "true", "yes", "on"}
        post = post_store.create_post(
            user_id,
            caption,
            tags,
            recipe_tag,
            restaurant_tag,
            raw,
            file.content_type or "",
            file.filename or "",
            is_reel=reel_flag,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"Could not save media file: {exc}") from exc
    return {"ok": True, "post": post}


@app.get("/api/posts/{post_id}")
def get_post(post_id: str, viewer_id: str | None = Query(None)):
    require_mongo()
    assert post_store is not None
    post = post_store.get_post(post_id, viewer_id)
    if not post:
        raise HTTPException(404, "Post not found")
    return {"post": post}


@app.post("/api/posts/{post_id}/like")
def toggle_post_like(post_id: str, body: PostActionRequest):
    require_mongo()
    assert post_store is not None
    assert notification_store is not None
    owner_id = post_store.get_post_owner(post_id)
    try:
        result = post_store.toggle_like(post_id, body.user_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if result.get("liked") and owner_id:
        notification_store.create(owner_id, body.user_id, "like", post_id=post_id)
    return result


@app.get("/api/posts/{post_id}/comments")
def list_post_comments(
    post_id: str,
    viewer_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
):
    require_mongo()
    assert post_store is not None
    if post_store.get_post(post_id, viewer_id) is None:
        raise HTTPException(404, "Post not found")
    return {"comments": post_store.list_comments(post_id, viewer_id, limit=limit)}


@app.post("/api/posts/{post_id}/comments")
def add_post_comment(post_id: str, body: CommentRequest):
    require_mongo()
    assert store is not None
    assert post_store is not None
    assert notification_store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to comment on posts")
    owner_id = post_store.get_post_owner(post_id)
    try:
        comment = post_store.add_comment(
            post_id,
            body.user_id,
            body.text,
            reply_to_comment_id=body.reply_to_comment_id,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if owner_id and owner_id != body.user_id:
        notification_store.create(owner_id, body.user_id, "comment", post_id=post_id, preview=body.text)
    reply_target = comment.get("reply_to_user_id")
    if reply_target and reply_target != body.user_id:
        notification_store.create(reply_target, body.user_id, "reply", post_id=post_id, preview=body.text)
    return {"ok": True, "comment": comment, "comments_count": comment.get("comments_count")}


@app.put("/api/posts/{post_id}/comments/{comment_id}")
def edit_post_comment(post_id: str, comment_id: str, body: CommentEditRequest):
    require_mongo()
    assert store is not None
    assert post_store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to edit comments")
    try:
        comment = post_store.update_comment(post_id, comment_id, body.user_id, body.text)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "comment": comment}


@app.post("/api/posts/{post_id}/comments/{comment_id}/like")
def toggle_comment_like(post_id: str, comment_id: str, body: PostActionRequest):
    require_mongo()
    assert store is not None
    assert post_store is not None
    assert notification_store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to like comments")
    try:
        result = post_store.toggle_comment_like(post_id, comment_id, body.user_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    author_id = result.pop("comment_author_id", None)
    if result.get("liked") and author_id and author_id != body.user_id:
        notification_store.create(author_id, body.user_id, "comment_like", post_id=post_id)
    return result


@app.delete("/api/posts/{post_id}/comments/{comment_id}")
def delete_post_comment(post_id: str, comment_id: str, user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    assert post_store is not None
    account = store.get_account(user_id)
    if not account:
        raise HTTPException(401, "Log in to delete comments")
    is_admin = store.is_admin(user_id)
    try:
        result = post_store.delete_comment(post_id, comment_id, user_id, allow_admin=is_admin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True, **result}


@app.post("/api/posts/{post_id}/bookmark")
def toggle_post_bookmark(post_id: str, body: PostActionRequest):
    require_mongo()
    assert post_store is not None
    try:
        result = post_store.toggle_bookmark(post_id, body.user_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return result


@app.delete("/api/posts/{post_id}")
def delete_post(post_id: str, user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    assert post_store is not None
    account = store.get_account(user_id)
    if not account:
        raise HTTPException(401, "Log in to delete posts")
    is_admin = store.is_admin(user_id)
    try:
        post_store.delete_post(post_id, user_id, allow_admin=is_admin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@app.get("/api/messages/unread")
def messages_unread(user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert message_store is not None
    return {"unread_count": message_store.total_unread(user_id)}


@app.get("/api/messages/conversations")
def list_conversations(user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert message_store is not None
    return {"conversations": message_store.list_conversations(user_id)}


@app.post("/api/messages/conversations/direct")
def open_direct_chat(body: DirectChatRequest):
    require_mongo()
    assert store is not None
    assert message_store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to send messages")
    try:
        conv = message_store.get_or_create_direct(body.user_id, body.other_user_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "conversation": conv}


@app.get("/api/messages/conversations/{conversation_id}/messages")
def list_chat_messages(
    conversation_id: str,
    user_id: str = Query(..., min_length=1),
    limit: int = Query(80, ge=1, le=200),
):
    require_mongo()
    assert message_store is not None
    try:
        messages = message_store.list_messages(conversation_id, user_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"messages": messages}


@app.post("/api/messages/conversations/{conversation_id}/messages")
def send_chat_message(conversation_id: str, body: MessageSendRequest):
    require_mongo()
    assert store is not None
    assert message_store is not None
    assert notification_store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to send messages")
    try:
        msg = message_store.send_message(conversation_id, body.user_id, body.text)
        conv = message_store._require_member(conversation_id, body.user_id)
        for pid in conv.get("participants", []):
            if pid != body.user_id:
                notification_store.create(pid, body.user_id, "message", preview=body.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "message": msg}


@app.post("/api/messages/conversations/{conversation_id}/media")
async def send_chat_media(
    conversation_id: str,
    user_id: str = Form(...),
    text: str = Form(""),
    kind: str = Form(""),
    file: UploadFile = File(...),
):
    require_mongo()
    assert store is not None
    assert message_store is not None
    assert notification_store is not None
    if not store.get_account(user_id):
        raise HTTPException(401, "Log in to send messages")
    raw = await file.read()
    preferred = (kind or "").strip().lower() or None
    if preferred and preferred not in {"image", "video", "voice", "document"}:
        preferred = None
    try:
        msg = message_store.save_and_send_attachment(
            conversation_id,
            user_id,
            file_bytes=raw,
            content_type=file.content_type or "",
            filename=file.filename or "",
            text=text or "",
            preferred_kind=preferred,
        )
        conv = message_store._require_member(conversation_id, user_id)
        preview = msg.get("text") or msg.get("file_name") or msg.get("media_type") or "Attachment"
        for pid in conv.get("participants", []):
            if pid != user_id:
                notification_store.create(pid, user_id, "message", preview=str(preview)[:120])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"Could not save file: {exc}") from exc
    return {"ok": True, "message": msg}


@app.post("/api/messages/conversations/{conversation_id}/read")
def mark_chat_read(conversation_id: str, body: PostActionRequest):
    require_mongo()
    assert message_store is not None
    try:
        message_store.mark_read(conversation_id, body.user_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@app.delete("/api/messages/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    assert message_store is not None
    if not store.get_account(user_id):
        raise HTTPException(401, "Log in to delete chats")
    try:
        message_store.delete_conversation(conversation_id, user_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@app.delete("/api/messages/conversations/{conversation_id}/messages/{message_id}")
def delete_chat_message(
    conversation_id: str,
    message_id: str,
    user_id: str = Query(..., min_length=1),
):
    require_mongo()
    assert store is not None
    assert message_store is not None
    if not store.get_account(user_id):
        raise HTTPException(401, "Log in to delete messages")
    try:
        message_store.delete_message(conversation_id, message_id, user_id)
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(403 if "only delete" in msg else 404, msg) from exc
    return {"ok": True}


@app.post("/api/messages/conversations/{conversation_id}/messages/{message_id}/reactions")
def react_to_message(conversation_id: str, message_id: str, body: MessageReactionRequest):
    require_mongo()
    assert store is not None
    assert message_store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to react to messages")
    try:
        result = message_store.toggle_reaction(conversation_id, message_id, body.user_id, body.emoji)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@app.get("/api/emojis")
def get_emojis(
    category: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(120, ge=1, le=300),
):
    return list_emojis(category=category, q=q, limit=limit)


@app.get("/api/stickers/packs")
def get_sticker_packs():
    return {"packs": list_sticker_packs()}


@app.get("/api/profile")
def get_profile(user_id: str = Query(..., min_length=1), viewer_id: str | None = Query(None)):
    require_mongo()
    assert store is not None
    try:
        return store.get_public_profile(user_id, viewer_id or user_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.put("/api/profile")
def update_profile(body: ProfileRequest):
    require_mongo()
    assert store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to save profile")
    try:
        profile = store.update_profile(
            body.user_id,
            body.allergies,
            body.cuisines,
            body.bio,
            display_name=body.display_name,
            country=body.country,
            is_public=body.is_public,
            is_active=body.is_active,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "profile": profile}


@app.post("/api/profile/avatar")
async def upload_avatar(user_id: str = Form(...), file: UploadFile = File(...)):
    require_mongo()
    assert store is not None
    account = store.get_account(user_id)
    if not account:
        raise HTTPException(401, "Log in to update profile picture")
    try:
        raw = await file.read()
        url = save_avatar(user_id, raw, file.content_type or "", file.filename or "")
        store.set_avatar_url(user_id, url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"Could not save profile picture: {exc}") from exc
    return {"ok": True, "avatar_url": url}


@app.get("/api/stories/feed")
def stories_feed(user_id: str = Query(..., min_length=1), limit: int = Query(40, ge=1, le=80)):
    require_mongo()
    assert store is not None
    assert story_store is not None
    if not store.get_account(user_id):
        raise HTTPException(401, "Log in to view stories")
    return {"items": story_store.feed_for(user_id, limit=limit)}


@app.get("/api/stories/user/{target_user_id}")
def user_stories(target_user_id: str, viewer_id: str | None = Query(None)):
    require_mongo()
    assert store is not None
    assert story_store is not None
    if not store.can_view_profile_content(target_user_id, viewer_id):
        return {
            "user": story_store._user_brief(target_user_id),
            "stories": [],
            "has_active_story": False,
            "story_seen": True,
            "private": True,
        }
    stories = story_store.list_user_stories(target_user_id, viewer_id)
    return {
        "user": story_store._user_brief(target_user_id),
        "stories": stories,
        "has_active_story": bool(stories),
        "story_seen": bool(stories) and all(s.get("seen") for s in stories),
    }


@app.post("/api/stories")
async def create_story(
    user_id: str = Form(...),
    caption: str = Form(""),
    file: UploadFile = File(...),
):
    require_mongo()
    assert store is not None
    assert story_store is not None
    if not store.get_account(user_id):
        raise HTTPException(401, "Log in to post a story")
    raw = await file.read()
    try:
        story = story_store.create_story(
            user_id,
            file_bytes=raw,
            content_type=file.content_type or "",
            filename=file.filename or "",
            caption=caption or "",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"Could not save story: {exc}") from exc
    return {"ok": True, "story": story}


@app.post("/api/stories/{story_id}/view")
def view_story(story_id: str, body: PostActionRequest):
    require_mongo()
    assert store is not None
    assert story_store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to view stories")
    owner_id = story_store.get_story_owner(story_id)
    if not owner_id:
        raise HTTPException(404, "Story not found")
    if not store.can_view_profile_content(owner_id, body.user_id):
        raise HTTPException(403, "This story is private")
    try:
        story = story_store.mark_viewed(story_id, body.user_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True, "story": story}


@app.get("/api/stories/{story_id}/viewers")
def story_viewers(story_id: str, user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    assert story_store is not None
    if not store.get_account(user_id):
        raise HTTPException(401, "Log in to see story viewers")
    try:
        return story_store.list_viewers(story_id, user_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.delete("/api/stories/{story_id}")
def delete_story(story_id: str, user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    assert story_store is not None
    if not store.get_account(user_id):
        raise HTTPException(401, "Log in to delete stories")
    try:
        story_store.delete_story(story_id, user_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@app.get("/api/users/search")
def search_users(
    q: str = Query(..., min_length=2, max_length=32),
    viewer_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=30),
):
    require_mongo()
    assert store is not None
    return {"users": store.search_users(q, limit=limit, viewer_id=viewer_id)}


@app.get("/api/notifications")
def list_notifications(
    user_id: str = Query(..., min_length=1),
    limit: int = Query(30, ge=1, le=50),
    unread_only: bool = Query(False),
):
    require_mongo()
    assert notification_store is not None
    items = notification_store.list_for_user(user_id, limit=limit, unread_only=unread_only)
    unread = notification_store.unread_count(user_id)
    return {"notifications": items, "unread_count": unread}


@app.post("/api/notifications/read-all")
def mark_all_notifications_read(body: PostActionRequest):
    require_mongo()
    assert notification_store is not None
    count = notification_store.mark_all_read(body.user_id)
    return {"ok": True, "marked": count}


@app.post("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: str, body: PostActionRequest):
    require_mongo()
    assert notification_store is not None
    if not notification_store.mark_read(body.user_id, notification_id):
        raise HTTPException(404, "Notification not found")
    return {"ok": True}


@app.get("/api/users/{target_user_id}/followers")
def user_followers(
    target_user_id: str,
    viewer_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
):
    require_mongo()
    assert store is not None
    try:
        return {"users": store.list_followers(target_user_id, limit=limit, viewer_id=viewer_id)}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@app.get("/api/users/{target_user_id}/following")
def user_following(
    target_user_id: str,
    viewer_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
):
    require_mongo()
    assert store is not None
    try:
        return {"users": store.list_following(target_user_id, limit=limit, viewer_id=viewer_id)}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@app.post("/api/users/{target_user_id}/follow")
def toggle_follow(target_user_id: str, body: FollowRequest):
    require_mongo()
    assert store is not None
    assert notification_store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to follow users")
    try:
        result = store.follow_user(body.user_id, target_user_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result.get("following"):
        notification_store.create(target_user_id, body.user_id, "follow")
    return result


@app.get("/api/users/{target_user_id}/posts")
def user_posts(
    target_user_id: str,
    viewer_id: str | None = Query(None),
    limit: int = Query(30, ge=1, le=50),
):
    require_mongo()
    assert store is not None
    assert post_store is not None
    if not store.can_view_profile_content(target_user_id, viewer_id):
        return {"posts": [], "count": 0, "can_view_content": False}
    posts = post_store.list_user_posts(target_user_id, viewer_id, limit=limit)
    return {"posts": posts, "count": len(posts), "can_view_content": True}


@app.get("/api/users/{target_user_id}/recipes")
def user_recipes(
    target_user_id: str,
    viewer_id: str | None = Query(None),
    limit: int = Query(30, ge=1, le=50),
):
    require_mongo()
    assert store is not None
    if not store.can_view_profile_content(target_user_id, viewer_id):
        return {"recipes": [], "count": 0, "can_view_content": False}
    history = store.cook_history(target_user_id, limit=limit)
    return {"recipes": history, "count": len(history), "can_view_content": True}


@app.get("/api/places/geocode")
def places_geocode(q: str = Query(..., min_length=2), limit: int = Query(5, ge=1, le=10)):
    assert places_service is not None
    try:
        results = places_service.geocode(q, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Location lookup failed: {exc}") from exc
    return {"results": results, "count": len(results)}


@app.get("/api/places/reverse")
def places_reverse(lat: float = Query(...), lng: float = Query(...)):
    assert places_service is not None
    try:
        result = places_service.reverse_geocode(lat, lng)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Reverse geocode failed: {exc}") from exc
    if not result:
        raise HTTPException(404, "Could not resolve that location")
    return {"result": result}


@app.get("/api/places/nearby")
def places_nearby(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(5000, ge=500, le=15000),
    cuisine: str | None = Query(None),
    min_rating: float | None = Query(None, ge=0, le=5),
    max_price: int | None = Query(None, ge=1, le=4),
    halal: bool | None = Query(None),
    haram: bool | None = Query(None),
    vegetarian: bool | None = Query(None),
    delivery: bool | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(20, ge=10, le=60),
    min_results: int = Query(10, ge=1, le=40),
    user_id: str | None = Query(None),
):
    assert places_service is not None
    try:
        places = places_service.nearby(
            lat,
            lng,
            radius_m=radius,
            cuisine=cuisine,
            min_rating=min_rating,
            max_price=max_price,
            halal=halal,
            haram=haram,
            vegetarian=vegetarian,
            delivery=delivery,
            q=q,
            limit=limit,
            min_results=min_results,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            502,
            f"Nearby search failed (map servers busy). Try again in a moment: {exc}",
        ) from exc

    if user_id and mongo_ok and store is not None:
        taste = _user_taste(user_id)
        if taste and taste.get("signals"):
            for place in places:
                bump = 0.0
                for name, w in (taste.get("liked_restaurants") or {}).items():
                    if str(name).lower() in str(place.get("name") or "").lower():
                        bump += float(w) * 2
                for cuisine_name, w in (taste.get("cuisine_weights") or {}).items():
                    if str(cuisine_name).lower() in str(place.get("cuisine") or "").lower():
                        bump += float(w)
                place["pref_score"] = round(bump - float(place.get("distance_km") or 0), 2)
            places.sort(
                key=lambda p: (
                    -(p.get("pref_score") or 0),
                    p.get("distance_km") is None,
                    p.get("distance_km") or 999,
                )
            )
        for place in places:
            place["saved"] = store.is_restaurant_saved(
                user_id, place_id=place.get("place_id"), name=place.get("name")
            )

    return {
        "places": places,
        "count": len(places),
        "center": {"lat": lat, "lng": lng},
        "radius_m": radius,
    }


@app.get("/api/places/{place_id}")
def place_details(
    place_id: str,
    lat: float | None = Query(None),
    lng: float | None = Query(None),
    user_id: str | None = Query(None),
):
    assert places_service is not None
    try:
        place = places_service.details(place_id, lat=lat, lng=lng)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Place details failed: {exc}") from exc
    if not place:
        raise HTTPException(404, "Place not found")
    if user_id and mongo_ok and store is not None:
        place["saved"] = store.is_restaurant_saved(
            user_id, place_id=place.get("place_id"), name=place.get("name")
        )
    return {"place": place}


@app.get("/api/saved-restaurants")
def list_saved_restaurants(user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    return {"restaurants": store.list_saved_restaurants(user_id)}


@app.get("/api/restaurants/recommended")
def recommended_restaurants(user_id: str = Query(..., min_length=1), limit: int = Query(8, ge=1, le=20)):
    require_mongo()
    taste = _user_taste(user_id)
    engine = _preference_engine()
    items = engine.recommend_restaurants(taste, limit=limit)
    # Dedupe against already-saved names
    saved = {str(r.get("restaurant_name") or "").strip().lower() for r in store.list_saved_restaurants(user_id)}
    fresh = [i for i in items if i["restaurant_name"].strip().lower() not in saved]
    return {
        "restaurants": fresh or items[:limit],
        "preferences": engine.summary(taste),
    }


@app.get("/api/preferences")
def get_preferences(user_id: str = Query(..., min_length=1)):
    require_mongo()
    taste = _user_taste(user_id) or {}
    liked = taste.get("liked_restaurants") or {}
    if hasattr(liked, "most_common"):
        restaurant_names = [n for n, _ in liked.most_common(8)]
    else:
        restaurant_names = list(liked.keys())[:8]
    return {
        "preferences": _preference_engine().summary(taste),
        "taste": {
            "top_cuisines": taste.get("top_cuisines") or [],
            "allergies": taste.get("allergies") or [],
            "restaurant_affinities": restaurant_names,
        },
    }


@app.post("/api/saved-restaurants")
def save_restaurant(body: SavedRestaurantRequest):
    require_mongo()
    assert store is not None
    if not store.get_account(body.user_id):
        raise HTTPException(401, "Log in to save restaurants")
    try:
        result = store.toggle_saved_restaurant(
            body.user_id,
            body.restaurant_name,
            body.area,
            place_id=body.place_id,
            address=body.address,
            lat=body.lat,
            lng=body.lng,
            rating=body.rating,
            price_level=body.price_level,
            cuisine=body.cuisine,
            website=body.website,
            maps_url=body.maps_url,
            directions_url=body.directions_url,
            halal=body.halal,
            vegetarian=body.vegetarian,
            delivery=body.delivery,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@app.delete("/api/saved-restaurants/{restaurant_id}")
def remove_saved_restaurant(restaurant_id: str, user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    try:
        store.remove_saved_restaurant(user_id, restaurant_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@app.get("/api/leaderboard")
def leaderboard(limit: int = Query(10, ge=1, le=25)):
    require_mongo()
    assert store is not None
    return {"leaderboard": store.leaderboard(limit=limit)}


@app.get("/api/auth/providers")
def auth_providers():
    return {"providers": oauth_providers_status()}


@app.post("/api/auth/register")
def register(body: RegisterRequest):
    require_mongo()
    assert store is not None
    try:
        user = store.register(body.username, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "user": user}


@app.post("/api/auth/login")
def login(body: LoginRequest):
    require_mongo()
    assert store is not None
    try:
        user = store.login(body.username, body.password)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    return {"ok": True, "user": user}


@app.post("/api/auth/oauth")
def oauth_login(body: OAuthLoginRequest):
    require_mongo()
    assert store is not None
    try:
        identity = verify_oauth_credential(body.provider, body.credential)
        user = store.login_with_oauth(identity)
    except OAuthError as exc:
        raise HTTPException(401, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "user": user}


@app.get("/api/auth/me")
def me(user_id: str = Query(..., min_length=1)):
    require_mongo()
    assert store is not None
    user = store.get_account(user_id)
    if not user:
        raise HTTPException(404, "Account not found. Please log in.")
    return {"user": user}


@app.delete("/api/auth/account")
def delete_account(body: DeleteAccountRequest):
    require_mongo()
    assert store is not None
    if not body.password and not body.confirm_text:
        raise HTTPException(400, "Password or confirmation text required")
    try:
        store.delete_account(body.user_id, password=body.password, confirm_text=body.confirm_text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "message": "Account deleted"}


@app.get("/api/admin/stats")
def admin_stats(admin_user_id: str = Query(..., min_length=1)):
    require_admin(admin_user_id)
    assert store is not None
    return store.platform_stats()


@app.get("/api/admin/users")
def admin_users(admin_user_id: str = Query(..., min_length=1), limit: int = Query(100, ge=1, le=200)):
    require_admin(admin_user_id)
    assert store is not None
    return {"users": store.list_all_users(limit=limit)}


@app.put("/api/admin/role")
def admin_set_role(body: RoleRequest):
    require_admin(body.admin_user_id)
    assert store is not None
    try:
        user = store.set_user_role(body.target_user_id, body.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "user": user}


uploads_dir = ROOT / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
(uploads_dir / "posts").mkdir(parents=True, exist_ok=True)
(uploads_dir / "avatars").mkdir(parents=True, exist_ok=True)
(uploads_dir / "messages").mkdir(parents=True, exist_ok=True)
(uploads_dir / "stories").mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

frontend_dir = ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dir), name="assets")

    @app.get("/")
    def index():
        return FileResponse(frontend_dir / "index.html")
