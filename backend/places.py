"""Restaurant discovery via OpenStreetMap (Nominatim geocode + Overpass nearby)."""

from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import quote_plus

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org"
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
USER_AGENT = "PetugramRestaurantDiscovery/1.0 (food-waste-app; contact=petugram-local)"


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _tag(tags: dict, *keys: str) -> str:
    for key in keys:
        val = tags.get(key)
        if val:
            return str(val).strip()
    return ""


def _truthy_tag(tags: dict, *keys: str) -> bool:
    for key in keys:
        val = str(tags.get(key) or "").strip().lower()
        if val in {"yes", "only", "true", "1", "halal", "vegetarian", "vegan"}:
            return True
    return False


def _parse_cuisine(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[;,/|]+", raw)
    return [p.strip().replace("_", " ").title() for p in parts if p.strip()]


def _osm_to_place(el: dict, origin_lat: float, origin_lng: float) -> dict | None:
    tags = el.get("tags") or {}
    name = _tag(tags, "name", "name:en", "brand")
    if not name:
        return None
    lat = el.get("lat")
    lng = el.get("lon")
    if lat is None or lng is None:
        center = el.get("center") or {}
        lat = center.get("lat")
        lng = center.get("lon")
    if lat is None or lng is None:
        return None
    lat_f, lng_f = float(lat), float(lng)
    amenity = _tag(tags, "amenity") or "restaurant"
    cuisines = _parse_cuisine(_tag(tags, "cuisine"))
    website = _tag(tags, "website", "contact:website", "url")
    phone = _tag(tags, "phone", "contact:phone")
    opening = _tag(tags, "opening_hours")
    address_parts = [
        _tag(tags, "addr:housenumber"),
        _tag(tags, "addr:street"),
        _tag(tags, "addr:suburb", "addr:neighbourhood"),
        _tag(tags, "addr:city", "addr:town", "addr:village"),
    ]
    address = ", ".join(p for p in address_parts if p)
    area = _tag(tags, "addr:suburb", "addr:neighbourhood", "addr:city", "addr:town") or ""
    place_id = el.get("_place_id_override") or f"osm-{el.get('type', 'node')}-{el.get('id')}"
    distance_km = round(_haversine_km(origin_lat, origin_lng, lat_f, lng_f), 2)
    # OSM rarely has star ratings; approximate from optional tags
    rating = None
    for key in ("stars", "rating", "review:rating"):
        raw = tags.get(key)
        if raw is None:
            continue
        try:
            rating = float(str(raw).split("/")[0])
            break
        except ValueError:
            continue
    price_level = None
    price_raw = _tag(tags, "price", "price_range", "fee")
    if price_raw:
        if price_raw.count("$") >= 3 or "expensive" in price_raw.lower():
            price_level = 3
        elif price_raw.count("$") == 2 or "moderate" in price_raw.lower():
            price_level = 2
        elif price_raw.count("$") == 1 or "cheap" in price_raw.lower() or "budget" in price_raw.lower():
            price_level = 1

    halal_raw = str(tags.get("diet:halal") or tags.get("halal") or "").strip().lower()
    cuisine_blob = " ".join(cuisines).lower()
    halal = halal_raw in {"yes", "only", "true", "1", "halal"} or "halal" in cuisine_blob
    haram = (
        halal_raw in {"no", "false", "0"}
        or any(x in cuisine_blob for x in ("pork", "bacon", "ham", "non-halal", "non halal"))
    )
    vegetarian = _truthy_tag(tags, "diet:vegetarian", "diet:vegan") or any(
        c.lower() in {"vegetarian", "vegan"} for c in cuisines
    )
    delivery = _truthy_tag(tags, "delivery")
    takeaway = _truthy_tag(tags, "takeaway")
    if not delivery and takeaway:
        delivery = False  # takeaway ≠ delivery; leave false unless delivery tag set
    # Some cafes mark cuisine delivery in description — keep strict to tags only

    maps_url = f"https://www.openstreetmap.org/{el.get('type', 'node')}/{el.get('id')}"
    directions_url = (
        f"https://www.google.com/maps/dir/?api=1&destination={lat_f},{lng_f}"
        f"&destination_place_id=&travelmode=driving"
    )
    google_search = f"https://www.google.com/maps/search/?api=1&query={quote_plus(name + ' ' + address)}"

    return {
        "place_id": place_id,
        "osm_type": el.get("type"),
        "osm_id": el.get("id"),
        "name": name,
        "restaurant_name": name,
        "amenity": amenity,
        "cuisines": cuisines,
        "cuisine": ", ".join(cuisines[:3]) if cuisines else "",
        "lat": lat_f,
        "lng": lng_f,
        "address": address,
        "area": area,
        "phone": phone,
        "website": website,
        "opening_hours": opening,
        "rating": rating,
        "price_level": price_level,
        "halal": halal,
        "haram": haram,
        "vegetarian": vegetarian,
        "delivery": delivery,
        "distance_km": distance_km,
        "maps_url": maps_url,
        "directions_url": directions_url,
        "google_maps_url": google_search,
        "menu_url": website or "",
        "reviews_url": google_search,
        "source": "openstreetmap",
    }


class PlacesService:
    def __init__(self, timeout: float = 22.0) -> None:
        self.timeout = timeout

    def _client(self, timeout: float | None = None) -> httpx.Client:
        t = timeout if timeout is not None else self.timeout
        return httpx.Client(
            timeout=httpx.Timeout(t, connect=8.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    def _overpass_query(self, lat: float, lng: float, radius_m: int) -> list[dict]:
        query = f"""
        [out:json][timeout:20];
        (
          node["amenity"="restaurant"](around:{radius_m},{lat},{lng});
          node["amenity"="cafe"](around:{radius_m},{lat},{lng});
          node["amenity"="fast_food"](around:{radius_m},{lat},{lng});
          way["amenity"="restaurant"](around:{radius_m},{lat},{lng});
          way["amenity"="cafe"](around:{radius_m},{lat},{lng});
          way["amenity"="fast_food"](around:{radius_m},{lat},{lng});
        );
        out center tags;
        """
        last_error: Exception | None = None
        for url in OVERPASS_URLS:
            try:
                with self._client(18.0) as client:
                    res = client.post(url, data={"data": query})
                    if res.status_code >= 400:
                        last_error = RuntimeError(f"Overpass {res.status_code} @ {url}")
                        continue
                    payload = res.json()
                    return list(payload.get("elements") or [])
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
        if last_error:
            raise last_error
        return []

    def _nominatim_nearby(self, lat: float, lng: float, radius_m: int, limit: int = 30) -> list[dict]:
        """Fallback when Overpass is down: bounded Nominatim restaurant search."""
        # degrees roughly: 1 deg lat ≈ 111 km
        delta = max(radius_m, 3000) / 111_000.0
        viewbox = f"{lng - delta},{lat + delta},{lng + delta},{lat - delta}"
        terms = ("restaurant", "cafe", "fast food", "food court")
        elements: list[dict] = []
        seen: set[str] = set()
        with self._client(15.0) as client:
            for term in terms:
                try:
                    res = client.get(
                        f"{NOMINATIM_URL}/search",
                        params={
                            "q": term,
                            "format": "json",
                            "addressdetails": 1,
                            "extratags": 1,
                            "limit": min(limit, 15),
                            "viewbox": viewbox,
                            "bounded": 1,
                        },
                        headers={
                            "User-Agent": USER_AGENT,
                            "Accept": "application/json",
                            "Accept-Language": "en",
                        },
                    )
                    if res.status_code >= 400:
                        continue
                    rows = res.json()
                except Exception:  # noqa: BLE001
                    continue
                for row in rows if isinstance(rows, list) else []:
                    try:
                        plat = float(row["lat"])
                        plng = float(row["lon"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    pid = f"nominatim-{row.get('place_id')}"
                    if pid in seen:
                        continue
                    if _haversine_km(lat, lng, plat, plng) > (radius_m / 1000.0) * 1.35:
                        continue
                    seen.add(pid)
                    extratags = row.get("extratags") or {}
                    address = row.get("address") or {}
                    name = row.get("name") or (row.get("display_name") or "").split(",")[0]
                    if not name:
                        continue
                    # Shape like Overpass element for shared mapper
                    tags = {
                        "name": name,
                        "amenity": extratags.get("amenity")
                        or ("cafe" if "cafe" in term else "restaurant"),
                        "cuisine": extratags.get("cuisine") or "",
                        "website": extratags.get("website") or "",
                        "phone": extratags.get("phone") or "",
                        "opening_hours": extratags.get("opening_hours") or "",
                        "diet:halal": extratags.get("diet:halal") or "",
                        "addr:street": address.get("road") or "",
                        "addr:suburb": address.get("suburb") or address.get("neighbourhood") or "",
                        "addr:city": address.get("city") or address.get("town") or "",
                    }
                    elements.append(
                        {
                            "type": "node",
                            "id": row.get("place_id") or len(seen),
                            "lat": plat,
                            "lon": plng,
                            "tags": tags,
                            "_place_id_override": f"osm-nominatim-{row.get('place_id')}",
                        }
                    )
                if len(elements) >= limit:
                    break
        return elements

    @staticmethod
    def _short_label(row: dict, fallback: str = "") -> str:
        addr = row.get("address") or {}
        parts = []
        for key in (
            "amenity",
            "building",
            "shop",
            "tourism",
            "road",
            "neighbourhood",
            "suburb",
            "quarter",
            "village",
            "town",
            "city_district",
            "city",
            "county",
            "state",
            "country",
        ):
            val = addr.get(key)
            if val and val not in parts:
                parts.append(str(val))
            if len(parts) >= 4:
                break
        if parts:
            return ", ".join(parts)
        display = (row.get("display_name") or fallback or "").strip()
        if not display:
            return fallback
        bits = [b.strip() for b in display.split(",") if b.strip()]
        return ", ".join(bits[:4]) if bits else display

    def geocode(self, query: str, limit: int = 5) -> list[dict]:
        q = (query or "").strip()
        if not q:
            return []

        # Allow pasting coordinates: "24.8607, 67.0011"
        coord = re.match(
            r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$",
            q,
        )
        if coord:
            lat_f, lng_f = float(coord.group(1)), float(coord.group(2))
            if -90 <= lat_f <= 90 and -180 <= lng_f <= 180:
                return [
                    {
                        "label": f"{lat_f:.5f}, {lng_f:.5f}",
                        "lat": lat_f,
                        "lng": lng_f,
                        "type": "coordinate",
                        "place_id": f"coord-{lat_f:.5f}-{lng_f:.5f}",
                        "importance": 1.0,
                    }
                ]

        fetch_n = max(int(limit), 8)
        with self._client() as client:
            res = client.get(
                f"{NOMINATIM_URL}/search",
                params={
                    "q": q,
                    "format": "json",
                    "addressdetails": 1,
                    "limit": fetch_n,
                    "dedupe": 1,
                },
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Accept-Language": "en",
                },
            )
            res.raise_for_status()
            rows = res.json()

        out = []
        seen: set[tuple[float, float]] = set()
        for row in rows:
            try:
                lat_f = float(row["lat"])
                lng_f = float(row["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            key = (round(lat_f, 4), round(lng_f, 4))
            if key in seen:
                continue
            seen.add(key)
            try:
                importance = float(row.get("importance") or 0)
            except (TypeError, ValueError):
                importance = 0.0
            out.append(
                {
                    "label": self._short_label(row, q),
                    "lat": lat_f,
                    "lng": lng_f,
                    "type": row.get("type") or row.get("class"),
                    "place_id": f"nominatim-{row.get('place_id')}",
                    "importance": importance,
                    "display_name": row.get("display_name") or "",
                }
            )
        out.sort(key=lambda r: (-(r.get("importance") or 0), r.get("label") or ""))
        return out[: max(1, min(int(limit), 10))]

    def reverse_geocode(self, lat: float, lng: float) -> dict | None:
        with self._client() as client:
            res = client.get(
                f"{NOMINATIM_URL}/reverse",
                params={
                    "lat": lat,
                    "lon": lng,
                    "format": "json",
                    "addressdetails": 1,
                    "zoom": 16,
                },
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Accept-Language": "en",
                },
            )
            res.raise_for_status()
            row = res.json()
        if not row or row.get("error"):
            return None
        return {
            "label": self._short_label(row, f"{lat:.4f}, {lng:.4f}"),
            "lat": float(lat),
            "lng": float(lng),
            "place_id": f"nominatim-{row.get('place_id')}",
            "display_name": row.get("display_name") or "",
        }

    def nearby(
        self,
        lat: float,
        lng: float,
        *,
        radius_m: int = 5000,
        cuisine: str | None = None,
        min_rating: float | None = None,
        max_price: int | None = None,
        halal: bool | None = None,
        haram: bool | None = None,
        vegetarian: bool | None = None,
        delivery: bool | None = None,
        q: str | None = None,
        limit: int = 40,
        min_results: int = 10,
        _expanded: bool = False,
    ) -> list[dict]:
        start_r = max(500, min(int(radius_m or 5000), 15000))
        limit = max(10, min(int(limit or 40), 60))
        want = max(0, min(int(min_results or 0), limit))
        search_r = max(start_r, 8000) if want >= 10 and not _expanded else start_r
        search_r = min(max(search_r, start_r), 15000)

        elements: list[dict] = []
        source = "overpass"
        try:
            elements = self._overpass_query(lat, lng, search_r)
        except Exception:
            source = "nominatim"
            elements = self._nominatim_nearby(lat, lng, search_r, limit=max(limit, 24))

        if not elements and source == "overpass":
            source = "nominatim"
            elements = self._nominatim_nearby(lat, lng, search_r, limit=max(limit, 24))

        places: list[dict] = []
        seen: set[str] = set()
        for el in elements:
            place = _osm_to_place(el, lat, lng)
            if not place:
                continue
            pid = place["place_id"]
            if pid in seen:
                continue
            seen.add(pid)
            place["source"] = source
            places.append(place)

        places = self._apply_filters(
            places,
            cuisine=cuisine,
            min_rating=min_rating,
            max_price=max_price,
            halal=halal,
            haram=haram,
            vegetarian=vegetarian,
            delivery=delivery,
            q=q,
        )
        places.sort(key=lambda p: (p.get("distance_km") is None, p.get("distance_km") or 999))

        if want and len(places) < want and search_r < 15000 and not _expanded:
            try:
                return self.nearby(
                    lat,
                    lng,
                    radius_m=15000,
                    cuisine=cuisine,
                    min_rating=min_rating,
                    max_price=max_price,
                    halal=halal,
                    haram=haram,
                    vegetarian=vegetarian,
                    delivery=delivery,
                    q=q,
                    limit=limit,
                    min_results=want,
                    _expanded=True,
                )
            except Exception:
                pass

        for place in places:
            place["search_radius_m"] = search_r
        return places[:limit]

    def _apply_filters(
        self,
        places: list[dict],
        *,
        cuisine: str | None,
        min_rating: float | None,
        max_price: int | None,
        halal: bool | None,
        haram: bool | None,
        vegetarian: bool | None,
        delivery: bool | None,
        q: str | None,
    ) -> list[dict]:
        out = []
        cuisine_l = (cuisine or "").strip().lower()
        needle = (q or "").strip().lower()
        for place in places:
            if cuisine_l:
                blob = " ".join(place.get("cuisines") or []).lower() + " " + str(place.get("cuisine") or "").lower()
                if cuisine_l not in blob and not any(cuisine_l in c.lower() for c in (place.get("cuisines") or [])):
                    continue
            if min_rating is not None and place.get("rating") is not None:
                if float(place["rating"]) < float(min_rating):
                    continue
            elif min_rating is not None and place.get("rating") is None:
                # Keep unrated when filtering by rating (OSM sparse ratings)
                pass
            if max_price is not None and place.get("price_level") is not None:
                if int(place["price_level"]) > int(max_price):
                    continue
            if halal is True and not place.get("halal"):
                continue
            if haram is True and place.get("halal") and not place.get("haram"):
                continue
            if vegetarian is True and not place.get("vegetarian"):
                continue
            if delivery is True and not place.get("delivery"):
                continue
            if needle:
                hay = f"{place.get('name','')} {place.get('address','')} {place.get('cuisine','')}".lower()
                if needle not in hay:
                    continue
            out.append(place)
        return out

    def details(self, place_id: str, lat: float | None = None, lng: float | None = None) -> dict | None:
        """Resolve OSM node/way details; optional lat/lng used for distance context."""
        m = re.match(r"^osm-(node|way|relation)-(\d+)$", place_id or "")
        if not m:
            return None
        osm_type, osm_id = m.group(1), m.group(2)
        query = f"""
        [out:json][timeout:20];
        {osm_type}({osm_id});
        out center tags;
        """
        with self._client() as client:
            res = client.post(OVERPASS_URL, data={"data": query})
            res.raise_for_status()
            payload = res.json()
        elements = payload.get("elements") or []
        if not elements:
            return None
        origin_lat = float(lat) if lat is not None else 0.0
        origin_lng = float(lng) if lng is not None else 0.0
        place = _osm_to_place(elements[0], origin_lat, origin_lng)
        if not place:
            return None
        # Lightweight "reviews" substitute: structured facts + external links
        facts = []
        if place.get("opening_hours"):
            facts.append({"author": "OpenStreetMap", "text": f"Hours: {place['opening_hours']}", "rating": None})
        if place.get("phone"):
            facts.append({"author": "OpenStreetMap", "text": f"Phone: {place['phone']}", "rating": None})
        if place.get("halal"):
            facts.append({"author": "OpenStreetMap", "text": "Marked as halal-friendly", "rating": None})
        if place.get("vegetarian"):
            facts.append({"author": "OpenStreetMap", "text": "Vegetarian / vegan options indicated", "rating": None})
        place["reviews"] = facts
        place["reviews_note"] = "Community map data — open Google Maps for full reviews and photos."
        return place
