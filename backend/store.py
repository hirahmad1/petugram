"""MongoDB-backed user data: sustainability, pantry, gamification."""

from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from backend.auth import hash_password, verify_password
from backend.db import get_db, utcnow

ROOT = Path(__file__).resolve().parent.parent

BADGES = [
    {"id": "zero_waste_hero", "name": "Zero Waste Hero", "icon": "🌍", "rule": "Cook 10 meals from leftovers"},
    {"id": "streak_7", "name": "7-Day Streak", "icon": "🔥", "rule": "Cook 7 days in a row"},
]

STORES = [
    {"name": "Imtiaz Super Market", "area": "Karachi"},
    {"name": "Carrefour", "area": "Lahore"},
    {"name": "Al-Fatah", "area": "Islamabad"},
    {"name": "Metro Cash & Carry", "area": "Multan"},
]


class UserStore:
    def __init__(self) -> None:
        pass

    def _users(self):
        return get_db().users

    def _pantry(self):
        return get_db().pantry

    def _history(self):
        return get_db().cook_history

    def _favorites(self):
        return get_db().favorites

    def _meal_plans(self):
        return get_db().meal_plans

    def _follows(self):
        return get_db().user_follows

    def _saved_restaurants(self):
        return get_db().saved_restaurants

    def ensure_user(self, user_id: str) -> dict:
        doc = self._users().find_one({"user_id": user_id})
        if doc:
            if "role" not in doc:
                self._users().update_one({"user_id": user_id}, {"$set": {"role": "user"}})
                doc["role"] = "user"
            return doc
        new_user = {
            "user_id": user_id,
            "password_hash": None,
            "role": "user",
            "allergies": [],
            "cuisines": [],
            "points": 0,
            "streak": 0,
            "last_cook_date": None,
            "badges": [],
            "totals": {
                "meals": 0,
                "ingredients_saved": 0,
            },
            "bio": "",
            "display_name": "",
            "country": "PK",
            "avatar_url": None,
            "is_public": True,
            "is_active": True,
            "created_at": utcnow(),
        }
        self._users().insert_one(new_user)
        return new_user

    def is_admin(self, user_id: str) -> bool:
        user = self._users().find_one({"user_id": user_id}, {"role": 1})
        return bool(user and user.get("role") == "admin")

    def register(self, username: str, password: str) -> dict:
        from backend.auth import validate_password, validate_username

        username = validate_username(username)
        password = validate_password(password, strict=True)
        if self._users().find_one({"username": username}):
            raise ValueError("Username already taken")

        user_id = f"user_{username}"
        if self._users().find_one({"user_id": user_id}):
            user_id = f"user_{username}_{secrets.token_hex(3)}"

        doc = {
            "user_id": user_id,
            "username": username,
            "password_hash": hash_password(password),
            "role": "user",
            "allergies": [],
            "cuisines": [],
            "points": 0,
            "streak": 0,
            "last_cook_date": None,
            "badges": [],
            "totals": {
                "meals": 0,
                "ingredients_saved": 0,
            },
            "bio": "",
            "display_name": "",
            "country": "PK",
            "avatar_url": None,
            "email": None,
            "oauth_accounts": [],
            "is_public": True,
            "is_active": True,
            "created_at": utcnow(),
        }
        self._users().insert_one(doc)
        return self._public_user(doc)

    def login(self, username: str, password: str) -> dict:
        from backend.auth import normalize_username, validate_password

        username = normalize_username(username)
        if len(username) < 3:
            raise ValueError("Invalid username or password")
        # Login stays compatible with older shorter passwords
        validate_password(password, strict=False)
        doc = self._users().find_one({"username": username})
        if not doc or not doc.get("password_hash"):
            raise ValueError("Invalid username or password")
        if not verify_password(password, doc["password_hash"]):
            raise ValueError("Invalid username or password")
        return self._public_user(doc)

    def login_with_oauth(self, identity: dict) -> dict:
        from backend.auth import suggest_username_from_identity, validate_username

        provider = (identity.get("provider") or "").strip().lower()
        sub = str(identity.get("sub") or "").strip()
        if provider not in {"google", "facebook"} or not sub:
            raise ValueError("Invalid OAuth identity")

        email = (identity.get("email") or "").strip().lower() or None
        name = (identity.get("name") or "").strip() or None
        picture = (identity.get("picture") or "").strip() or None

        doc = self._users().find_one({"oauth_accounts": {"$elemMatch": {"provider": provider, "sub": sub}}})
        if not doc and email:
            doc = self._users().find_one({"email": email})

        if doc:
            accounts = list(doc.get("oauth_accounts") or [])
            if not any(a.get("provider") == provider and a.get("sub") == sub for a in accounts):
                accounts.append({"provider": provider, "sub": sub, "email": email})
            updates: dict = {"oauth_accounts": accounts}
            if email and not doc.get("email"):
                updates["email"] = email
            if picture and not doc.get("avatar_url"):
                updates["avatar_url"] = picture
            if name and not (doc.get("display_name") or "").strip():
                updates["display_name"] = name[:80]
            self._users().update_one({"user_id": doc["user_id"]}, {"$set": updates})
            doc = self._users().find_one({"user_id": doc["user_id"]})
            return self._public_user(doc)

        base = suggest_username_from_identity(name, email, f"{provider}{sub[-4:]}")
        username = base
        for _ in range(12):
            try:
                validate_username(username)
            except ValueError:
                username = f"chef{secrets.token_hex(2)}"
                continue
            if not self._users().find_one({"username": username}):
                break
            username = f"{base[:18]}{secrets.token_hex(2)}"
        else:
            username = f"chef{secrets.token_hex(4)}"

        user_id = f"user_{username}"
        if self._users().find_one({"user_id": user_id}):
            user_id = f"user_{username}_{secrets.token_hex(3)}"

        doc = {
            "user_id": user_id,
            "username": username,
            "password_hash": None,
            "role": "user",
            "allergies": [],
            "cuisines": [],
            "points": 0,
            "streak": 0,
            "last_cook_date": None,
            "badges": [],
            "totals": {"meals": 0, "ingredients_saved": 0},
            "bio": "",
            "display_name": (name or "")[:80],
            "country": "PK",
            "avatar_url": picture,
            "email": email,
            "oauth_accounts": [{"provider": provider, "sub": sub, "email": email}],
            "is_public": True,
            "is_active": True,
            "created_at": utcnow(),
        }
        self._users().insert_one(doc)
        return self._public_user(doc)

    def get_account(self, user_id: str) -> dict | None:
        doc = self._users().find_one({"user_id": user_id})
        if not doc or not doc.get("username"):
            return None
        return self._public_user(doc, viewer_id=user_id)

    def _story_flags(self, user_id: str, viewer_id: str | None = None) -> dict:
        try:
            from backend.stories import StoryStore

            store = StoryStore()
            has_active = store.has_active_story(user_id)
            return {
                "has_active_story": has_active,
                "story_seen": store.story_seen_by(user_id, viewer_id) if has_active else False,
            }
        except Exception:
            return {"has_active_story": False, "story_seen": False}

    def _public_user(self, doc: dict, viewer_id: str | None = None) -> dict:
        oauth_accounts = doc.get("oauth_accounts") or []
        providers = sorted({str(a.get("provider")) for a in oauth_accounts if a.get("provider")})
        flags = self._story_flags(doc["user_id"], viewer_id or doc["user_id"])
        return {
            "user_id": doc["user_id"],
            "username": doc.get("username"),
            "role": doc.get("role", "user"),
            "points": doc.get("points", 0),
            "streak": doc.get("streak", 0),
            "has_password": bool(doc.get("password_hash")),
            "auth_providers": providers,
            "email": doc.get("email"),
            "avatar_url": doc.get("avatar_url"),
            "is_public": bool(doc.get("is_public", True)),
            "is_active": bool(doc.get("is_active", True)),
            **flags,
        }

    def can_view_profile_content(self, target_user_id: str, viewer_id: str | None = None) -> bool:
        """Owner and followers can always see content; public active accounts are open to all."""
        user = self._users().find_one({"user_id": target_user_id})
        if not user or not user.get("username"):
            return False
        if viewer_id and viewer_id == target_user_id:
            return True
        if not bool(user.get("is_active", True)):
            return False
        if bool(user.get("is_public", True)):
            return True
        if not viewer_id:
            return False
        return (
            self._follows().find_one({"follower_id": viewer_id, "following_id": target_user_id}) is not None
        )

    def can_view_follow_lists(self, target_user_id: str, viewer_id: str | None = None) -> bool:
        user = self._users().find_one({"user_id": target_user_id})
        if not user or not user.get("username"):
            return False
        if viewer_id and viewer_id == target_user_id:
            return True
        if not bool(user.get("is_active", True)):
            return False
        if bool(user.get("is_public", True)):
            return True
        if not viewer_id:
            return False
        return (
            self._follows().find_one({"follower_id": viewer_id, "following_id": target_user_id}) is not None
        )

    def ensure_admin(self, username: str, password: str) -> dict:
        username = username.strip().lower()
        existing = self._users().find_one({"username": username})
        if existing:
            self._users().update_one(
                {"username": username},
                {"$set": {"role": "admin", "password_hash": hash_password(password)}},
            )
            return self._public_user(self._users().find_one({"username": username}))

        user_id = f"admin_{username}"
        doc = {
            "user_id": user_id,
            "username": username,
            "password_hash": hash_password(password),
            "role": "admin",
            "allergies": [],
            "cuisines": [],
            "points": 0,
            "streak": 0,
            "last_cook_date": None,
            "badges": [],
            "totals": {
                "meals": 0,
                "ingredients_saved": 0,
            },
            "bio": "",
            "display_name": "",
            "country": "PK",
            "avatar_url": None,
            "is_public": True,
            "is_active": True,
            "created_at": utcnow(),
        }
        self._users().insert_one(doc)
        return self._public_user(doc)

    def list_all_users(self, limit: int = 100) -> list[dict]:
        rows = []
        for doc in self._users().find({"username": {"$ne": None}}).sort("created_at", -1).limit(limit):
            rows.append(
                {
                    "user_id": doc["user_id"],
                    "username": doc.get("username"),
                    "role": doc.get("role", "user"),
                    "points": doc.get("points", 0),
                    "meals": doc.get("totals", {}).get("meals", 0),
                    "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
                }
            )
        return rows

    def set_user_role(self, target_user_id: str, role: str) -> dict:
        if role not in {"user", "admin"}:
            raise ValueError("Role must be user or admin")
        result = self._users().update_one({"user_id": target_user_id}, {"$set": {"role": role}})
        if result.matched_count == 0:
            raise ValueError("User not found")
        doc = self._users().find_one({"user_id": target_user_id})
        return self._public_user(doc)

    def delete_account(self, user_id: str, password: str | None = None, confirm_text: str | None = None) -> None:
        user = self._users().find_one({"user_id": user_id})
        if not user:
            raise ValueError("Account not found")
        has_password = bool(user.get("password_hash"))
        oauth_only = bool(user.get("oauth_accounts")) and not has_password
        if has_password:
            if not password or not verify_password(password, user["password_hash"]):
                raise ValueError("Incorrect password")
        elif oauth_only:
            expected = f"delete {user.get('username')}"
            if (confirm_text or "").strip().lower() != expected:
                raise ValueError(f'Type "{expected}" to confirm account deletion')
        else:
            raise ValueError("Account not found")
        if user.get("role") == "admin":
            admin_count = self._users().count_documents({"role": "admin"})
            if admin_count <= 1:
                raise ValueError("Cannot delete the only admin account")
        self._pantry().delete_many({"user_id": user_id})
        self._history().delete_many({"user_id": user_id})
        self._favorites().delete_many({"user_id": user_id})
        try:
            from backend.posts import PostStore
            from backend.profiles import delete_avatar_file
            from backend.notifications import NotificationStore
            from backend.messaging import MessageStore
            from backend.stories import StoryStore
            from backend.surplus import SurplusStore

            PostStore().delete_user_data(user_id)
            NotificationStore().delete_user_data(user_id)
            MessageStore().delete_user_data(user_id)
            StoryStore().delete_user_data(user_id)
            SurplusStore().delete_user_data(user_id)
            delete_avatar_file(user.get("avatar_url"))
        except Exception:
            pass
        self._follows().delete_many({"$or": [{"follower_id": user_id}, {"following_id": user_id}]})
        self._saved_restaurants().delete_many({"user_id": user_id})
        self._meal_plans().delete_many({"user_id": user_id})
        result = self._users().delete_one({"user_id": user_id})
        if result.deleted_count == 0:
            raise ValueError("Account not found")

    def platform_stats(self) -> dict:
        users = self._users().count_documents({"username": {"$ne": None}})
        admins = self._users().count_documents({"role": "admin"})
        meals = self._history().count_documents({})
        pantry_items = self._pantry().count_documents({})
        return {
            "registered_users": users,
            "admin_accounts": admins,
            "total_meals_cooked": meals,
            "pantry_items_tracked": pantry_items,
        }

    def get_profile(self, user_id: str, viewer_id: str | None = None) -> dict:
        user = self.ensure_user(user_id)
        return self._profile_payload(user, viewer_id)

    def get_public_profile(self, user_id: str, viewer_id: str | None = None) -> dict:
        user = self._users().find_one({"user_id": user_id})
        if not user or not user.get("username"):
            raise ValueError("User not found")
        return self._profile_payload(user, viewer_id)

    def _profile_payload(self, user: dict, viewer_id: str | None = None) -> dict:
        user_id = user["user_id"]
        is_own = bool(viewer_id and viewer_id == user_id)
        is_public = bool(user.get("is_public", True))
        is_active = bool(user.get("is_active", True))
        totals = user.get("totals", {})
        created = user.get("created_at")
        followers = self._follows().count_documents({"following_id": user_id})
        following = self._follows().count_documents({"follower_id": user_id})
        posts_count = get_db().posts.count_documents({"user_id": user_id})
        is_following = False
        if viewer_id and viewer_id != user_id:
            is_following = self._follows().find_one({"follower_id": viewer_id, "following_id": user_id}) is not None
        can_view = is_own or (is_active and (is_public or is_following))
        flags = self._story_flags(user_id, viewer_id) if (is_own or is_active) else {
            "has_active_story": False,
            "story_seen": False,
        }

        # Inactive to others: limited profile
        display_name = (user.get("display_name") or "").strip()[:80]
        country = (user.get("country") or "PK").strip().upper() or "PK"

        if not is_active and not is_own:
            return {
                "user_id": user_id,
                "username": user.get("username") or user_id.replace("_", " "),
                "display_name": display_name,
                "country": country,
                "role": user.get("role", "user"),
                "bio": "",
                "avatar_url": user.get("avatar_url"),
                "allergies": [],
                "cuisines": [],
                "points": 0,
                "streak": 0,
                "badges": [],
                "badge_catalog": [],
                "totals": {},
                "impact": None,
                "member_since": created.isoformat()[:10] if created else None,
                "followers_count": followers,
                "following_count": following,
                "posts_count": posts_count,
                "is_following": is_following,
                "is_own_profile": False,
                "is_public": is_public,
                "is_active": False,
                "can_view_content": False,
                "has_active_story": False,
                "story_seen": False,
            }

        from backend.impact import compute_impact

        visible_totals = totals if (is_own or can_view) else {}
        impact = None
        if is_own or can_view:
            impact = compute_impact(
                ingredients_saved=int(visible_totals.get("ingredients_saved", 0) or 0),
                meals=int(visible_totals.get("meals", 0) or 0),
                location_code=country,
            )

        payload = {
            "user_id": user_id,
            "username": user.get("username") or user_id.replace("_", " "),
            "display_name": display_name,
            "country": country,
            "role": user.get("role", "user"),
            "bio": (user.get("bio") or "").strip(),
            "avatar_url": user.get("avatar_url"),
            "allergies": user.get("allergies", []) if (is_own or can_view) else [],
            "cuisines": user.get("cuisines", []) if (is_own or can_view) else [],
            "points": int(user.get("points", 0)) if (is_own or can_view) else 0,
            "streak": int(user.get("streak", 0)) if (is_own or can_view) else 0,
            "badges": user.get("badges", []) if (is_own or can_view) else [],
            "badge_catalog": BADGES if (is_own or can_view) else [],
            "totals": visible_totals,
            "impact": impact,
            "member_since": created.isoformat()[:10] if created else None,
            "followers_count": followers,
            "following_count": following,
            "posts_count": posts_count,
            "is_following": is_following,
            "is_own_profile": is_own,
            "is_public": is_public,
            "is_active": is_active,
            "can_view_content": can_view,
            **flags,
        }
        return payload

    def update_profile(
        self,
        user_id: str,
        allergies: list[str] | None = None,
        cuisines: list[str] | None = None,
        bio: str | None = None,
        display_name: str | None = None,
        country: str | None = None,
        is_public: bool | None = None,
        is_active: bool | None = None,
    ) -> dict:
        self.ensure_user(user_id)

        def _clean(items: list[str], *, title: bool = False) -> list[str]:
            out: list[str] = []
            seen: set[str] = set()
            for raw in items or []:
                val = " ".join(str(raw).strip().split())
                if not val:
                    continue
                if title:
                    val = val.title()
                key = val.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(val[:60])
            return out[:20]

        update: dict = {}
        if allergies is not None:
            update["allergies"] = _clean(allergies, title=False)
        if cuisines is not None:
            update["cuisines"] = _clean(cuisines, title=True)
        if bio is not None:
            update["bio"] = (bio or "").strip()[:500]
        if display_name is not None:
            cleaned = " ".join((display_name or "").strip().split())
            if len(cleaned) > 80:
                raise ValueError("Name must be 80 characters or fewer")
            update["display_name"] = cleaned
        if country is not None:
            from backend.impact import LOCATIONS, DEFAULT_LOCATION

            code = (country or DEFAULT_LOCATION).strip().upper()
            if code not in LOCATIONS:
                raise ValueError("Choose a valid location")
            update["country"] = code
        if is_public is not None:
            update["is_public"] = bool(is_public)
        if is_active is not None:
            update["is_active"] = bool(is_active)
        if update:
            self._users().update_one({"user_id": user_id}, {"$set": update})
        return self.get_public_profile(user_id, user_id)

    def set_avatar_url(self, user_id: str, avatar_url: str) -> str:
        self.ensure_user(user_id)
        self._users().update_one({"user_id": user_id}, {"$set": {"avatar_url": avatar_url}})
        return avatar_url

    def list_following_ids(self, user_id: str) -> list[str]:
        return [doc["following_id"] for doc in self._follows().find({"follower_id": user_id}, {"following_id": 1})]

    def search_users(self, query: str, limit: int = 20, viewer_id: str | None = None) -> list[dict]:
        import re

        q = query.strip().lower()
        if len(q) < 2:
            return []
        pattern = re.compile(re.escape(q), re.IGNORECASE)
        docs = [
            d
            for d in self._users()
            .find({"$or": [{"username": pattern}, {"display_name": pattern}]})
            .sort("username", 1)
            .limit(limit * 3)
            if d.get("username") and (bool(d.get("is_active", True)) or (viewer_id and d["user_id"] == viewer_id))
        ][:limit]
        following_ids: set[str] = set()
        if viewer_id and docs:
            ids = [d["user_id"] for d in docs if d["user_id"] != viewer_id]
            if ids:
                following_ids = {
                    f["following_id"]
                    for f in self._follows().find(
                        {"follower_id": viewer_id, "following_id": {"$in": ids}},
                        {"following_id": 1},
                    )
                }
        rows = []
        for doc in docs:
            rows.append(
                {
                    "user_id": doc["user_id"],
                    "username": doc.get("username"),
                    "display_name": self._display_name_for(doc),
                    "avatar_url": doc.get("avatar_url"),
                    "bio": (doc.get("bio") or "")[:120],
                    "is_following": doc["user_id"] in following_ids,
                    "is_public": bool(doc.get("is_public", True)),
                    "is_active": bool(doc.get("is_active", True)),
                }
            )
        return rows

    def follow_user(self, follower_id: str, following_id: str) -> dict:
        if follower_id == following_id:
            raise ValueError("You cannot follow yourself")
        target = self._users().find_one({"user_id": following_id})
        if not target or not target.get("username"):
            raise ValueError("User not found")
        if not bool(target.get("is_active", True)):
            raise ValueError("This account is not active")
        self.ensure_user(follower_id)
        existing = self._follows().find_one({"follower_id": follower_id, "following_id": following_id})
        if existing:
            self._follows().delete_one({"_id": existing["_id"]})
            following = False
        else:
            self._follows().insert_one(
                {"follower_id": follower_id, "following_id": following_id, "created_at": utcnow()}
            )
            following = True
        count = self._follows().count_documents({"following_id": following_id})
        return {"following": following, "followers_count": count}

    def list_followers(self, user_id: str, limit: int = 50, viewer_id: str | None = None) -> list[dict]:
        if not self.can_view_follow_lists(user_id, viewer_id):
            raise PermissionError("Follow list is private")
        out = []
        for doc in self._follows().find({"following_id": user_id}).sort("created_at", -1).limit(limit):
            follower = self._users().find_one({"user_id": doc["follower_id"]})
            if follower and follower.get("username") and bool(follower.get("is_active", True)):
                out.append(self._follow_user_row(follower, doc.get("created_at")))
        return out

    def list_following(self, user_id: str, limit: int = 50, viewer_id: str | None = None) -> list[dict]:
        if not self.can_view_follow_lists(user_id, viewer_id):
            raise PermissionError("Follow list is private")
        out = []
        for doc in self._follows().find({"follower_id": user_id}).sort("created_at", -1).limit(limit):
            target = self._users().find_one({"user_id": doc["following_id"]})
            if target and target.get("username") and bool(target.get("is_active", True)):
                out.append(self._follow_user_row(target, doc.get("created_at")))
        return out

    def _display_name(self, username: str | None, user_id: str) -> str:
        raw_name = (username or "").strip() or str(user_id).replace("_", " ").strip() or "User"
        if " " in raw_name or len(raw_name) > 3:
            return " ".join(part[:1].upper() + part[1:] for part in raw_name.split() if part) or "User"
        return raw_name

    def _display_name_for(self, user: dict) -> str:
        custom = (user.get("display_name") or "").strip()
        if custom:
            return custom[:80]
        return self._display_name(user.get("username"), user.get("user_id") or "")

    def _follow_user_row(self, user: dict, followed_at) -> dict:
        return {
            "user_id": user["user_id"],
            "username": user.get("username"),
            "display_name": self._display_name_for(user),
            "avatar_url": user.get("avatar_url"),
            "bio": (user.get("bio") or "")[:120],
            "followed_at": followed_at.isoformat() if followed_at else None,
            "is_active": bool(user.get("is_active", True)),
        }

    def toggle_saved_restaurant(
        self,
        user_id: str,
        restaurant_name: str,
        area: str = "",
        *,
        place_id: str | None = None,
        address: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
        rating: float | None = None,
        price_level: int | None = None,
        cuisine: str | None = None,
        website: str | None = None,
        maps_url: str | None = None,
        directions_url: str | None = None,
        halal: bool | None = None,
        vegetarian: bool | None = None,
        delivery: bool | None = None,
    ) -> dict:
        self.ensure_user(user_id)
        name = (restaurant_name or "").strip()
        if not name:
            raise ValueError("Restaurant name is required")
        place_id = (place_id or "").strip() or None
        existing = None
        if place_id:
            existing = self._saved_restaurants().find_one({"user_id": user_id, "place_id": place_id})
        if not existing:
            existing = self._saved_restaurants().find_one({"user_id": user_id, "restaurant_name": name})
        if existing:
            self._saved_restaurants().delete_one({"_id": existing["_id"]})
            return {"saved": False}
        doc = {
            "user_id": user_id,
            "restaurant_name": name[:120],
            "area": (area or "").strip()[:80],
            "place_id": place_id,
            "address": (address or "").strip()[:200] or None,
            "lat": lat,
            "lng": lng,
            "rating": rating,
            "price_level": price_level,
            "cuisine": (cuisine or "").strip()[:120] or None,
            "website": (website or "").strip()[:300] or None,
            "maps_url": (maps_url or "").strip()[:400] or None,
            "directions_url": (directions_url or "").strip()[:400] or None,
            "halal": bool(halal) if halal is not None else None,
            "vegetarian": bool(vegetarian) if vegetarian is not None else None,
            "delivery": bool(delivery) if delivery is not None else None,
            "saved_at": utcnow(),
        }
        self._saved_restaurants().insert_one(doc)
        doc["_id"] = str(doc["_id"])
        doc["saved_at"] = doc["saved_at"].isoformat()
        return {"saved": True, "restaurant": doc}

    def list_saved_restaurants(self, user_id: str) -> list[dict]:
        self.ensure_user(user_id)
        out = []
        for doc in self._saved_restaurants().find({"user_id": user_id}).sort("saved_at", -1):
            out.append(
                {
                    "_id": str(doc["_id"]),
                    "restaurant_name": doc.get("restaurant_name", ""),
                    "area": doc.get("area", ""),
                    "place_id": doc.get("place_id"),
                    "address": doc.get("address"),
                    "lat": doc.get("lat"),
                    "lng": doc.get("lng"),
                    "rating": doc.get("rating"),
                    "price_level": doc.get("price_level"),
                    "cuisine": doc.get("cuisine"),
                    "website": doc.get("website"),
                    "maps_url": doc.get("maps_url"),
                    "directions_url": doc.get("directions_url"),
                    "halal": doc.get("halal"),
                    "vegetarian": doc.get("vegetarian"),
                    "delivery": doc.get("delivery"),
                    "saved_at": doc["saved_at"].isoformat() if doc.get("saved_at") else None,
                }
            )
        return out

    def is_restaurant_saved(self, user_id: str, *, place_id: str | None = None, name: str | None = None) -> bool:
        if place_id:
            if self._saved_restaurants().find_one({"user_id": user_id, "place_id": place_id}):
                return True
        if name:
            if self._saved_restaurants().find_one({"user_id": user_id, "restaurant_name": name.strip()}):
                return True
        return False

    def remove_saved_restaurant(self, user_id: str, restaurant_id: str) -> None:
        from bson import ObjectId

        try:
            oid = ObjectId(restaurant_id)
        except Exception as exc:
            raise ValueError("Restaurant not found") from exc
        result = self._saved_restaurants().delete_one({"_id": oid, "user_id": user_id})
        if result.deleted_count == 0:
            raise ValueError("Restaurant not found")

    def log_cook(self, user_id: str, recipe: dict) -> dict:
        user = self.ensure_user(user_id)
        today = date.today().isoformat()
        last = user.get("last_cook_date")
        streak = int(user.get("streak", 0))
        if last == today:
            pass
        elif last == (date.today() - timedelta(days=1)).isoformat():
            streak += 1
        else:
            streak = 1

        points = 15
        saved_count = len(recipe.get("matched_ingredients", []) or [])
        event = {
            "user_id": user_id,
            "recipe_id": recipe.get("id"),
            "recipe_name": recipe.get("name"),
            "ingredients_saved": saved_count,
            "cooked_at": utcnow(),
        }
        self._history().insert_one(event)

        totals = user.get("totals", {})
        new_totals = {
            "meals": int(totals.get("meals", 0)) + 1,
            "ingredients_saved": int(totals.get("ingredients_saved", 0)) + saved_count,
        }

        badges = list(user.get("badges", []))
        earned = self._check_badges(new_totals, streak, badges)
        badges.extend(earned)
        points += len(earned) * 50

        self._users().update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "streak": streak,
                    "last_cook_date": today,
                    "badges": badges,
                    "totals": new_totals,
                    "points": int(user.get("points", 0)) + points,
                }
            },
        )
        return {
            "points_earned": points,
            "new_badges": earned,
            "streak": streak,
            "totals": new_totals,
        }

    def _check_badges(self, totals: dict, streak: int, existing: list[str]) -> list[str]:
        earned: list[str] = []
        checks = [
            ("zero_waste_hero", totals["meals"] >= 10),
            ("streak_7", streak >= 7),
        ]
        for badge_id, ok in checks:
            if ok and badge_id not in existing:
                earned.append(badge_id)
        return earned

    def add_pantry_item(self, user_id: str, ingredient: str, expiry_date: str, qty: str = "1") -> dict:
        self.ensure_user(user_id)
        doc = {
            "user_id": user_id,
            "ingredient": ingredient.strip().lower(),
            "qty": qty,
            "expiry_date": expiry_date,
            "added_at": utcnow(),
        }
        result = self._pantry().insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return doc

    def list_pantry(self, user_id: str) -> list[dict]:
        self.ensure_user(user_id)
        items = []
        for doc in self._pantry().find({"user_id": user_id}).sort("expiry_date", 1):
            doc["_id"] = str(doc["_id"])
            items.append(doc)
        return items

    def delete_pantry_item(self, user_id: str, item_id: str) -> bool:
        from bson import ObjectId

        result = self._pantry().delete_one({"user_id": user_id, "_id": ObjectId(item_id)})
        return result.deleted_count > 0

    def delete_favorite(self, user_id: str, favorite_id: str) -> bool:
        from bson import ObjectId
        from bson.errors import InvalidId

        self.ensure_user(user_id)
        try:
            oid = ObjectId(favorite_id)
        except InvalidId:
            return False
        result = self._favorites().delete_one({"user_id": user_id, "_id": oid})
        return result.deleted_count > 0

    def clear_favorites(self, user_id: str) -> int:
        self.ensure_user(user_id)
        result = self._favorites().delete_many({"user_id": user_id})
        return result.deleted_count

    def delete_history_item(self, user_id: str, history_id: str) -> bool:
        from bson import ObjectId
        from bson.errors import InvalidId

        self.ensure_user(user_id)
        try:
            oid = ObjectId(history_id)
        except InvalidId:
            return False
        result = self._history().delete_one({"user_id": user_id, "_id": oid})
        return result.deleted_count > 0

    def clear_history(self, user_id: str) -> int:
        self.ensure_user(user_id)
        result = self._history().delete_many({"user_id": user_id})
        return result.deleted_count

    def expiry_alerts(self, user_id: str, days: int = 2) -> list[dict]:
        self.ensure_user(user_id)
        cutoff = (date.today() + timedelta(days=days)).isoformat()
        today = date.today().isoformat()
        alerts = []
        for doc in self._pantry().find(
            {"user_id": user_id, "expiry_date": {"$lte": cutoff}}
        ).sort("expiry_date", 1):
            ingredient = doc["ingredient"]
            exp = doc["expiry_date"]
            if exp < today:
                msg = f"Your {ingredient} expired. Cook it today!"
            elif exp == today:
                msg = f"Your {ingredient} expires today. Here are recipe ideas."
            else:
                msg = f"Your {ingredient} expires soon ({exp}). Use it before it goes to waste."
            alerts.append(
                {
                    "ingredient": ingredient,
                    "expiry_date": exp,
                    "message": msg,
                    "item_id": str(doc["_id"]),
                }
            )
        return alerts

    def shopping_list(self, missing: list[str]) -> dict:
        items = [{"ingredient": ing} for ing in missing if ing]
        return {"items": items}

    def low_stock(self, user_id: str) -> list[str]:
        pantry = {p["ingredient"] for p in self.list_pantry(user_id)}
        staples = ["egg", "onion", "tomato", "rice", "milk", "chicken", "potato"]
        return [s for s in staples if s not in pantry]

    def toggle_favorite(self, user_id: str, recipe: dict) -> dict:
        self.ensure_user(user_id)
        rid = recipe.get("id")
        existing = self._favorites().find_one({"user_id": user_id, "recipe_id": rid})
        if existing:
            self._favorites().delete_one({"_id": existing["_id"]})
            return {"favorited": False}
        # Keep a rich snapshot so Saved can open the full recipe later
        snapshot_keys = (
            "id",
            "name",
            "image",
            "cuisine",
            "calories",
            "protein",
            "carbs",
            "fat",
            "nutrition",
            "time_min",
            "difficulty",
            "diet",
            "halal",
            "goal",
            "ingredients",
            "measurements",
            "steps",
            "instructions",
            "video_url",
            "source_url",
            "matched_ingredients",
            "missing_ingredients",
            "match_score",
            "search_mode",
            "generated",
            "servings",
        )
        snapshot = {k: recipe.get(k) for k in snapshot_keys if recipe.get(k) is not None}
        if not snapshot.get("id") and rid:
            snapshot["id"] = rid
        if not snapshot.get("name"):
            snapshot["name"] = recipe.get("name") or "Recipe"
        self._favorites().insert_one(
            {
                "user_id": user_id,
                "recipe_id": rid,
                "recipe_name": recipe.get("name"),
                "recipe": snapshot,
                "saved_at": utcnow(),
            }
        )
        return {"favorited": True}

    def list_favorites(self, user_id: str) -> list[dict]:
        self.ensure_user(user_id)
        out = []
        for doc in self._favorites().find({"user_id": user_id}).sort("saved_at", -1):
            doc["_id"] = str(doc["_id"])
            if doc.get("saved_at"):
                doc["saved_at"] = doc["saved_at"].isoformat()
            out.append(doc)
        return out

    def save_meal_plan(self, user_id: str, plan: dict) -> dict:
        self.ensure_user(user_id)
        recipe_keys = (
            "id",
            "name",
            "image",
            "cuisine",
            "calories",
            "time_min",
            "difficulty",
            "diet",
            "ingredients",
            "matched_ingredients",
            "missing_ingredients",
            "substitutions",
            "steps",
            "instructions",
            "match_score",
        )

        def _slim_recipe(recipe: dict | None) -> dict | None:
            if not recipe:
                return None
            return {k: recipe.get(k) for k in recipe_keys if recipe.get(k) is not None}

        def _slim_meal(meal: dict | None) -> dict | None:
            if not meal:
                return None
            slim_recipe = _slim_recipe(meal.get("recipe"))
            return {
                "slot": meal.get("slot") or "dinner",
                "label": meal.get("label") or str(meal.get("slot") or "dinner").title(),
                "recipe": slim_recipe,
            }

        slim_days = []
        for day in plan.get("days") or []:
            meals = day.get("meals")
            if not meals and day.get("meal"):
                meals = [day["meal"]]
            slim_meals = [_slim_meal(m) for m in (meals or [])]
            slim_meals = [m for m in slim_meals if m]
            dinner = next((m for m in slim_meals if m.get("slot") == "dinner"), slim_meals[0] if slim_meals else None)
            slim_days.append(
                {
                    "day": day.get("day"),
                    "label": day.get("label") or f"Day {day.get('day')}",
                    "meals": slim_meals,
                    "meal": dinner,
                }
            )
        payload = {
            "user_id": user_id,
            "days": slim_days,
            "ingredients_used": plan.get("ingredients_used") or [],
            "filters": plan.get("filters") or {},
            "days_count": plan.get("days_count") or len(slim_days),
            "slots": plan.get("slots") or ["breakfast", "lunch", "dinner", "snack"],
            "updated_at": utcnow(),
        }
        self._meal_plans().update_one({"user_id": user_id}, {"$set": payload}, upsert=True)
        return self.get_meal_plan(user_id) or payload

    def get_meal_plan(self, user_id: str) -> dict | None:
        self.ensure_user(user_id)
        doc = self._meal_plans().find_one({"user_id": user_id})
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        if doc.get("updated_at"):
            doc["updated_at"] = doc["updated_at"].isoformat()
        return {
            "days": doc.get("days") or [],
            "ingredients_used": doc.get("ingredients_used") or [],
            "filters": doc.get("filters") or {},
            "days_count": doc.get("days_count") or len(doc.get("days") or []),
            "updated_at": doc.get("updated_at"),
        }

    def delete_meal_plan(self, user_id: str) -> bool:
        self.ensure_user(user_id)
        result = self._meal_plans().delete_one({"user_id": user_id})
        return result.deleted_count > 0

    def cook_history(self, user_id: str, limit: int = 20) -> list[dict]:
        self.ensure_user(user_id)
        out = []
        for doc in self._history().find({"user_id": user_id}).sort("cooked_at", -1).limit(limit):
            doc["_id"] = str(doc["_id"])
            doc["cooked_at"] = doc["cooked_at"].isoformat()
            out.append(doc)
        return out

    def monthly_report(self, user_id: str) -> dict:
        from backend.impact import compute_impact, list_locations

        user = self.ensure_user(user_id)
        now = utcnow()
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        pipeline = [
            {"$match": {"user_id": user_id, "cooked_at": {"$gte": start}}},
            {
                "$group": {
                    "_id": None,
                    "meals": {"$sum": 1},
                    "ingredients_saved": {"$sum": {"$ifNull": ["$ingredients_saved", 0]}},
                }
            },
        ]
        rows = list(self._history().aggregate(pipeline))
        month = rows[0] if rows else {}
        meals = int(month.get("meals", 0))
        month_ingredients = int(month.get("ingredients_saved", 0) or 0)
        totals = user.get("totals", {}) or {}
        all_meals = int(totals.get("meals", 0) or 0)
        all_ingredients = int(totals.get("ingredients_saved", 0) or 0)
        # Older cook events lack ingredients_saved — estimate from lifetime averages
        if meals and not month_ingredients and all_meals > 0 and all_ingredients > 0:
            month_ingredients = max(1, int(round(all_ingredients * (meals / all_meals))))
        score = min(100, int(meals * 8 + user.get("streak", 0) * 3))
        country = (user.get("country") or "PK").strip().upper() or "PK"
        impact_all = compute_impact(
            ingredients_saved=all_ingredients,
            meals=all_meals,
            location_code=country,
        )
        impact_month = compute_impact(
            ingredients_saved=month_ingredients,
            meals=meals,
            location_code=country,
        )

        return {
            "month": now.strftime("%B %Y"),
            "meals_created": meals,
            "sustainability_score": score,
            "streak": user.get("streak", 0),
            "points": user.get("points", 0),
            "badges": user.get("badges", []),
            "badge_catalog": BADGES,
            "allergies": user.get("allergies", []),
            "cuisines": user.get("cuisines", []),
            "country": country,
            "locations": list_locations(),
            "impact": impact_all,
            "impact_month": impact_month,
            "all_time": totals,
            "member_since": user.get("created_at").isoformat()[:10] if user.get("created_at") else None,
        }

    def leaderboard(self, limit: int = 10) -> list[dict]:
        rows = []
        for doc in self._users().find().sort("points", -1).limit(limit):
            rows.append(
                {
                    "user_id": doc["user_id"],
                    "points": doc.get("points", 0),
                    "meals": doc.get("totals", {}).get("meals", 0),
                }
            )
        return rows
