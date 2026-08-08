"""Profile avatars."""

from __future__ import annotations

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AVATAR_DIR = ROOT / "uploads" / "avatars"
MAX_AVATAR_BYTES = 4 * 1024 * 1024
ALLOWED = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/jpg", "image/pjpeg"}
EXT_FOR = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
EXT_TO = {v: k for k, v in EXT_FOR.items() if k not in {"image/jpg", "image/pjpeg"}}


def save_avatar(user_id: str, file_bytes: bytes, content_type: str, filename: str = "") -> str:
    if not file_bytes:
        raise ValueError("Uploaded file is empty")
    if len(file_bytes) > MAX_AVATAR_BYTES:
        raise ValueError("Profile picture must be under 4 MB")
    ct = (content_type or "").split(";")[0].strip().lower()
    ext = EXT_FOR.get(ct)
    if not ext:
        ext = Path(filename or "").suffix.lower()
        ct = EXT_TO.get(ext, "")
    if ct not in ALLOWED and ext not in EXT_TO:
        raise ValueError("Upload a JPG, PNG, WebP, or GIF image")
    ext = ext or EXT_FOR.get(ct, ".jpg")
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    for old in AVATAR_DIR.glob(f"{user_id}.*"):
        old.unlink(missing_ok=True)
    name = f"{user_id}{ext}"
    (AVATAR_DIR / name).write_bytes(file_bytes)
    return f"/uploads/avatars/{name}"


def delete_avatar_file(avatar_url: str | None) -> None:
    if not avatar_url or not avatar_url.startswith("/uploads/avatars/"):
        return
    path = ROOT / avatar_url.lstrip("/")
    if path.exists():
        path.unlink(missing_ok=True)
