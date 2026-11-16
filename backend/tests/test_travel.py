import asyncio

import httpx
import pytest

from backend.app import travel


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")


A = {"id": "a", "name": "Home", "lat": 43.472, "lon": -80.545}
B = {"id": "b", "name": "Library", "lat": 43.469, "lon": -80.541}


def test_offline_routing_is_explicit_estimate():
    route = asyncio.run(travel.get_route(A, B, {}))
    assert route["estimated"] and route["minutes"] > 0
    assert route["coordinates"] == [[A["lat"], A["lon"]], [B["lat"], B["lon"]]]
    assert "Estimated" in route["source"]


def test_manual_override_direction_and_cache_priority():
    origin = {**A, "travel_overrides": {"b": 17}}
    assert travel.estimate_minutes(origin, B, {}) == 17
    assert asyncio.run(travel.get_route(origin, B, {}))["source"] == "Manual override"
    assert travel.estimate_minutes(B, origin, {}) != 17
    assert travel.estimate_minutes(A, A, {}) == 0


def test_provider_cache_and_route_geometry(monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "0")
    calls = []

    async def provider(*args):
        calls.append(args)
        return {"routes": [{"duration": 420, "distance": 500, "geometry": {"coordinates": [[-80.545, 43.472], [-80.541, 43.469]]}}]}

    monkeypatch.setattr(travel, "_request", provider)
    first = asyncio.run(travel.get_route(A, B, {}))
    assert not first["estimated"] and first["minutes"] == 7
    assert first["coordinates"][0] == [43.472, -80.545]
    assert asyncio.run(travel.get_route(A, B, {})) == first
    assert len(calls) == 1
    assert travel.estimate_minutes(A, B, {}) == 7


def test_provider_failure_falls_back(monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "0")

    async def fail(*args):
        raise httpx.ConnectError("Unavailable")

    monkeypatch.setattr(travel, "_request", fail)
    assert asyncio.run(travel.get_route(A, B, {}))["estimated"]


def test_geocode_is_cached_and_validated(monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "0")
    calls = []

    async def provider(*args):
        calls.append(args)
        return [{"display_name": "University of Waterloo", "lat": "43.472", "lon": "-80.545"}]

    monkeypatch.setattr(travel, "_request", provider)
    assert asyncio.run(travel.geocode("Waterloo"))[0]["lat"] == 43.472
    asyncio.run(travel.geocode("waterloo"))
    assert len(calls) == 1
    with pytest.raises(ValueError):
        asyncio.run(travel.geocode("a"))


def test_geocode_offline_has_actionable_error():
    with pytest.raises(ValueError, match="Click the map"):
        asyncio.run(travel.geocode("Waterloo"))
