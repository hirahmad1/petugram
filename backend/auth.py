"""Password hashing and credential validation for Petugram accounts."""

from __future__ import annotations

import hashlib
import re
import secrets

USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,23}$")
RESERVED_USERNAMES = {
    "admin",
    "administrator",
    "root",
    "system",
    "support",
    "petugram",
    "null",
    "undefined",
    "api",
    "help",
    "mod",
    "moderator",
}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return secrets.compare_digest(digest, check.hex())


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def validate_username(username: str) -> str:
    cleaned = normalize_username(username)
    if len(cleaned) < 3:
        raise ValueError("Username must be at least 3 characters")
    if len(cleaned) > 24:
        raise ValueError("Username must be at most 24 characters")
    if not USERNAME_RE.match(cleaned):
        raise ValueError("Username must start with a letter and use only letters, numbers, and underscores")
    if cleaned in RESERVED_USERNAMES:
        raise ValueError("That username is reserved")
    return cleaned


def validate_password(password: str, *, strict: bool = True) -> str:
    value = password or ""
    if "\x00" in value:
        raise ValueError("Password contains invalid characters")
    if len(value) < (8 if strict else 6):
        raise ValueError("Password must be at least 8 characters" if strict else "Password must be at least 6 characters")
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters")
    if strict:
        if value.strip() != value:
            raise ValueError("Password cannot start or end with spaces")
        if not re.search(r"[A-Za-z]", value):
            raise ValueError("Password must include at least one letter")
        if not re.search(r"\d", value):
            raise ValueError("Password must include at least one number")
        if value.lower() in {"password", "password1", "12345678", "qwerty123"}:
            raise ValueError("Choose a stronger password")
    return value


def suggest_username_from_identity(name: str | None, email: str | None, fallback: str) -> str:
    base = ""
    if email and "@" in email:
        base = email.split("@", 1)[0]
    elif name:
        base = name
    else:
        base = fallback
    base = re.sub(r"[^a-z0-9_]+", "", (base or "").lower())
    if not base:
        base = "chef"
    if base[0].isdigit():
        base = f"u{base}"
    base = base[:20] or "chef"
    if not USERNAME_RE.match(base):
        base = (base + "user")[:24]
        if not USERNAME_RE.match(base):
            base = "chef"
    return base
