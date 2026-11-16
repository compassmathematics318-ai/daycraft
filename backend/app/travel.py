"""Cached, rate-limited public walking routes; explicit conservative offline estimates."""
from __future__ import annotations

import asyncio
from contextlib import closing
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import unicodedata

import httpx

ROOT = Path(__file__).resolve().parents[2]
_locks: dict[str, asyncio.Lock] = {}
_last: dict[str, float] = {}
HEADERS = {"User-Agent": "ScheduleBuilder/1.0 (local personal daily planner)", "Accept": "application/json"}

# Verified campus names, not coordinates or claims of an exact entrance.
# https://uwaterloo.ca/plant-operations/floor-plans
# https://uwaterloo.ca/students (UWaterloo naming)
BUILDING_ALIAS_SOURCE = "https://uwaterloo.ca/plant-operations/floor-plans"
GEOCODER_POLICY = "https://operations.osmfoundation.org/policies/nominatim/"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
_CAMPUS = "University of Waterloo, Waterloo, Ontario, Canada"
_BUILDINGS = (
    ("SLC", "Student Life Centre", (
        "slc", "student life centre", "student life center",
    )),
    ("QNC", "Mike & Ophelia Lazaridis Quantum-Nano Centre", (
        "qnc", "quantum nano centre", "quantum nano center", "quantum nano",
        "mike and ophelia lazaridis quantum nano centre", "lazaridis quantum nano centre",
    )),
    ("MC", "Mathematics and Computer Building", (
        "mc", "mathematics and computer", "mathematics and computer building",
        "math and computer", "math and computer building", "math computer building",
    )),
    ("RCH", "J.R. Coutts Engineering Lecture Hall", (
        "rch", "j r coutts engineering lecture hall", "j r coutts hall",
        "j r coutts", "coutts hall", "coutts engineering lecture hall",
    )),
    ("DC", "William G. Davis Computer Research Centre", ("dc", "davis centre", "davis center", "william g davis computer research centre")),
    ("DP", "Dana Porter Library", ("dp", "dana porter", "dana porter library")),
    ("PAC", "Physical Activities Complex", ("pac", "physical activities complex")),
    ("M3", "Mathematics 3", ("m3", "mathematics 3", "math 3")),
    ("STC", "Science Teaching Complex", ("stc", "science teaching complex")),
    ("E5", "Engineering 5", ("e5", "engineering 5")),
    ("E7", "Engineering 7", ("e7", "engineering 7")),
    ("EC4", "East Campus 4", ("ec4", "east campus 4")),
    ("NH", "Ira G. Needles Hall", ("nh", "needles hall", "ira g needles hall")),
)


def _normalized_place(value: str) -> str:
    value = "".join(character for character in unicodedata.normalize("NFKD", value) if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^\w\s]", " ", value.casefold().replace("&", " and ")).split())


def building_aliases(query: str) -> list[dict]:
    """Local, explicit query suggestions; these never assert a coordinate match.

    Only exact known names, optionally qualified by campus/city, are expanded.
    Unrelated addresses and ambiguous substrings (e.g. 'MC Toronto') stay intact.
    """
    normalized = _normalized_place(query)
    campus_names = ("university of waterloo waterloo ontario canada", "university of waterloo waterloo ontario",
                    "university of waterloo waterloo", "university of waterloo ontario canada",
                    "waterloo ontario canada", "waterloo ontario", "university of waterloo", "uwaterloo", "u waterloo", "waterloo")
    unqualified = normalized
    for campus in campus_names:
        if unqualified.startswith(campus + " "):
            unqualified = unqualified[len(campus) + 1:]
            break
        if unqualified.endswith(" " + campus):
            unqualified = unqualified[:-len(campus) - 1]
            if unqualified.endswith(" at"):
                unqualified = unqualified[:-3]
            break
    for abbreviation, name, aliases in _BUILDINGS:
        if unqualified in aliases:
            return [{"alias": abbreviation, "name": name, "aliases": list(aliases),
                     "resolved_query": f"{name}, {_CAMPUS}", "alias_source": BUILDING_ALIAS_SOURCE,
                     # OSM names need not match expanded prose. These variants
                     # retain the official building name and explicit city.
                     "fallback_query": f"{'Mathematics & Computer' if abbreviation == 'MC' else 'Quantum Nano Centre' if abbreviation == 'QNC' else name}, Waterloo",
                     "search_query": f"{'Quantum Nano Centre' if abbreviation == 'QNC' else name}, Waterloo",
                     "requires_confirmation": True}]
    if normalized in ("uwaterloo", "u waterloo", "university of waterloo"):
        return [{"alias": "UWaterloo", "name": "University of Waterloo",
                 "aliases": ["uwaterloo", "u waterloo", "university of waterloo"],
                 "resolved_query": _CAMPUS, "alias_source": "https://uwaterloo.ca/students",
                 "requires_confirmation": True}]
    return []


def _cache_path() -> Path:
    return Path(os.environ.get("SCHEDULE_BUILDER_ROUTE_CACHE", str(ROOT / "data" / "travel_cache.sqlite")))


def _read(key: str, ttl: int = 604800):
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, timestamp REAL)")
        row = db.execute("SELECT value,timestamp FROM cache WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row and time.time() - row[1] < ttl else None


def _write(key: str, value):
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, timestamp REAL)")
        db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, json.dumps(value), time.time()))


