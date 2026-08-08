"""In-app notifications for likes, comments, and follows."""

from __future__ import annotations

import secrets

from backend.db import get_db, utcnow


class NotificationStore:
    TYPES = {"like", "comment", "follow", "reply", "comment_like", "message", "surplus_claim"}

    def _col(self):
        return get_db().notifications

    def _users(self):
        return get_db().users

    def _actor_name(self, user_id: str) -> str:
        doc = self._users().find_one({"user_id": user_id})
        if doc and doc.get("username"):
            return doc["username"]
        return user_id.replace("_", " ")

    def create(
        self,
        recipient_id: str,
        actor_id: str,
        kind: str,
        *,
        post_id: str | None = None,
        preview: str = "",
    ) -> dict | None:
        if recipient_id == actor_id:
            return None
        if kind not in self.TYPES:
            return None
        actor_name = self._actor_name(actor_id)
        if kind == "like":
            message = f"{actor_name} liked your post"
        elif kind == "comment":
            snippet = (preview or "").strip()[:80]
            message = f"{actor_name} commented: {snippet}" if snippet else f"{actor_name} commented on your post"
        elif kind == "reply":
            snippet = (preview or "").strip()[:80]
            message = f"{actor_name} replied: {snippet}" if snippet else f"{actor_name} replied to your comment"
        elif kind == "comment_like":
            message = f"{actor_name} liked your comment"
        elif kind == "message":
            snippet = (preview or "").strip()[:80]
            message = f"{actor_name}: {snippet}" if snippet else f"New message from {actor_name}"
        elif kind == "surplus_claim":
            snippet = (preview or "").strip()[:80]
            message = (
                f"{actor_name} {snippet}"
                if snippet
                else f"{actor_name} claimed your surplus food"
            )
        else:
            message = f"{actor_name} started following you"
        doc = {
            "notification_id": f"ntf_{secrets.token_hex(8)}",
            "recipient_id": recipient_id,
            "actor_id": actor_id,
            "actor_name": actor_name,
            "type": kind,
            "post_id": post_id,
            "message": message,
            "read": False,
            "created_at": utcnow(),
        }
        self._col().insert_one(doc)
        return self._serialize(doc)

    def list_for_user(self, user_id: str, limit: int = 30, unread_only: bool = False) -> list[dict]:
        query: dict = {"recipient_id": user_id}
        if unread_only:
            query["read"] = False
        out = []
        for doc in self._col().find(query).sort("created_at", -1).limit(limit):
            out.append(self._serialize(doc))
        return out

    def unread_count(self, user_id: str) -> int:
        return self._col().count_documents({"recipient_id": user_id, "read": False})

    def mark_read(self, user_id: str, notification_id: str) -> bool:
        result = self._col().update_one(
            {"notification_id": notification_id, "recipient_id": user_id},
            {"$set": {"read": True}},
        )
        return result.matched_count > 0

    def mark_all_read(self, user_id: str) -> int:
        result = self._col().update_many(
            {"recipient_id": user_id, "read": False},
            {"$set": {"read": True}},
        )
        return result.modified_count

    def delete_user_data(self, user_id: str) -> None:
        self._col().delete_many({"$or": [{"recipient_id": user_id}, {"actor_id": user_id}]})

    def _serialize(self, doc: dict) -> dict:
        return {
            "notification_id": doc["notification_id"],
            "recipient_id": doc.get("recipient_id"),
            "actor_id": doc.get("actor_id"),
            "actor_name": doc.get("actor_name", "User"),
            "type": doc.get("type"),
            "post_id": doc.get("post_id"),
            "message": doc.get("message", ""),
            "read": bool(doc.get("read")),
            "created_at": doc["created_at"].isoformat() if doc.get("created_at") else None,
        }
