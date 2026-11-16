"""Explicit, bounded place search with independent providers and local reuse.

No coordinates are inferred from an alias. Every candidate is either a saved
user location or a validated provider point, and must be confirmed by the user.
"""
from __future__ import annotations

import logging
import math
import os
import socket
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from . import travel

logger = logging.getLogger(__name__)
DEFAULT_PRIMARY = "https://nominatim.openstreetmap.org/search"
DEFAULT_FALLBACK = "https://photon.komoot.io/api/"
# Public Photon demo policy: https://github.com/komoot/photon#demo-server
# Both public services are used only after explicit submit, never autocomplete.


def _public_endpoint(endpoint: str) -> str:
    """Diagnostics never expose credentials or configured URL query tokens."""
    parsed = urlsplit(endpoint)
    return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))


def _valid_endpoint(endpoint: str) -> bool:
    try:
        parsed = urlsplit(endpoint)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)
    except ValueError:
        return False


def _coordinates(lat, lon) -> tuple[float, float]:
    lat, lon = float(lat), float(lon)
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Invalid provider point")
    return lat, lon


def _parse(response, kind: str) -> list[dict]:
    if kind == "photon":
        if not isinstance(response, dict) or not isinstance(response.get("features"), list):
            raise ValueError("Expected GeoJSON features")
        points = []
        for feature in response["features"][:5]:
            if not isinstance(feature, dict):
                raise ValueError("Expected a feature object")
            properties = feature["properties"]
            geometry = feature["geometry"]
            if not isinstance(properties, dict) or not isinstance(geometry, dict):
                raise ValueError("Expected feature properties and geometry")
            if geometry.get("type") != "Point":
                raise ValueError("Expected a point")
            if not isinstance(geometry.get("coordinates"), list) or len(geometry["coordinates"]) < 2:
                raise ValueError("Expected coordinate pair")
            lon, lat = geometry["coordinates"][:2]
            address = {key: value for key, value in properties.items()
                       if key in ("housenumber", "street", "city", "state", "country", "postcode") and isinstance(value, str)}
            name = properties.get("name") or properties.get("street") or properties.get("city")
            points.append({"lat": lat, "lon": lon, "name": name,
                           "display_name": ", ".join(dict.fromkeys([name, *address.values()])),
                           "address": address, "osm_type": properties.get("osm_type"), "osm_id": properties.get("osm_id")})
    else:
        if not isinstance(response, list):
            raise ValueError("Expected results array")
        points = response[:5]
    results = []
    for point in points:
        if not isinstance(point, dict):
            raise ValueError("Expected a place object")
        lat, lon = _coordinates(point["lat"], point["lon"])
        name = point["display_name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Expected place name")
        address = point.get("address") or {}
        if not isinstance(address, dict):
            raise ValueError("Expected address object")
        results.append({"name": name, "place_name": point.get("name"), "lat": lat, "lon": lon,
                        "address": {key: value for key, value in address.items() if isinstance(key, str) and isinstance(value, str)},
                        "attribution": point.get("licence") or travel.OSM_ATTRIBUTION,
                        "osm_type": point.get("osm_type"), "osm_id": point.get("osm_id")})
    return results


def _failure(exc: Exception) -> tuple[str, str, int | None]:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return ("rate_limited" if code == 429 else "configuration_error" if code in (401, 403, 404) else "unavailable", "http_error", code)
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", "timeout", None
    if isinstance(exc, httpx.ConnectError):
        cause = exc
        while cause is not None:
            if isinstance(cause, socket.gaierror):
                return "unavailable", "dns_error", None
            cause = cause.__cause__ or cause.__context__
        return "unavailable", "connection_error", None
    if isinstance(exc, httpx.HTTPError):
        return "unavailable", "network_error", None
    return "invalid_response", "invalid_response", None


def _saved(query: str, locations: list[dict], alias: dict | None) -> list[dict]:
    normalized = travel._normalized_place(query)
    results = []
    for place in locations:
        names = [place.get("name", ""), place.get("building", ""), *place.get("aliases", [])]
        matches = normalized in {travel._normalized_place(value) for value in names if value}
        if not matches and alias:
            matches = any(candidate and candidate[0]["alias"] == alias["alias"]
                          for candidate in (travel.building_aliases(value) for value in names if value))
        if not matches:
            continue
        lat, lon = _coordinates(place["lat"], place["lon"])
        results.append({"name": place["name"], "lat": lat, "lon": lon, "address": place.get("address", ""),
                        "location_id": place.get("id"), "source": "Saved location", "provider": "local",
                        "attribution": "Your saved location", "query": query, "resolved_query": query,
                        "initial_query": query, "fallback_used": False, "match_type": "saved", "requires_confirmation": True})
    return results[:5]


