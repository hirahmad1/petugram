"""Direct messaging between users, including media attachments."""

from __future__ import annotations

import secrets
from pathlib import Path

from backend.db import get_db, to_iso, utcnow

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = ROOT / "uploads" / "messages"

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_VIDEO_BYTES = 25 * 1024 * 1024
MAX_VOICE_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024

ALLOWED_IMAGE = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/jpg", "image/pjpeg"}
ALLOWED_VIDEO = {"video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"}
ALLOWED_VOICE = {
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
    "audio/mp3",
    "audio/aac",
}
ALLOWED_DOCUMENT = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/csv",
    "application/zip",
    "application/x-zip-compressed",
}

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
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/aac": ".aac",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
}

EXT_TO_KIND = {
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".png": ("image", "image/png"),
    ".webp": ("image", "image/webp"),
    ".gif": ("image", "image/gif"),
    ".mp4": ("video", "video/mp4"),
    ".webm": ("video", "video/webm"),
    ".mov": ("video", "video/quicktime"),
    ".avi": ("video", "video/x-msvideo"),
    ".ogg": ("voice", "audio/ogg"),
    ".mp3": ("voice", "audio/mpeg"),
    ".m4a": ("voice", "audio/mp4"),
    ".wav": ("voice", "audio/wav"),
    ".aac": ("voice", "audio/aac"),
    ".pdf": ("document", "application/pdf"),
    ".doc": ("document", "application/msword"),
    ".docx": ("document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".xls": ("document", "application/vnd.ms-excel"),
    ".xlsx": ("document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".ppt": ("document", "application/vnd.ms-powerpoint"),
    ".pptx": ("document", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ".txt": ("document", "text/plain"),
    ".csv": ("document", "text/csv"),
    ".zip": ("document", "application/zip"),
}

PREVIEW_LABELS = {
    "image": "Photo",
    "video": "Video",
    "voice": "Voice message",
    "document": "Document",
}


def resolve_attachment_kind(content_type: str, filename: str = "", preferred: str | None = None) -> tuple[str, str]:
    """Return (kind, normalized_content_type). kind in image|video|voice|document."""
    ct = (content_type or "").split(";")[0].strip().lower()
    ext = Path(filename or "").suffix.lower()

    if preferred == "voice" or ct in ALLOWED_VOICE or (ext in {".webm", ".ogg", ".mp3", ".m4a", ".wav", ".aac"} and preferred == "voice"):
        if ct in ALLOWED_VOICE:
            return "voice", ct
        if ext == ".webm":
            return "voice", "audio/webm"
        guessed = EXT_TO_KIND.get(ext)
        if guessed and guessed[0] == "voice":
            return guessed
        if preferred == "voice":
            return "voice", ct or "audio/webm"

    if ct in ALLOWED_IMAGE:
        return "image", "image/jpeg" if ct in {"image/jpg", "image/pjpeg"} else ct
    if ct in ALLOWED_VIDEO:
        return "video", ct
    if ct in ALLOWED_VOICE:
        return "voice", ct
    if ct in ALLOWED_DOCUMENT:
        return "document", ct

    guessed = EXT_TO_KIND.get(ext)
    if guessed:
        return guessed

    raise ValueError("Unsupported file. Use image, video, audio, or a common document type.")


def max_bytes_for_kind(kind: str) -> int:
    return {
        "image": MAX_IMAGE_BYTES,
        "video": MAX_VIDEO_BYTES,
        "voice": MAX_VOICE_BYTES,
        "document": MAX_DOCUMENT_BYTES,
    }.get(kind, MAX_DOCUMENT_BYTES)


class MessageStore:
    def __init__(self) -> None:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def _conversations(self):
        return get_db().conversations

    def _messages(self):
        return get_db().messages

    def _users(self):
        return get_db().users

    def _pair_key(self, a: str, b: str) -> str:
        return "|".join(sorted([a, b]))

    def _user_brief(self, user_id: str) -> dict:
        doc = self._users().find_one({"user_id": user_id}) or {}
        raw_name = (doc.get("username") or "").strip()
        if not raw_name:
            raw_name = str(user_id or "User").replace("_", " ").strip() or "User"
        custom = (doc.get("display_name") or "").strip()
        if custom:
            display = custom[:80]
        elif " " in raw_name or len(raw_name) > 3:
            display = " ".join(part[:1].upper() + part[1:] for part in raw_name.split() if part)
        else:
            display = raw_name
        return {
            "user_id": user_id,
            "username": raw_name,
            "display_name": display or "User",
            "avatar_url": doc.get("avatar_url"),
        }

    def get_or_create_direct(self, user_id: str, other_user_id: str) -> dict:
        if user_id == other_user_id:
            raise ValueError("Cannot message yourself")
        other = self._users().find_one({"user_id": other_user_id, "username": {"$ne": None}})
        if not other:
            raise ValueError("User not found")
        pair = self._pair_key(user_id, other_user_id)
        conv = self._conversations().find_one({"type": "direct", "pair_key": pair})
        if not conv:
            now = utcnow()
            conv = {
                "conversation_id": f"conv_{secrets.token_hex(8)}",
                "type": "direct",
                "pair_key": pair,
                "participants": sorted([user_id, other_user_id]),
                "last_message_at": now,
                "last_message_preview": "",
                "unread": {user_id: 0, other_user_id: 0},
                "created_at": now,
            }
            self._conversations().insert_one(conv)
        return self._serialize_conversation(conv, user_id)

    def list_conversations(self, user_id: str) -> list[dict]:
        rows = []
        for conv in self._conversations().find({"participants": user_id}).sort("last_message_at", -1):
            rows.append(self._serialize_conversation(conv, user_id))
        return rows

    def _require_member(self, conversation_id: str, user_id: str) -> dict:
        conv = self._conversations().find_one({"conversation_id": conversation_id})
        if not conv or user_id not in conv.get("participants", []):
            raise ValueError("Conversation not found")
        return conv

    def _serialize_conversation(self, conv: dict, viewer_id: str) -> dict:
        other_id = next((p for p in conv.get("participants", []) if p != viewer_id), None)
        other = self._user_brief(other_id) if other_id else {
            "user_id": "",
            "username": "Chat",
            "display_name": "Chat",
            "avatar_url": None,
        }
        unread_map = conv.get("unread") or {}
        return {
            "conversation_id": conv["conversation_id"],
            "type": conv.get("type", "direct"),
            "other_user": other,
            "last_message_at": to_iso(conv.get("last_message_at")),
            "last_message_preview": conv.get("last_message_preview", ""),
            "unread_count": int(unread_map.get(viewer_id, 0) or 0),
        }

    def _preview_for(self, text: str, media_type: str, file_name: str = "") -> str:
        body = (text or "").strip()
        if body.startswith("::petugram-sticker:") and body.endswith("::"):
            inner = body[len("::petugram-sticker:") : -2]
            parts = inner.split(":")
            # pack:id:emoji  OR legacy emoji-only
            emoji = parts[-1].strip() if parts else ""
            return f"Sticker {emoji}" if emoji else "Sticker"
        if media_type and media_type != "text":
            label = PREVIEW_LABELS.get(media_type, "Attachment")
            if media_type == "document" and file_name:
                label = file_name[:80]
            return f"{label}" + (f" · {body[:80]}" if body else "")
        return body[:120]

    def _touch_conversation(self, conv: dict, sender_id: str, preview: str, now) -> None:
        unread = dict(conv.get("unread") or {})
        for pid in conv.get("participants", []):
            if pid == sender_id:
                unread[pid] = 0
            else:
                unread[pid] = int(unread.get(pid, 0) or 0) + 1
        self._conversations().update_one(
            {"conversation_id": conv["conversation_id"]},
            {"$set": {"last_message_at": now, "last_message_preview": preview, "unread": unread}},
        )

    def send_message(self, conversation_id: str, sender_id: str, text: str) -> dict:
        return self.send_attachment_message(
            conversation_id,
            sender_id,
            text=text,
            media_type="text",
        )

    def send_attachment_message(
        self,
        conversation_id: str,
        sender_id: str,
        *,
        text: str = "",
        media_type: str = "text",
        media_url: str | None = None,
        file_name: str | None = None,
        file_size: int | None = None,
        content_type: str | None = None,
    ) -> dict:
        conv = self._require_member(conversation_id, sender_id)
        body = (text or "").strip()
        kind = media_type or "text"
        if kind == "text" and not body:
            raise ValueError("Message cannot be empty")
        if kind != "text" and not media_url:
            raise ValueError("Attachment missing")
        now = utcnow()
        message_id = f"msg_{secrets.token_hex(8)}"
        doc = {
            "message_id": message_id,
            "conversation_id": conversation_id,
            "sender_id": sender_id,
            "text": body[:2000],
            "media_type": kind,
            "media_url": media_url,
            "file_name": (file_name or "")[:180] or None,
            "file_size": int(file_size or 0) or None,
            "content_type": content_type,
            "created_at": now,
            "read_by": [sender_id],
            "reactions": {},
        }
        self._messages().insert_one(doc)
        preview = self._preview_for(body, kind, file_name or "")
        self._touch_conversation(conv, sender_id, preview, now)
        return self._serialize_message(doc, sender_id)

    def save_and_send_attachment(
        self,
        conversation_id: str,
        sender_id: str,
        *,
        file_bytes: bytes,
        content_type: str,
        filename: str,
        text: str = "",
        preferred_kind: str | None = None,
    ) -> dict:
        if not file_bytes:
            raise ValueError("Empty file")
        kind, normalized_ct = resolve_attachment_kind(content_type, filename, preferred_kind)
        limit = max_bytes_for_kind(kind)
        if len(file_bytes) > limit:
            mb = limit // (1024 * 1024)
            raise ValueError(f"{PREVIEW_LABELS.get(kind, 'File')} must be under {mb} MB")

        ext = EXT_FOR_TYPE.get(normalized_ct) or Path(filename or "").suffix.lower() or ".bin"
        if kind == "voice" and ext == ".webm" and "video" in (content_type or ""):
            # MediaRecorder often reports video/webm for audio-only blobs
            normalized_ct = "audio/webm"
        safe_name = Path(filename or f"file{ext}").name[:120]
        message_id = f"msg_{secrets.token_hex(8)}"
        stored = f"{message_id}{ext}"
        path = UPLOAD_DIR / stored
        path.write_bytes(file_bytes)
        media_url = f"/uploads/messages/{stored}"

        # Insert with predetermined message_id by temporarily using send then update — cleaner to insert directly
        conv = self._require_member(conversation_id, sender_id)
        body = (text or "").strip()
        now = utcnow()
        doc = {
            "message_id": message_id,
            "conversation_id": conversation_id,
            "sender_id": sender_id,
            "text": body[:2000],
            "media_type": kind,
            "media_url": media_url,
            "file_name": safe_name,
            "file_size": len(file_bytes),
            "content_type": normalized_ct,
            "created_at": now,
            "read_by": [sender_id],
            "reactions": {},
        }
        self._messages().insert_one(doc)
        preview = self._preview_for(body, kind, safe_name)
        self._touch_conversation(conv, sender_id, preview, now)
        return self._serialize_message(doc, sender_id)

    def list_messages(self, conversation_id: str, user_id: str, limit: int = 80) -> list[dict]:
        self._require_member(conversation_id, user_id)
        docs = list(
            self._messages()
            .find({"conversation_id": conversation_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        docs.reverse()
        return [self._serialize_message(doc, user_id) for doc in docs]

    def _serialize_reactions(self, reactions: dict | None, viewer_id: str) -> list[dict]:
        rows = []
        for emoji, users in (reactions or {}).items():
            user_ids = [u for u in (users or []) if u]
            if not user_ids:
                continue
            rows.append(
                {
                    "emoji": emoji,
                    "count": len(user_ids),
                    "reacted": viewer_id in user_ids,
                    "user_ids": user_ids[:20],
                }
            )
        rows.sort(key=lambda r: (-r["count"], r["emoji"]))
        return rows

    def toggle_reaction(self, conversation_id: str, message_id: str, user_id: str, emoji: str) -> dict:
        self._require_member(conversation_id, user_id)
        mark = (emoji or "").strip()
        if not mark or len(mark) > 16:
            raise ValueError("Invalid reaction")
        doc = self._messages().find_one({"message_id": message_id, "conversation_id": conversation_id})
        if not doc:
            raise ValueError("Message not found")
        reactions = dict(doc.get("reactions") or {})
        users = list(reactions.get(mark) or [])
        if user_id in users:
            users = [u for u in users if u != user_id]
            if users:
                reactions[mark] = users
            else:
                reactions.pop(mark, None)
            action = "removed"
        else:
            # One reaction type per user: remove from other emojis first
            cleaned = {}
            for key, vals in reactions.items():
                kept = [u for u in (vals or []) if u != user_id]
                if kept:
                    cleaned[key] = kept
            reactions = cleaned
            reactions[mark] = list(reactions.get(mark) or []) + [user_id]
            action = "added"
        self._messages().update_one({"message_id": message_id}, {"$set": {"reactions": reactions}})
        doc["reactions"] = reactions
        return {
            "ok": True,
            "action": action,
            "message": self._serialize_message(doc, user_id),
        }

    def _serialize_message(self, doc: dict, viewer_id: str) -> dict:
        media_type = doc.get("media_type") or ("text" if not doc.get("media_url") else "document")
        return {
            "message_id": doc["message_id"],
            "conversation_id": doc["conversation_id"],
            "sender_id": doc["sender_id"],
            "text": doc.get("text", ""),
            "media_type": media_type,
            "media_url": doc.get("media_url"),
            "file_name": doc.get("file_name"),
            "file_size": doc.get("file_size"),
            "content_type": doc.get("content_type"),
            "mine": doc["sender_id"] == viewer_id,
            "created_at": to_iso(doc.get("created_at")),
            "reactions": self._serialize_reactions(doc.get("reactions"), viewer_id),
        }

    def mark_read(self, conversation_id: str, user_id: str) -> None:
        self._require_member(conversation_id, user_id)
        self._conversations().update_one(
            {"conversation_id": conversation_id},
            {"$set": {f"unread.{user_id}": 0}},
        )
        for doc in self._messages().find({"conversation_id": conversation_id, "sender_id": {"$ne": user_id}}):
            read_by = list(doc.get("read_by") or [])
            if user_id not in read_by:
                read_by.append(user_id)
                self._messages().update_one({"message_id": doc["message_id"]}, {"$set": {"read_by": read_by}})

    def _unlink_media(self, media_url: str | None) -> None:
        if not media_url or not str(media_url).startswith("/uploads/messages/"):
            return
        path = ROOT / str(media_url).lstrip("/")
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass

    def _preview_from_doc(self, doc: dict | None) -> str:
        if not doc:
            return ""
        return self._preview_for(doc.get("text", ""), doc.get("media_type") or "text", doc.get("file_name") or "")

    def _refresh_conversation_preview(self, conversation_id: str) -> None:
        last = self._messages().find_one({"conversation_id": conversation_id}, sort=[("created_at", -1)])
        if last:
            self._conversations().update_one(
                {"conversation_id": conversation_id},
                {
                    "$set": {
                        "last_message_at": last.get("created_at"),
                        "last_message_preview": self._preview_from_doc(last),
                    }
                },
            )
        else:
            conv = self._conversations().find_one({"conversation_id": conversation_id}) or {}
            unread = {pid: 0 for pid in conv.get("participants", [])}
            self._conversations().update_one(
                {"conversation_id": conversation_id},
                {"$set": {"last_message_preview": "", "unread": unread}},
            )

    def delete_message(self, conversation_id: str, message_id: str, user_id: str) -> None:
        self._require_member(conversation_id, user_id)
        doc = self._messages().find_one({"message_id": message_id, "conversation_id": conversation_id})
        if not doc:
            raise ValueError("Message not found")
        if doc.get("sender_id") != user_id:
            raise ValueError("You can only delete your own messages")
        self._unlink_media(doc.get("media_url"))
        self._messages().delete_one({"message_id": message_id})
        self._refresh_conversation_preview(conversation_id)

    def delete_conversation(self, conversation_id: str, user_id: str) -> None:
        self._require_member(conversation_id, user_id)
        for doc in self._messages().find({"conversation_id": conversation_id}, {"media_url": 1}):
            self._unlink_media(doc.get("media_url"))
        self._messages().delete_many({"conversation_id": conversation_id})
        self._conversations().delete_one({"conversation_id": conversation_id})

    def total_unread(self, user_id: str) -> int:
        total = 0
        for conv in self._conversations().find({"participants": user_id}, {"unread": 1}):
            total += int((conv.get("unread") or {}).get(user_id, 0) or 0)
        return total

    def delete_user_data(self, user_id: str) -> None:
        conv_ids = [c["conversation_id"] for c in self._conversations().find({"participants": user_id}, {"conversation_id": 1})]
        if not conv_ids:
            return
        for doc in self._messages().find({"conversation_id": {"$in": conv_ids}}, {"media_url": 1}):
            self._unlink_media(doc.get("media_url"))
        self._messages().delete_many({"conversation_id": {"$in": conv_ids}})
        self._conversations().delete_many({"conversation_id": {"$in": conv_ids}})
