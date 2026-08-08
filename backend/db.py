"""MongoDB connection and collections for Petugram."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from pymongo import MongoClient, ASCENDING
from pymongo.database import Database
from pymongo.collection import Collection

_client: MongoClient | None = None
_db: Database | None = None


def get_db() -> Database:
    global _client, _db
    if _db is not None:
        return _db
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017").strip()
    db_name = os.getenv("MONGODB_DB", "petugram").strip()
    _client = MongoClient(uri, serverSelectionTimeoutMS=4000)
    _client.admin.command("ping")
    _db = _client[db_name]
    _ensure_indexes(_db)
    return _db


def close_db() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


def _ensure_indexes(db: Database) -> None:
    db.users.create_index("user_id", unique=True)
    db.users.create_index("username", unique=True, sparse=True)
    db.pantry.create_index([("user_id", ASCENDING), ("expiry_date", ASCENDING)])
    db.cook_history.create_index([("user_id", ASCENDING), ("cooked_at", ASCENDING)])
    db.favorites.create_index([("user_id", ASCENDING), ("recipe_id", ASCENDING)], unique=True)
    db.meal_plans.create_index("user_id", unique=True)
    db.posts.create_index([("created_at", ASCENDING)])
    db.posts.create_index("post_id", unique=True)
    db.post_likes.create_index([("post_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
    db.comment_likes.create_index([("comment_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
    db.comment_likes.create_index([("post_id", ASCENDING), ("user_id", ASCENDING)])
    db.post_comments.create_index([("post_id", ASCENDING), ("created_at", ASCENDING)])
    db.post_bookmarks.create_index([("post_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
    db.user_follows.create_index([("follower_id", ASCENDING), ("following_id", ASCENDING)], unique=True)
    db.user_follows.create_index([("following_id", ASCENDING), ("created_at", ASCENDING)])
    db.saved_restaurants.create_index([("user_id", ASCENDING), ("restaurant_name", ASCENDING)], unique=True)
    db.saved_restaurants.create_index([("user_id", ASCENDING), ("place_id", ASCENDING)], sparse=True)
    db.posts.create_index([("user_id", ASCENDING), ("created_at", ASCENDING)])
    db.notifications.create_index([("recipient_id", ASCENDING), ("created_at", ASCENDING)])
    db.notifications.create_index([("recipient_id", ASCENDING), ("read", ASCENDING)])
    db.notifications.create_index("notification_id", unique=True)
    db.conversations.create_index("conversation_id", unique=True)
    db.conversations.create_index([("participants", ASCENDING), ("last_message_at", ASCENDING)])
    db.conversations.create_index("pair_key", unique=True, sparse=True)
    db.messages.create_index([("conversation_id", ASCENDING), ("created_at", ASCENDING)])
    db.messages.create_index("message_id", unique=True)
    db.surplus_offers.create_index("offer_id", unique=True)
    db.surplus_offers.create_index([("status", ASCENDING), ("created_at", ASCENDING)])
    db.surplus_offers.create_index([("user_id", ASCENDING), ("created_at", ASCENDING)])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime | None) -> str | None:
    """Serialize datetimes as UTC ISO-8601 with Z so browsers parse timezone correctly."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")
