"""Google and Facebook identity token verification."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class OAuthError(ValueError):
    pass


def oauth_providers_status() -> dict:
    google_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    facebook_id = os.getenv("FACEBOOK_APP_ID", "").strip()
    facebook_secret = os.getenv("FACEBOOK_APP_SECRET", "").strip()
    return {
        "google": {"enabled": bool(google_id), "client_id": google_id or None},
        "facebook": {
            "enabled": bool(facebook_id and facebook_secret),
            "app_id": facebook_id or None,
        },
    }


def _http_get_json(url: str, timeout: float = 8.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "Petugram/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:200]
        raise OAuthError(f"Provider verification failed ({exc.code}): {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise OAuthError("Could not reach identity provider") from exc
    except json.JSONDecodeError as exc:
        raise OAuthError("Invalid provider response") from exc


def verify_google_id_token(id_token: str) -> dict:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    if not client_id:
        raise OAuthError("Google sign-in is not configured")
    token = (id_token or "").strip()
    if not token:
        raise OAuthError("Missing Google credential")
    data = _http_get_json(
        "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": token})
    )
    aud = str(data.get("aud") or "")
    if aud != client_id:
        raise OAuthError("Google credential audience mismatch")
    if str(data.get("email_verified", "false")).lower() not in {"true", "1"}:
        # Some accounts may omit; require sub at minimum
        if not data.get("sub"):
            raise OAuthError("Google account is incomplete")
    sub = str(data.get("sub") or "").strip()
    if not sub:
        raise OAuthError("Google account id missing")
    return {
        "provider": "google",
        "sub": sub,
        "email": (data.get("email") or "").strip().lower() or None,
        "name": (data.get("name") or data.get("given_name") or "").strip() or None,
        "picture": (data.get("picture") or "").strip() or None,
    }


def verify_facebook_access_token(access_token: str) -> dict:
    app_id = os.getenv("FACEBOOK_APP_ID", "").strip()
    app_secret = os.getenv("FACEBOOK_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise OAuthError("Facebook sign-in is not configured")
    token = (access_token or "").strip()
    if not token:
        raise OAuthError("Missing Facebook credential")

    debug = _http_get_json(
        "https://graph.facebook.com/debug_token?"
        + urllib.parse.urlencode(
            {
                "input_token": token,
                "access_token": f"{app_id}|{app_secret}",
            }
        )
    )
    payload = debug.get("data") or {}
    if not payload.get("is_valid"):
        raise OAuthError("Facebook credential is invalid or expired")
    if str(payload.get("app_id") or "") != app_id:
        raise OAuthError("Facebook credential app mismatch")

    profile = _http_get_json(
        "https://graph.facebook.com/me?"
        + urllib.parse.urlencode(
            {
                "fields": "id,name,email,picture.type(large)",
                "access_token": token,
            }
        )
    )
    sub = str(profile.get("id") or "").strip()
    if not sub:
        raise OAuthError("Facebook account id missing")
    picture = None
    pic = profile.get("picture")
    if isinstance(pic, dict):
        picture = ((pic.get("data") or {}).get("url") or "").strip() or None
    return {
        "provider": "facebook",
        "sub": sub,
        "email": (profile.get("email") or "").strip().lower() or None,
        "name": (profile.get("name") or "").strip() or None,
        "picture": picture,
    }


def verify_oauth_credential(provider: str, credential: str) -> dict:
    kind = (provider or "").strip().lower()
    if kind == "google":
        return verify_google_id_token(credential)
    if kind == "facebook":
        return verify_facebook_access_token(credential)
    raise OAuthError("Unsupported sign-in provider")