async def _request(service: str, url: str, params: dict):
    # Separate provider locks avoid concurrent searches and enforce <=1 request/sec.
    lock = _locks.setdefault(service, asyncio.Lock())
    async with lock:
        await asyncio.sleep(max(0, 1.1 - (time.monotonic() - _last.get(service, 0))))
        _last[service] = time.monotonic()
        async with httpx.AsyncClient(timeout=8.0 if service.startswith("geocode") else 3.0, headers=HEADERS, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()


def _distance(a: dict, b: dict) -> float:
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat, dlon = lat2 - lat1, math.radians(b["lon"] - a["lon"])
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(value)))


def _key(a: dict, b: dict) -> str:
    provider = os.environ.get("WALKING_ROUTER_URL", "https://routing.openstreetmap.de/routed-foot/route/v1/foot")
    return f"route:{provider}:{a['lat']:.6f},{a['lon']:.6f}:{b['lat']:.6f},{b['lon']:.6f}"


def _override(a: dict, b: dict):
    return a.get("travel_overrides", {}).get(b.get("id"))


def _same_location(a: dict, b: dict) -> bool:
    if a.get("id") is not None and b.get("id") is not None:
        return a["id"] == b["id"]
    return a["lat"] == b["lat"] and a["lon"] == b["lon"]


def cached_route(origin: dict, destination: dict, settings: dict | None = None) -> dict | None:
    """Return an authoritative local route without contacting any provider.

    Matrix preparation uses this before its network budget, so a large location
    library never loses manual-override or cached-route provenance.
    """
    base = {"origin_id": origin.get("id"), "destination_id": destination.get("id"),
            "coordinates": [[origin["lat"], origin["lon"]], [destination["lat"], destination["lon"]]]}
    if _same_location(origin, destination):
        return {**base, "minutes": 0, "distance_m": 0, "estimated": False, "source": "Same location"}
    override = _override(origin, destination)
    if override is not None:
        return {**base, "minutes": int(math.ceil(float(override))), "distance_m": round(_distance(origin, destination)),
                "estimated": False, "source": "Manual override"}
    cached = _read(_key(origin, destination))
    if cached:
        return {**cached, **{key: base[key] for key in ("origin_id", "destination_id")}}
    return None


def estimate_minutes(origin: dict | None, destination: dict | None, settings: dict) -> int:
    if not origin or not destination or _same_location(origin, destination):
        return 0
    cached = cached_route(origin, destination, settings)
    if cached:
        return int(cached["minutes"])
    distance = _distance(origin, destination) * 1.4
    speed = max(1, float(settings.get("walking_speed_kmh", 4.5))) * 1000 / 60
    return max(1, int(math.ceil(distance / speed)))


async def get_route(origin: dict, destination: dict, settings: dict) -> dict:
    distance = _distance(origin, destination)
    coords = [[origin["lat"], origin["lon"]], [destination["lat"], destination["lon"]]]
    base = {"origin_id": origin.get("id"), "destination_id": destination.get("id"), "coordinates": coords}
    cached = cached_route(origin, destination, settings)
    if cached:
        return cached
    key = _key(origin, destination)
    provider = os.environ.get("WALKING_ROUTER_URL", "https://routing.openstreetmap.de/routed-foot/route/v1/foot").rstrip("/")
    try:
        if os.environ.get("SCHEDULE_BUILDER_OFFLINE") == "1" or not provider:
            raise ValueError("Offline mode")
        pair = f"{origin['lon']},{origin['lat']};{destination['lon']},{destination['lat']}"
        response = await _request("routing", f"{provider}/{pair}", {"overview": "full", "geometries": "geojson", "steps": "false"})
        route = response["routes"][0]
        seconds, routed_distance = float(route["duration"]), float(route["distance"])
        if not math.isfinite(seconds) or not math.isfinite(routed_distance) or seconds < 0 or routed_distance < 0:
            raise ValueError("Provider returned invalid route measurements")
        geometry = [[float(p[1]), float(p[0])] for p in route["geometry"]["coordinates"]]
        if len(geometry) < 2 or any(not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180 for lat, lon in geometry):
            raise ValueError("Provider returned invalid route geometry")
        minutes = max(1, math.ceil(seconds / 60))
        result = {**base, "minutes": minutes, "distance_m": round(routed_distance), "estimated": False,
                  "source": "Pedestrian routing provider", "coordinates": geometry}
        _write(key, result)
        return result
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, OverflowError):
        return {**base, "minutes": estimate_minutes(origin, destination, settings), "distance_m": round(distance * 1.4),
                "estimated": True, "source": "Estimated walk (distance × 1.4); verify access and crossings"}


async def geocode_search(query: str, saved_locations: list[dict] | None = None, region: str = "", center: tuple[float, float] | None = None) -> dict:
    from .geocoding import search
    return await search(query, saved_locations, region, center)


async def geocode(query: str) -> list[dict]:
    """Compatibility helper; endpoint uses the structured search result."""
    response = await geocode_search(query)
    if response["status"] not in ("ok", "no_results"):
        raise ValueError("Place search is unavailable. " + response["message"])
    return response["results"]
