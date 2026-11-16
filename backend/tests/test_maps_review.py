"""Independent mapping regressions; public providers are never contacted."""
import asyncio
import math
import time

import httpx
import pytest

from backend.app import travel

A = {"id": "a", "lat": 43.4728, "lon": -80.5420}
B = {"id": "b", "lat": 43.4698, "lon": -80.5423}


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "0")


def test_cache_provenance_is_available_without_remote_requests(monkeypatch):
    async def provider(*args):
        return {"routes": [{"duration": 420, "distance": 523, "geometry": {"coordinates": [[A["lon"], A["lat"]], [B["lon"], B["lat"]]]}}]}

    monkeypatch.setattr(travel, "_request", provider)
    assert travel.cached_route(A, B) is None
    actual = asyncio.run(travel.get_route(A, B, {}))
    assert travel.cached_route(A, B) == actual
    override = {**A, "travel_overrides": {"b": 17}}
    assert travel.cached_route(override, B)["source"] == "Manual override"
    assert travel.cached_route(override, B)["minutes"] == 17
    assert travel.cached_route(A, A)["source"] == "Same location"


def test_route_cache_respects_provider_and_changed_coordinates(monkeypatch):
    travel._write(travel._key(A, B), {"minutes": 7, "estimated": False, "source": "Pedestrian routing provider"})
    assert travel.cached_route(A, B)["minutes"] == 7
    assert travel.cached_route(A, {**B, "lat": B["lat"] + .01}) is None
    monkeypatch.setenv("WALKING_ROUTER_URL", "https://other-router.invalid/foot")
    assert travel.cached_route(A, B) is None


def test_fallback_speed_changes_are_not_stale_cached_routes(monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    slow = asyncio.run(travel.get_route(A, B, {"walking_speed_kmh": 2}))
    fast = asyncio.run(travel.get_route(A, B, {"walking_speed_kmh": 6}))
    assert slow["minutes"] > fast["minutes"] > 0
    assert slow["estimated"] and fast["estimated"]


@pytest.mark.parametrize("field,value", [("duration", -60), ("duration", math.inf), ("duration", math.nan), ("distance", -1)])
def test_invalid_provider_measurements_fall_back(monkeypatch, field, value):
    async def provider(*args):
        route = {"duration": 420, "distance": 523, "geometry": {"coordinates": [[A["lon"], A["lat"]], [B["lon"], B["lat"]]]}}
        route[field] = value
        return {"routes": [route]}

    monkeypatch.setattr(travel, "_request", provider)
    result = asyncio.run(travel.get_route(A, B, {}))
    assert result["estimated"] and result["minutes"] > 1
    assert travel.cached_route(A, B) is None


def test_geocoding_rejects_invalid_provider_coordinates(monkeypatch):
    async def provider(*args):
        return [{"display_name": "Invalid", "lat": "nan", "lon": "-80"}]

    monkeypatch.setattr(travel, "_request", provider)
    with pytest.raises(ValueError, match="unavailable"):
        asyncio.run(travel.geocode("invalid point"))


def test_requests_are_serialized_and_rate_limited(monkeypatch):
    starts = []

    class Client:
        def __init__(self, **options):
            assert options["headers"]["User-Agent"].startswith("ScheduleBuilder/")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params):
            starts.append(time.monotonic())
            return httpx.Response(200, json=[], request=httpx.Request("GET", url))

    monkeypatch.setattr(travel.httpx, "AsyncClient", Client)

    async def requests():
        await asyncio.gather(travel._request("qa-unique", "https://provider.invalid", {}), travel._request("qa-unique", "https://provider.invalid", {}))

    asyncio.run(requests())
    assert len(starts) == 2 and starts[1] - starts[0] >= 1.05