def _alias_matches(point: dict, alias: dict | None) -> bool:
    if not alias:
        return True
    # Context-qualified campus aliases must not select a same-named building
    # elsewhere, a shop inside it, or the campus centroid.
    if not (43.40 <= point["lat"] <= 43.55 and -80.65 <= point["lon"] <= -80.45):
        return False
    normalized = travel._normalized_place(point.get("place_name") or point["name"].split(",")[0])
    return normalized in {travel._normalized_place(value) for value in [alias["name"], *alias["aliases"]]}


async def search(query: str, saved_locations: list[dict] | None = None, region: str = "", center: tuple[float, float] | None = None) -> dict:
    query = " ".join(query.split())
    diagnostics = []
    base = {"results": [], "context": region, "diagnostics": diagnostics}
    if len(query) < 2 or len(query) > 200 or not travel._normalized_place(query):
        return {**base, "status": "invalid_query", "message": "Search must contain 2–200 characters and a place name or address."}
    alias = next(iter(travel.building_aliases(query)), None)
    local = _saved(query, saved_locations or [], alias)
    if local:
        diagnostics.append({"stage": "saved", "provider": "local", "outcome": "ok", "elapsed_ms": 0})
        return {**base, "results": local, "status": "ok", "message": "Choose a saved location to confirm it."}
    # A broad search preference, never a candidate coordinate or hard boundary.
    # Exact home coordinates and other saved records stay on this computer.
    if center is not None:
        center = tuple(round(value, 2) for value in _coordinates(*center))
    elif "waterloo" in travel._normalized_place(region):
        center = (43.47, -80.54)
    initial = alias["resolved_query"] if alias else query
    # Long institutional prose can match a shop's address rather than the
    # building. Concise official names + city were verified against providers.
    if alias and alias["alias"] not in ("MC", "RCH", "UWaterloo"):
        initial = alias.get("search_query", f"{alias['name']}, Waterloo")
    second = alias.get("fallback_query") if alias else None
    if not alias and region and "," not in query and travel._normalized_place(region) not in travel._normalized_place(query):
        second = f"{query}, {region}"
    primary = os.environ.get("GEOCODER_URL", DEFAULT_PRIMARY).strip()
    fallback = os.environ.get("GEOCODER_FALLBACK_URL", DEFAULT_FALLBACK).strip()
    attempts = [("primary", "nominatim", primary, initial)]
    if second and second != initial:
        attempts.append(("normalized", "nominatim", primary, second))
    attempts.append(("fallback", "photon", fallback, second or initial))
    failures = []
    primary_failed = False
    for stage, kind, endpoint, resolved in attempts:
        if stage == "normalized" and primary_failed:
            continue  # Different wording cannot fix a blocked provider.
        if stage == "fallback" and primary_failed and not alias:
            # Preserve an explicit distant place when changing providers. The
            # primary outage offers no evidence that its wording was wrong.
            resolved = initial
        start = time.monotonic()
        diagnostic = {"stage": stage, "provider": _public_endpoint(endpoint) if _valid_endpoint(endpoint) else "unconfigured",
                      "query": resolved, "outcome": "unavailable"}
        diagnostics.append(diagnostic)
        if not endpoint:
            diagnostic.update(outcome="skipped", reason="provider_disabled", elapsed_ms=0)
            if stage == "primary":
                failures.append("configuration_error")
                primary_failed = True
            continue
        if not _valid_endpoint(endpoint):
            diagnostic.update(outcome="configuration_error", reason="invalid_endpoint", elapsed_ms=0)
            failures.append("configuration_error")
            if kind == "nominatim":
                primary_failed = True
            continue
        params = {"q": resolved, "limit": 5}
        if kind == "nominatim":
            params.update(format="jsonv2", addressdetails=1, namedetails=1)
        if alias:
            # Coarse public city bounds, never exact home coordinates.
            params.update({"viewbox": "-80.65,43.55,-80.45,43.40", "bounded": 1} if kind == "nominatim"
                          else {"bbox": "-80.65,43.40,-80.45,43.55"})
        elif center:
            lat, lon = center
            params.update({"viewbox": f"{max(-180, lon - .2):.2f},{min(90, lat + .15):.2f},{min(180, lon + .2):.2f},{max(-90, lat - .15):.2f}", "bounded": 0}
                          if kind == "nominatim" else {"lat": lat, "lon": lon})
        key = f"geocode:v4:{kind}:{endpoint}:{travel._normalized_place(resolved)}:{bool(alias)}:{center}:{travel._normalized_place(region)}"
        try:
            cached = travel._read(key, 2592000)
            if cached is None and kind == "nominatim" and stage == "primary":
                # Keep pre-repair successful searches useful while offline.
                for legacy_query in dict.fromkeys((resolved, query, alias["resolved_query"] if alias else query)):
                    legacy = travel._read(f"geocode:v3:{endpoint}:{legacy_query.casefold()}", 2592000)
                    if legacy and legacy.get("results"):
                        cached = {"results": _parse(legacy["results"], kind), "stored_at": time.time()}
                        break
            if cached is not None and (cached["results"] or time.time() - cached["stored_at"] < 300):
                points = cached["results"]
                diagnostic["cached"] = True
            else:
                if os.environ.get("SCHEDULE_BUILDER_OFFLINE") == "1":
                    diagnostic.update(outcome="unavailable", reason="offline")
                    failures.append("unavailable")
                    if kind == "nominatim":
                        primary_failed = True
                    continue
                raw = await travel._request("geocode" if kind == "nominatim" else "geocode-photon", endpoint, params)
                points = _parse(raw, kind)
                travel._write(key, {"results": points, "stored_at": time.time()})
            points = [point for point in points if _alias_matches(point, alias)]
            diagnostic["outcome"] = "ok" if points else "no_results"
            if points:
                results = []
                seen = set()
                for point in points:
                    identity = (round(point["lat"], 6), round(point["lon"], 6), point["name"])
                    if identity in seen:
                        continue
                    seen.add(identity)
                    result = {**point, "query": query, "resolved_query": resolved, "initial_query": initial,
                              "fallback_used": stage != "primary", "match_type": "alias" if alias else "provider",
                              "source": "Photon / OpenStreetMap place search" if kind == "photon" else
                              "OpenStreetMap place search" if endpoint == DEFAULT_PRIMARY else "Configured place search provider",
                              "provider": _public_endpoint(endpoint), "requires_confirmation": True}
                    if alias:
                        result.update({key: alias[key] for key in ("alias", "alias_source")})
                    results.append(result)
                return {**base, "results": results, "status": "ok", "message":
                        "Found places using the fallback provider. Review the address and pin." if stage == "fallback" else "Choose a place and confirm its pin."}
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, OverflowError) as exc:
            status, reason, http_status = _failure(exc)
            diagnostic.update(outcome=status, reason=reason)
            if http_status:
                diagnostic["http_status"] = http_status
            failures.append(status)
            if kind == "nominatim":
                primary_failed = True
            # Log actionable provider evidence without raw responses, query,
            # private saved records, credential-bearing URLs or network text.
            logger.warning("geocode provider=%s stage=%s outcome=%s reason=%s http_status=%s exception=%s",
                           diagnostic["provider"], stage, status, reason, http_status, type(exc).__name__)
        finally:
            diagnostic["elapsed_ms"] = round((time.monotonic() - start) * 1000)
    if failures:
        status = next((value for value in ("rate_limited", "timeout", "unavailable", "invalid_response", "configuration_error") if value in failures), "unavailable")
        messages = {"rate_limited": "Place search was rate limited. Wait briefly and submit again.",
                    "timeout": "Place search timed out. Submit again when your connection is ready.",
                    "configuration_error": "Place search provider configuration needs attention.",
                    "invalid_response": "Place search received an invalid provider response.",
                    "unavailable": "Place search is unavailable or offline. Check your connection and retry."}
        return {**base, "status": status, "message": messages[status] + " Saved locations still work. Click the map or enter coordinates if needed."}
    return {**base, "status": "no_results", "message": "No matching places were found. Try a full name, city or street address."}
