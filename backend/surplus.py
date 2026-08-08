"""Local surplus food donation / sharing offers."""

from __future__ import annotations

import math
import secrets
from datetime import datetime, timezone

from backend.db import get_db, to_iso, utcnow


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


class SurplusStore:
    def _offers(self):
        return get_db().surplus_offers

    def _users(self):
        return get_db().users

    def _user_brief(self, user_id: str) -> dict:
        doc = self._users().find_one({"user_id": user_id}) or {}
        return {
            "user_id": user_id,
            "username": doc.get("username") or user_id,
            "display_name": (doc.get("display_name") or "").strip()
            or doc.get("username")
            or "Neighbor",
            "avatar_url": doc.get("avatar_url"),
        }

    def _serialize(self, doc: dict, *, viewer_lat: float | None = None, viewer_lng: float | None = None) -> dict:
        lat = doc.get("lat")
        lng = doc.get("lng")
        distance_km = None
        if (
            viewer_lat is not None
            and viewer_lng is not None
            and isinstance(lat, (int, float))
            and isinstance(lng, (int, float))
        ):
            distance_km = round(_haversine_km(viewer_lat, viewer_lng, float(lat), float(lng)), 2)
        owner = self._user_brief(doc.get("user_id") or "")
        return {
            "offer_id": doc.get("offer_id"),
            "user_id": doc.get("user_id"),
            "username": owner.get("username"),
            "display_name": owner.get("display_name"),
            "avatar_url": owner.get("avatar_url"),
            "title": doc.get("title") or doc.get("ingredient") or "Surplus food",
            "ingredient": doc.get("ingredient"),
            "qty": doc.get("qty") or "1",
            "expiry_date": doc.get("expiry_date"),
            "note": doc.get("note") or "",
            "area": doc.get("area") or "",
            "lat": lat,
            "lng": lng,
            "status": doc.get("status") or "open",
            "pantry_item_id": doc.get("pantry_item_id"),
            "claimed_by": doc.get("claimed_by"),
            "distance_km": distance_km,
            "created_at": to_iso(doc.get("created_at")),
            "updated_at": to_iso(doc.get("updated_at")),
        }

    def create_offer(
        self,
        user_id: str,
        *,
        ingredient: str,
        qty: str = "1",
        expiry_date: str | None = None,
        note: str = "",
        area: str = "",
        lat: float | None = None,
        lng: float | None = None,
        pantry_item_id: str | None = None,
        title: str | None = None,
    ) -> dict:
        name = " ".join((ingredient or "").strip().split())
        if len(name) < 2:
            raise ValueError("Describe the surplus food item")
        if len(name) > 80:
            name = name[:80]
        now = utcnow()
        doc = {
            "offer_id": f"surplus_{secrets.token_hex(8)}",
            "user_id": user_id,
            "ingredient": name.lower(),
            "title": (title or name).strip()[:100],
            "qty": (qty or "1").strip()[:40] or "1",
            "expiry_date": (expiry_date or "").strip() or None,
            "note": (note or "").strip()[:400],
            "area": (area or "").strip()[:80],
            "lat": float(lat) if lat is not None else None,
            "lng": float(lng) if lng is not None else None,
            "pantry_item_id": pantry_item_id,
            "status": "open",
            "claimed_by": None,
            "created_at": now,
            "updated_at": now,
        }
        self._offers().insert_one(doc)
        return self._serialize(doc)

    def list_offers(
        self,
        *,
        viewer_id: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
        radius_km: float = 25.0,
        mine: bool = False,
        limit: int = 40,
    ) -> list[dict]:
        query: dict = {"status": "open"}
        if mine and viewer_id:
            query = {"user_id": viewer_id, "status": {"$in": ["open", "claimed"]}}
        docs = list(self._offers().find(query).sort("created_at", -1).limit(max(limit * 3, 40)))
        rows = [self._serialize(d, viewer_lat=lat, viewer_lng=lng) for d in docs]
        if lat is not None and lng is not None and not mine:
            with_coords = [r for r in rows if r.get("distance_km") is not None]
            without = [r for r in rows if r.get("distance_km") is None]
            with_coords.sort(key=lambda r: r["distance_km"])
            nearby = [r for r in with_coords if r["distance_km"] <= radius_km]
            rows = (nearby or with_coords) + without
        return rows[:limit]

    def get_offer(self, offer_id: str) -> dict | None:
        doc = self._offers().find_one({"offer_id": offer_id})
        return self._serialize(doc) if doc else None

    def claim_offer(self, offer_id: str, claimant_id: str) -> dict:
        doc = self._offers().find_one({"offer_id": offer_id})
        if not doc:
            raise ValueError("Offer not found")
        if doc.get("status") != "open":
            raise ValueError("This offer is no longer available")
        if doc.get("user_id") == claimant_id:
            raise ValueError("You cannot claim your own offer")
        self._offers().update_one(
            {"offer_id": offer_id, "status": "open"},
            {
                "$set": {
                    "status": "claimed",
                    "claimed_by": claimant_id,
                    "updated_at": utcnow(),
                }
            },
        )
        updated = self._offers().find_one({"offer_id": offer_id})
        return self._serialize(updated)

    def close_offer(self, offer_id: str, user_id: str) -> None:
        doc = self._offers().find_one({"offer_id": offer_id, "user_id": user_id})
        if not doc:
            raise ValueError("Offer not found")
        self._offers().update_one(
            {"offer_id": offer_id},
            {"$set": {"status": "closed", "updated_at": utcnow()}},
        )

    def delete_user_data(self, user_id: str) -> None:
        self._offers().delete_many({"user_id": user_id})
        self._offers().update_many(
            {"claimed_by": user_id, "status": "claimed"},
            {"$set": {"status": "closed", "updated_at": utcnow()}},
        )
