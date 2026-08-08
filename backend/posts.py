"""Food posts: photos/videos, captions, tags, likes, comments, bookmarks."""

from __future__ import annotations

import re
import secrets
from pathlib import Path

from datetime import timedelta

from backend.db import get_db, utcnow

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = ROOT / "uploads" / "posts"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_VIDEO_BYTES = 25 * 1024 * 1024
MAX_REEL_BYTES = 40 * 1024 * 1024
ALLOWED_IMAGE = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/jpg", "image/pjpeg"}
ALLOWED_VIDEO = {"video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"}
EXT_FOR_TYPE = {
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
EXT_TO_TYPE = {
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


def _resolve_media_type(content_type: str, filename: str = "") -> tuple[str, str]:
    """Return (media_type, normalized content_type). Raises ValueError if unsupported."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in ALLOWED_IMAGE:
        return "image", EXT_TO_TYPE.get(Path(filename).suffix.lower(), "image/jpeg")
    if ct in ALLOWED_VIDEO:
        return "video", ct if ct in EXT_FOR_TYPE else "video/mp4"

    ext = Path(filename or "").suffix.lower()
    guessed = EXT_TO_TYPE.get(ext)
    if guessed in ALLOWED_IMAGE:
        return "image", guessed
    if guessed and guessed in ALLOWED_VIDEO:
        return "video", guessed

    raise ValueError("Upload a JPG, PNG, WebP, GIF, MP4, or WebM file")


def parse_hashtags(raw: str) -> list[str]:
    if not raw:
        return []
    tags = re.findall(r"#?[\w\u0080-\uFFFF]+", raw.replace(",", " "))
    cleaned = []
    for tag in tags:
        t = tag.lstrip("#").strip().lower()
        if t and t not in cleaned:
            cleaned.append(t)
    return cleaned[:12]


class PostStore:
    def __init__(self) -> None:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def _posts(self):
        return get_db().posts

    def _likes(self):
        return get_db().post_likes

    def _comments(self):
        return get_db().post_comments

    def _comment_likes(self):
        return get_db().comment_likes

    def _bookmarks(self):
        return get_db().post_bookmarks

    def _users(self):
        return get_db().users

    def _follows(self):
        return get_db().user_follows

    def _username(self, user_id: str) -> str:
        doc = self._users().find_one({"user_id": user_id})
        if doc and doc.get("username"):
            return doc["username"]
        return user_id.replace("_", " ")

    def _blocked_author_ids(self, viewer_id: str | None) -> set[str]:
        """Authors whose posts/reels this viewer must not see."""
        restricted = list(
            self._users().find(
                {"$or": [{"is_public": False}, {"is_active": False}]},
                {"user_id": 1, "is_public": 1, "is_active": 1},
            )
        )
        if not restricted:
            return set()
        inactive = {u["user_id"] for u in restricted if not bool(u.get("is_active", True))}
        private = {
            u["user_id"]
            for u in restricted
            if bool(u.get("is_active", True)) and not bool(u.get("is_public", True))
        }
        blocked = set(inactive) | set(private)
        if not viewer_id:
            return blocked
        blocked.discard(viewer_id)
        if private:
            following = {
                f["following_id"]
                for f in self._follows().find(
                    {"follower_id": viewer_id, "following_id": {"$in": list(private)}},
                    {"following_id": 1},
                )
            }
            blocked -= following
        return blocked

    def _with_visibility(self, query: dict | None, viewer_id: str | None) -> dict:
        q = dict(query or {})
        blocked = self._blocked_author_ids(viewer_id)
        if not blocked:
            return q
        existing = q.get("user_id")
        if existing is None:
            q["user_id"] = {"$nin": list(blocked)}
        elif isinstance(existing, str):
            if existing in blocked:
                q["user_id"] = {"$in": []}
        elif isinstance(existing, dict):
            if "$in" in existing:
                allowed = [uid for uid in existing["$in"] if uid not in blocked]
                q["user_id"] = {"$in": allowed}
            elif "$nin" in existing:
                q["user_id"] = {"$nin": list(set(existing["$nin"]) | blocked)}
            else:
                q["user_id"] = {"$nin": list(blocked)}
        return q

    def can_view_author(self, author_id: str, viewer_id: str | None = None) -> bool:
        if not author_id:
            return False
        if viewer_id and viewer_id == author_id:
            return True
        return author_id not in self._blocked_author_ids(viewer_id)

    def create_post(
        self,
        user_id: str,
        caption: str,
        hashtags: list[str],
        recipe_tag: str,
        restaurant_tag: str,
        file_bytes: bytes,
        content_type: str,
        filename: str = "",
        *,
        is_food: bool = True,
        is_reel: bool = False,
    ) -> dict:
        if not file_bytes:
            raise ValueError("Uploaded file is empty")
        media_type, normalized_type = _resolve_media_type(content_type, filename)
        reel = bool(is_reel)
        if reel and media_type != "video":
            raise ValueError("Reels must be a short video (MP4, WebM, or MOV)")
        if media_type == "image":
            if len(file_bytes) > MAX_IMAGE_BYTES:
                raise ValueError("Image must be under 12 MB")
        else:
            limit = MAX_REEL_BYTES if reel else MAX_VIDEO_BYTES
            if len(file_bytes) > limit:
                raise ValueError(
                    "Reel video must be under 40 MB" if reel else "Video must be under 25 MB"
                )

        post_id = f"post_{secrets.token_hex(8)}"
        ext = EXT_FOR_TYPE.get(normalized_type, Path(filename).suffix.lower() or ".jpg")
        filename = f"{post_id}{ext}"
        path = UPLOAD_DIR / filename
        path.write_bytes(file_bytes)

        doc = {
            "post_id": post_id,
            "user_id": user_id,
            "username": self._username(user_id),
            "caption": (caption or "").strip()[:2000],
            "hashtags": hashtags,
            "recipe_tag": (recipe_tag or "").strip()[:120],
            "restaurant_tag": (restaurant_tag or "").strip()[:120],
            "media_type": media_type,
            "media_url": f"/uploads/posts/{filename}",
            "is_food": bool(is_food),
            "is_reel": reel,
            "likes_count": 0,
            "comments_count": 0,
            "created_at": utcnow(),
        }
        self._posts().insert_one(doc)
        return self._serialize(doc, viewer_id=user_id)

    def list_reels(self, viewer_id: str | None, limit: int = 30, skip: int = 0) -> list[dict]:
        query = self._with_visibility({"is_reel": True, "media_type": "video"}, viewer_id)
        # Over-fetch then trim so privacy filtering doesn't leave a short page
        fetch_n = max(limit + skip, limit) * 3
        docs = list(self._posts().find(query).sort("created_at", -1).limit(fetch_n))
        docs = docs[skip : skip + limit]
        return self._serialize_many(docs, viewer_id)

    def list_feed(self, viewer_id: str | None, limit: int = 20, skip: int = 0) -> list[dict]:
        query = self._with_visibility({}, viewer_id)
        fetch_n = max(limit + skip, limit) * 3
        docs = list(self._posts().find(query).sort("created_at", -1).limit(fetch_n))
        docs = docs[skip : skip + limit]
        return self._serialize_many(docs, viewer_id)

    def list_following_feed(self, viewer_id: str, following_ids: list[str], limit: int = 30) -> list[dict]:
        author_ids = list({viewer_id, *following_ids})
        query = self._with_visibility({"user_id": {"$in": author_ids}}, viewer_id)
        cursor = self._posts().find(query).sort("created_at", -1).limit(limit)
        return self._serialize_many(list(cursor), viewer_id)

    def list_trending(self, viewer_id: str | None, limit: int = 30, days: int = 7) -> list[dict]:
        since = utcnow() - timedelta(days=days)
        match = self._with_visibility({"created_at": {"$gte": since}}, viewer_id)
        pipeline = [
            {"$match": match},
            {
                "$addFields": {
                    "trend_score": {
                        "$add": [
                            {"$ifNull": ["$likes_count", 0]},
                            {"$multiply": [{"$ifNull": ["$comments_count", 0]}, 2]},
                        ]
                    }
                }
            },
            {"$sort": {"trend_score": -1, "created_at": -1}},
            {"$limit": limit},
        ]
        return self._serialize_many(list(self._posts().aggregate(pipeline)), viewer_id)

    def get_post_owner(self, post_id: str) -> str | None:
        doc = self._posts().find_one({"post_id": post_id}, {"user_id": 1})
        return doc.get("user_id") if doc else None

    def list_user_posts(self, author_id: str, viewer_id: str | None, limit: int = 30) -> list[dict]:
        if not self.can_view_author(author_id, viewer_id):
            return []
        docs = list(self._posts().find({"user_id": author_id}).sort("created_at", -1).limit(limit))
        return self._serialize_many(docs, viewer_id)

    def get_post(self, post_id: str, viewer_id: str | None = None) -> dict | None:
        doc = self._posts().find_one({"post_id": post_id})
        if not doc:
            return None
        if not self.can_view_author(doc.get("user_id") or "", viewer_id):
            return None
        return self._serialize(doc, viewer_id)

    def toggle_like(self, post_id: str, user_id: str) -> dict:
        post = self._posts().find_one({"post_id": post_id})
        if not post:
            raise ValueError("Post not found")
        if not self.can_view_author(post.get("user_id") or "", user_id):
            raise PermissionError("This post is private")
        existing = self._likes().find_one({"post_id": post_id, "user_id": user_id})
        if existing:
            self._likes().delete_one({"_id": existing["_id"]})
            self._posts().update_one({"post_id": post_id}, {"$inc": {"likes_count": -1}})
            liked = False
        else:
            self._likes().insert_one({"post_id": post_id, "user_id": user_id, "created_at": utcnow()})
            self._posts().update_one({"post_id": post_id}, {"$inc": {"likes_count": 1}})
            liked = True
        updated = self._posts().find_one({"post_id": post_id})
        return {"liked": liked, "likes_count": max(0, int(updated.get("likes_count", 0)))}

    def _serialize_comment(self, doc: dict, viewer_id: str | None = None, *, liked: bool | None = None) -> dict:
        comment_id = doc["comment_id"]
        if liked is None:
            liked = False
            if viewer_id:
                liked = self._comment_likes().find_one({"comment_id": comment_id, "user_id": viewer_id}) is not None
        return {
            "comment_id": comment_id,
            "post_id": doc["post_id"],
            "user_id": doc.get("user_id"),
            "username": doc.get("username", "User"),
            "text": doc.get("text", ""),
            "reply_to_comment_id": doc.get("reply_to_comment_id"),
            "reply_to_username": doc.get("reply_to_username"),
            "reply_to_user_id": doc.get("reply_to_user_id"),
            "likes_count": max(0, int(doc.get("likes_count", 0))),
            "liked": liked,
            "created_at": doc["created_at"].isoformat() if doc.get("created_at") else None,
            "edited_at": doc["edited_at"].isoformat() if doc.get("edited_at") else None,
        }

    def _ensure_mention(self, text: str, username: str) -> str:
        mention = f"@{username}"
        if mention.lower() not in text.lower():
            return f"{mention} {text}".strip()[:500]
        return text[:500]

    def add_comment(
        self,
        post_id: str,
        user_id: str,
        text: str,
        reply_to_comment_id: str | None = None,
    ) -> dict:
        post = self._posts().find_one({"post_id": post_id})
        if not post:
            raise ValueError("Post not found")
        if not self.can_view_author(post.get("user_id") or "", user_id):
            raise PermissionError("This post is private")
        body = (text or "").strip()
        if not body:
            raise ValueError("Comment cannot be empty")
        reply_to_username = None
        reply_to_user_id = None
        if reply_to_comment_id:
            parent = self._comments().find_one({"comment_id": reply_to_comment_id, "post_id": post_id})
            if not parent:
                raise ValueError("Comment to reply to was not found")
            reply_to_username = parent.get("username") or self._username(parent.get("user_id", ""))
            reply_to_user_id = parent.get("user_id")
            body = self._ensure_mention(body, reply_to_username)
        comment_id = f"cmt_{secrets.token_hex(8)}"
        doc = {
            "comment_id": comment_id,
            "post_id": post_id,
            "user_id": user_id,
            "username": self._username(user_id),
            "text": body[:500],
            "reply_to_comment_id": reply_to_comment_id,
            "reply_to_username": reply_to_username,
            "reply_to_user_id": reply_to_user_id,
            "likes_count": 0,
            "created_at": utcnow(),
            "edited_at": None,
        }
        self._comments().insert_one(doc)
        self._posts().update_one({"post_id": post_id}, {"$inc": {"comments_count": 1}})
        updated = self._posts().find_one({"post_id": post_id})
        result = self._serialize_comment(doc)
        result["comments_count"] = max(0, int(updated.get("comments_count", 0))) if updated else 1
        return result

    def list_comments(self, post_id: str, viewer_id: str | None = None, limit: int = 50) -> list[dict]:
        post = self._posts().find_one({"post_id": post_id}, {"user_id": 1})
        if not post:
            return []
        if not self.can_view_author(post.get("user_id") or "", viewer_id):
            return []
        docs = list(self._comments().find({"post_id": post_id}).sort("created_at", 1).limit(limit))
        liked_ids: set[str] = set()
        if viewer_id and docs:
            comment_ids = [d["comment_id"] for d in docs]
            liked_ids = {
                row["comment_id"]
                for row in self._comment_likes().find(
                    {"user_id": viewer_id, "comment_id": {"$in": comment_ids}},
                    {"comment_id": 1},
                )
            }
        return [self._serialize_comment(doc, viewer_id, liked=doc["comment_id"] in liked_ids) for doc in docs]

    def toggle_comment_like(self, post_id: str, comment_id: str, user_id: str) -> dict:
        post = self._posts().find_one({"post_id": post_id}, {"user_id": 1})
        if not post:
            raise ValueError("Post not found")
        if not self.can_view_author(post.get("user_id") or "", user_id):
            raise PermissionError("This post is private")
        comment = self._comments().find_one({"comment_id": comment_id, "post_id": post_id})
        if not comment:
            raise ValueError("Comment not found")
        existing = self._comment_likes().find_one({"comment_id": comment_id, "user_id": user_id})
        if existing:
            self._comment_likes().delete_one({"_id": existing["_id"]})
            self._comments().update_one({"comment_id": comment_id}, {"$inc": {"likes_count": -1}})
            liked = False
        else:
            self._comment_likes().insert_one(
                {
                    "comment_id": comment_id,
                    "post_id": post_id,
                    "user_id": user_id,
                    "created_at": utcnow(),
                }
            )
            self._comments().update_one({"comment_id": comment_id}, {"$inc": {"likes_count": 1}})
            liked = True
        updated = self._comments().find_one({"comment_id": comment_id})
        return {
            "liked": liked,
            "likes_count": max(0, int(updated.get("likes_count", 0))) if updated else 0,
            "comment_author_id": comment.get("user_id"),
        }

    def update_comment(self, post_id: str, comment_id: str, user_id: str, text: str) -> dict:
        post = self._posts().find_one({"post_id": post_id})
        if not post:
            raise ValueError("Post not found")
        comment = self._comments().find_one({"comment_id": comment_id, "post_id": post_id})
        if not comment:
            raise ValueError("Comment not found")
        if comment.get("user_id") != user_id:
            raise PermissionError("You can only edit your own comments")
        body = (text or "").strip()
        if not body:
            raise ValueError("Comment cannot be empty")
        if comment.get("reply_to_username"):
            body = self._ensure_mention(body, comment["reply_to_username"])
        now = utcnow()
        self._comments().update_one(
            {"comment_id": comment_id},
            {"$set": {"text": body[:500], "edited_at": now}},
        )
        updated = self._comments().find_one({"comment_id": comment_id})
        return self._serialize_comment(updated, user_id)

    def delete_comment(
        self,
        post_id: str,
        comment_id: str,
        user_id: str,
        *,
        allow_admin: bool = False,
    ) -> dict:
        post = self._posts().find_one({"post_id": post_id})
        if not post:
            raise ValueError("Post not found")
        comment = self._comments().find_one({"comment_id": comment_id, "post_id": post_id})
        if not comment:
            raise ValueError("Comment not found")
        is_author = comment.get("user_id") == user_id
        is_post_owner = post.get("user_id") == user_id
        if not (is_author or is_post_owner or allow_admin):
            raise PermissionError("You can only delete your own comments")
        self._comments().delete_one({"comment_id": comment_id})
        self._comment_likes().delete_many({"comment_id": comment_id})
        self._posts().update_one({"post_id": post_id}, {"$inc": {"comments_count": -1}})
        updated = self._posts().find_one({"post_id": post_id})
        return {"comments_count": max(0, int(updated.get("comments_count", 0)))}

    def toggle_bookmark(self, post_id: str, user_id: str) -> dict:
        post = self._posts().find_one({"post_id": post_id})
        if not post:
            raise ValueError("Post not found")
        if not self.can_view_author(post.get("user_id") or "", user_id):
            raise PermissionError("This post is private")
        existing = self._bookmarks().find_one({"post_id": post_id, "user_id": user_id})
        if existing:
            self._bookmarks().delete_one({"_id": existing["_id"]})
            return {"bookmarked": False}
        self._bookmarks().insert_one({"post_id": post_id, "user_id": user_id, "saved_at": utcnow()})
        return {"bookmarked": True}

    def list_bookmarks(self, user_id: str, limit: int = 30) -> list[dict]:
        ids = [
            b["post_id"]
            for b in self._bookmarks().find({"user_id": user_id}).sort("saved_at", -1).limit(limit * 2)
        ]
        if not ids:
            return []
        posts = {p["post_id"]: p for p in self._posts().find({"post_id": {"$in": ids}})}
        ordered = [
            posts[pid]
            for pid in ids
            if pid in posts and self.can_view_author(posts[pid].get("user_id") or "", user_id)
        ][:limit]
        return self._serialize_many(ordered, user_id)

    def delete_post(self, post_id: str, user_id: str, *, allow_admin: bool = False) -> None:
        post = self._posts().find_one({"post_id": post_id})
        if not post:
            raise ValueError("Post not found")
        if post.get("user_id") != user_id and not allow_admin:
            raise PermissionError("You can only delete your own posts")
        media_url = post.get("media_url", "")
        if media_url.startswith("/uploads/posts/"):
            filename = media_url.split("/")[-1]
            path = UPLOAD_DIR / filename
            if path.exists():
                path.unlink(missing_ok=True)
        self._posts().delete_one({"post_id": post_id})
        self._likes().delete_many({"post_id": post_id})
        self._comment_likes().delete_many({"post_id": post_id})
        self._comments().delete_many({"post_id": post_id})
        self._bookmarks().delete_many({"post_id": post_id})

    def delete_user_data(self, user_id: str) -> None:
        post_ids = [p["post_id"] for p in self._posts().find({"user_id": user_id}, {"post_id": 1})]
        for post_id in post_ids:
            try:
                self.delete_post(post_id, user_id, allow_admin=True)
            except ValueError:
                pass
        self._likes().delete_many({"user_id": user_id})
        self._comment_likes().delete_many({"user_id": user_id})
        self._comments().delete_many({"user_id": user_id})
        self._bookmarks().delete_many({"user_id": user_id})

    def _viewer_flags(self, post_ids: list[str], viewer_id: str | None) -> tuple[set[str], set[str]]:
        if not viewer_id or not post_ids:
            return set(), set()
        liked = {
            doc["post_id"]
            for doc in self._likes().find({"user_id": viewer_id, "post_id": {"$in": post_ids}}, {"post_id": 1})
        }
        bookmarked = {
            doc["post_id"]
            for doc in self._bookmarks().find({"user_id": viewer_id, "post_id": {"$in": post_ids}}, {"post_id": 1})
        }
        return liked, bookmarked

    def _serialize_many(self, docs: list[dict], viewer_id: str | None) -> list[dict]:
        # Defense in depth: never serialize private/inactive authors to outsiders
        blocked = self._blocked_author_ids(viewer_id)
        docs = [d for d in docs if (d.get("user_id") or "") not in blocked]
        liked_ids, bookmarked_ids = self._viewer_flags([d["post_id"] for d in docs], viewer_id)
        return [
            self._serialize(
                doc,
                viewer_id,
                liked=doc["post_id"] in liked_ids,
                bookmarked=doc["post_id"] in bookmarked_ids,
            )
            for doc in docs
        ]

    def _serialize(
        self,
        doc: dict,
        viewer_id: str | None,
        *,
        liked: bool | None = None,
        bookmarked: bool | None = None,
    ) -> dict:
        post_id = doc["post_id"]
        if liked is None or bookmarked is None:
            liked_ids, bookmarked_ids = self._viewer_flags([post_id], viewer_id)
            liked = post_id in liked_ids
            bookmarked = post_id in bookmarked_ids
        return {
            "post_id": post_id,
            "user_id": doc.get("user_id"),
            "username": doc.get("username", "User"),
            "caption": doc.get("caption", ""),
            "hashtags": doc.get("hashtags") or [],
            "recipe_tag": doc.get("recipe_tag", ""),
            "restaurant_tag": doc.get("restaurant_tag", ""),
            "media_type": doc.get("media_type", "image"),
            "media_url": doc.get("media_url", ""),
            "is_food": doc.get("is_food"),
            "is_reel": bool(doc.get("is_reel")),
            "likes_count": max(0, int(doc.get("likes_count", 0))),
            "comments_count": max(0, int(doc.get("comments_count", 0))),
            "liked": bool(liked),
            "bookmarked": bool(bookmarked),
            "created_at": doc["created_at"].isoformat() if doc.get("created_at") else None,
        }
