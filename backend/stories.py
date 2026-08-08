"""24-hour user stories shown on profile pictures."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.db import get_db, to_iso, utcnow

ROOT = Path(__file__).resolve().parent.parent
STORY_DIR = ROOT / "uploads" / "stories"
MAX_STORY_IMAGE_BYTES = 8 * 1024 * 1024
MAX_STORY_VIDEO_BYTES = 25 * 1024 * 1024
STORY_TTL = timedelta(hours=24)

ALLOWED_IMAGE = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/jpg",
    "image/pjpeg",
}
ALLOWED_VIDEO = {"video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"}
ALLOWED = ALLOWED_IMAGE | ALLOWED_VIDEO
EXT_FOR = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
}
EXT_TO = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
}


def _as_utc(dt: datetime | None) -> datetime | None:
    """Mongo returns naive UTC datetimes; normalize before comparing to utcnow()."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _media_kind(content_type: str, ext: str) -> str:
    if content_type in ALLOWED_VIDEO or ext in {".mp4", ".webm", ".mov", ".avi"}:
        return "video"
    return "image"


class StoryStore:
    def _stories(self):
        return get_db().stories

    def _users(self):
        return get_db().users

    def _follows(self):
        return get_db().user_follows

    def _purge_expired(self, user_id: str | None = None) -> None:
        now = utcnow()
        query: dict = {"expires_at": {"$lte": now}}
        if user_id:
            query["user_id"] = user_id
        for doc in self._stories().find(query, {"media_url": 1}):
            self._unlink(doc.get("media_url"))
        self._stories().delete_many(query)

    def _unlink(self, media_url: str | None) -> None:
        if not media_url or not str(media_url).startswith("/uploads/stories/"):
            return
        path = ROOT / str(media_url).lstrip("/")
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass

    def _user_brief(self, user_id: str) -> dict:
        doc = self._users().find_one({"user_id": user_id}) or {}
        raw = (doc.get("username") or user_id or "User").strip()
        return {
            "user_id": user_id,
            "username": doc.get("username") or raw,
            "avatar_url": doc.get("avatar_url"),
        }

    def _other_viewers(self, doc: dict) -> list[str]:
        owner = doc.get("user_id")
        return [vid for vid in (doc.get("viewers") or []) if vid and vid != owner]

    def _serialize(self, doc: dict, viewer_id: str | None = None) -> dict:
        viewers = list(doc.get("viewers") or [])
        other = self._other_viewers(doc)
        mine = bool(viewer_id and viewer_id == doc.get("user_id"))
        return {
            "story_id": doc["story_id"],
            "user_id": doc["user_id"],
            "media_url": doc.get("media_url"),
            "media_type": doc.get("media_type") or "image",
            "caption": doc.get("caption") or "",
            "created_at": to_iso(doc.get("created_at")),
            "expires_at": to_iso(doc.get("expires_at")),
            "view_count": len(other) if mine else 0,
            "seen": bool(viewer_id and viewer_id in viewers),
            "mine": mine,
        }

    def list_viewers(self, story_id: str, owner_id: str) -> dict:
        doc = self._stories().find_one({"story_id": story_id})
        if not doc:
            raise ValueError("Story not found")
        if doc.get("user_id") != owner_id:
            raise PermissionError("Only the story owner can see viewers")
        expires = _as_utc(doc.get("expires_at"))
        if expires and expires <= utcnow():
            self._purge_expired(owner_id)
            raise ValueError("Story expired")
        viewer_ids = self._other_viewers(doc)
        # newest viewers first (append order)
        viewer_ids = list(reversed(viewer_ids))
        users = []
        for vid in viewer_ids:
            brief = self._user_brief(vid)
            if brief.get("username"):
                users.append(brief)
        return {
            "story_id": story_id,
            "view_count": len(users),
            "viewers": users,
        }

    def has_active_story(self, user_id: str) -> bool:
        self._purge_expired(user_id)
        return (
            self._stories().count_documents(
                {"user_id": user_id, "expires_at": {"$gt": utcnow()}},
                limit=1,
            )
            > 0
        )

    def story_seen_by(self, user_id: str, viewer_id: str | None) -> bool:
        if not viewer_id:
            return False
        self._purge_expired(user_id)
        docs = list(
            self._stories().find(
                {"user_id": user_id, "expires_at": {"$gt": utcnow()}},
                {"viewers": 1},
            )
        )
        if not docs:
            return False
        return all(viewer_id in (d.get("viewers") or []) for d in docs)

    def create_story(
        self,
        user_id: str,
        *,
        file_bytes: bytes,
        content_type: str,
        filename: str = "",
        caption: str = "",
    ) -> dict:
        if not file_bytes:
            raise ValueError("Uploaded file is empty")
        ct = (content_type or "").split(";")[0].strip().lower()
        ext = EXT_FOR.get(ct)
        if not ext:
            ext = Path(filename or "").suffix.lower()
            ct = EXT_TO.get(ext, ct)
        if ct not in ALLOWED and ext not in EXT_TO:
            raise ValueError("Upload a photo (JPG, PNG, WebP, GIF) or video (MP4, WebM, MOV)")
        if not ext:
            ext = EXT_FOR.get(ct, ".jpg")
        if not ct:
            ct = EXT_TO.get(ext, "image/jpeg")
        kind = _media_kind(ct, ext)
        max_bytes = MAX_STORY_VIDEO_BYTES if kind == "video" else MAX_STORY_IMAGE_BYTES
        if len(file_bytes) > max_bytes:
            limit_mb = 25 if kind == "video" else 8
            raise ValueError(f"Story {kind} must be under {limit_mb} MB")

        self._purge_expired(user_id)
        STORY_DIR.mkdir(parents=True, exist_ok=True)
        story_id = f"story_{secrets.token_hex(8)}"
        stored = f"{story_id}{ext}"
        (STORY_DIR / stored).write_bytes(file_bytes)
        now = utcnow()
        doc = {
            "story_id": story_id,
            "user_id": user_id,
            "media_url": f"/uploads/stories/{stored}",
            "media_type": kind,
            "caption": (caption or "").strip()[:200],
            "created_at": now,
            "expires_at": now + STORY_TTL,
            "viewers": [user_id],
        }
        self._stories().insert_one(doc)
        return self._serialize(doc, user_id)

    def list_user_stories(self, user_id: str, viewer_id: str | None = None) -> list[dict]:
        self._purge_expired(user_id)
        # Hide inactive accounts from everyone except the owner
        owner = self._users().find_one({"user_id": user_id}, {"is_active": 1, "is_public": 1}) or {}
        if viewer_id != user_id:
            if not bool(owner.get("is_active", True)):
                return []
            if not bool(owner.get("is_public", True)):
                following = self._follows().find_one(
                    {"follower_id": viewer_id or "", "following_id": user_id}
                )
                if not following:
                    return []
        docs = list(
            self._stories()
            .find({"user_id": user_id, "expires_at": {"$gt": utcnow()}})
            .sort("created_at", 1)
        )
        return [self._serialize(d, viewer_id) for d in docs]

    def get_story_owner(self, story_id: str) -> str | None:
        doc = self._stories().find_one({"story_id": story_id}, {"user_id": 1})
        return doc.get("user_id") if doc else None

    def mark_viewed(self, story_id: str, viewer_id: str) -> dict:
        doc = self._stories().find_one({"story_id": story_id})
        if not doc:
            raise ValueError("Story not found")
        expires = _as_utc(doc.get("expires_at"))
        if expires and expires <= utcnow():
            self._purge_expired(doc.get("user_id"))
            raise ValueError("Story expired")
        viewers = list(doc.get("viewers") or [])
        if viewer_id not in viewers:
            viewers.append(viewer_id)
            self._stories().update_one({"story_id": story_id}, {"$set": {"viewers": viewers}})
            doc["viewers"] = viewers
        return self._serialize(doc, viewer_id)

    def delete_story(self, story_id: str, user_id: str) -> None:
        doc = self._stories().find_one({"story_id": story_id, "user_id": user_id})
        if not doc:
            raise ValueError("Story not found")
        self._unlink(doc.get("media_url"))
        self._stories().delete_one({"story_id": story_id})

    def feed_for(self, viewer_id: str, limit: int = 40) -> list[dict]:
        self._purge_expired()
        following = {
            f["following_id"]
            for f in self._follows().find({"follower_id": viewer_id}, {"following_id": 1})
        }
        following.add(viewer_id)
        now = utcnow()
        pipeline = [
            {"$match": {"user_id": {"$in": list(following)}, "expires_at": {"$gt": now}}},
            {"$sort": {"created_at": -1}},
            {
                "$group": {
                    "_id": "$user_id",
                    "latest": {"$first": "$created_at"},
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"latest": -1}},
            {"$limit": limit},
        ]
        rows = []
        for g in self._stories().aggregate(pipeline):
            uid = g["_id"]
            stories = self.list_user_stories(uid, viewer_id)
            if not stories:
                continue
            brief = self._user_brief(uid)
            rows.append(
                {
                    **brief,
                    "story_count": len(stories),
                    "has_unseen": any(not s.get("seen") for s in stories),
                    "stories": stories,
                }
            )
        return rows

    def delete_user_data(self, user_id: str) -> None:
        for doc in self._stories().find({"user_id": user_id}, {"media_url": 1}):
            self._unlink(doc.get("media_url"))
        self._stories().delete_many({"user_id": user_id})
