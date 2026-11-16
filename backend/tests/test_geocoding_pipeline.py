"""Provider contracts and failure classification; all public calls are stubbed."""
import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import travel
from backend.app.main import create_app


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "0")
    monkeypatch.delenv("GEOCODER_URL", raising=False)
    monkeypatch.delenv("GEOCODER_FALLBACK_URL", raising=False)


def photon(name="Student Life Centre", lat=43.4719722, lon=-80.5452128):
    return {"features": [{"properties": {"name": name, "city": "Waterloo", "country": "Canada"},
                          "geometry": {"type": "Point", "coordinates": [lon, lat]}}]}


@pytest.mark.parametrize("query", ["SLC", "Student Life Centre", "Student Life Center", "SLC Waterloo",
                                    "student life centre at University of Waterloo", "Student Life Centre, Waterloo, Ontario"])
def test_slc_alias_uses_contextual_name_never_salt_lake_city(monkeypatch, query):
    calls = []

    async def provider(service, endpoint, params):
        calls.append(params)
        return [{"name": "Student Life Centre", "display_name": "Student Life Centre, Waterloo, Ontario, Canada",
                 "lat": "43.4719722", "lon": "-80.5452128"}]

    monkeypatch.setattr(travel, "_request", provider)
    result = asyncio.run(travel.geocode_search(query))
    assert result["status"] == "ok"
    assert calls[0]["q"] == "Student Life Centre, Waterloo"
    assert calls[0]["bounded"] == 1
    assert result["results"][0]["alias"] == "SLC"


@pytest.mark.parametrize("query,code", [("QNC", "QNC"), ("Quantum Nano Centre", "QNC"), ("EC4 Waterloo", "EC4"),
                                         ("Dana Porter Library", "DP"), ("Science Teaching Complex", "STC")])
def test_verified_campus_aliases_are_names_without_local_coordinates(query, code):
    alias, = travel.building_aliases(query)
    assert alias["alias"] == code and "lat" not in alias


def test_saved_alias_exact_match_is_local_and_retains_location_id(monkeypatch):
    async def forbidden(*args):
        pytest.fail("Saved locations must never be sent to an external service")

    monkeypatch.setattr(travel, "_request", forbidden)
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    place = {"id": "private-local", "name": "My private room", "aliases": ["SLC"], "lat": 43.47, "lon": -80.54, "address": "Private address"}
    result = asyncio.run(travel.geocode_search("Student Life Centre", [place], "Waterloo, Ontario"))
    assert result["status"] == "ok" and result["results"][0]["location_id"] == "private-local"
    assert result["results"][0]["match_type"] == "saved"
    assert result["diagnostics"] == [{"stage": "saved", "provider": "local", "outcome": "ok", "elapsed_ms": 0}]


def test_independent_fallback_after_primary_connection_failure(monkeypatch):
    calls = []

    async def provider(service, endpoint, params):
        calls.append((service, endpoint, params))
        if service == "geocode":
            raise httpx.ConnectError("Blocked provider")
        return photon()

    monkeypatch.setattr(travel, "_request", provider)
    result = asyncio.run(travel.geocode_search("SLC"))
    candidate, = result["results"]
    assert result["status"] == "ok" and len(calls) == 2
    assert calls[0][1] != calls[1][1]
    assert candidate["fallback_used"] and "Photon" in candidate["source"]
    assert candidate["lat"] == 43.4719722 and candidate["requires_confirmation"]
    assert result["diagnostics"][0]["reason"] == "connection_error"


def test_primary_outage_preserves_distant_query_for_independent_fallback(monkeypatch):
    calls = []

    async def provider(service, endpoint, params):
        calls.append(params["q"])
        if service == "geocode":
            raise httpx.ConnectError("Blocked provider")
        return photon("Toronto City Hall", 43.6536032, -79.3840055)

    monkeypatch.setattr(travel, "_request", provider)
    result = asyncio.run(travel.geocode_search("Toronto City Hall", region="Waterloo, Ontario"))
    assert result["status"] == "ok"
    assert calls == ["Toronto City Hall", "Toronto City Hall"]


@pytest.mark.parametrize("endpoint,offline", [("", False), ("ftp://invalid/search", False), ("https://provider.test", True)])
def test_primary_configuration_or_offline_failure_skips_wording_retry(monkeypatch, endpoint, offline):
    monkeypatch.setenv("GEOCODER_URL", endpoint)
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1" if offline else "0")
    calls = []

    async def provider(service, endpoint, params):
        calls.append(params["q"])
        assert service == "geocode-photon"
        return photon("Toronto City Hall", 43.6536032, -79.3840055)

    monkeypatch.setattr(travel, "_request", provider)
    result = asyncio.run(travel.geocode_search("Toronto City Hall", region="Waterloo, Ontario"))
    assert [item["stage"] for item in result["diagnostics"]] == ["primary", "fallback"]
    assert result["diagnostics"][-1]["query"] == "Toronto City Hall"
    assert calls == ([] if offline else ["Toronto City Hall"])


@pytest.mark.parametrize("failure,status,reason", [
    (httpx.ReadTimeout("timeout"), "timeout", "timeout"),
    (httpx.ConnectError("network"), "unavailable", "connection_error"),
    (httpx.HTTPStatusError("limit", request=httpx.Request("GET", "https://provider.test"),
                           response=httpx.Response(429)), "rate_limited", "http_error"),
    (httpx.HTTPStatusError("forbidden", request=httpx.Request("GET", "https://provider.test"),
                           response=httpx.Response(403)), "configuration_error", "http_error"),
])
def test_total_provider_failure_is_not_reported_as_zero_results(monkeypatch, failure, status, reason):
    async def provider(*args):
        raise failure

    monkeypatch.setattr(travel, "_request", provider)
    result = asyncio.run(travel.geocode_search("Unknown building"))
    assert result["status"] == status and result["results"] == []
    assert all(item["reason"] == reason and "elapsed_ms" in item for item in result["diagnostics"])


def test_genuine_empty_search_is_bounded_cached_and_separate_from_failure(monkeypatch):
    calls = []

    async def provider(service, endpoint, params):
        calls.append(params)
        return {"features": []} if service == "geocode-photon" else []

    monkeypatch.setattr(travel, "_request", provider)
    for _ in range(2):
        result = asyncio.run(travel.geocode_search("An unknown place", region="Waterloo, Ontario"))
        assert result["status"] == "no_results"
    assert len(calls) == 3
    assert calls[1]["q"] == "An unknown place, Waterloo, Ontario"


def test_negative_cache_expires_quickly_not_thirty_days(monkeypatch):
    calls = []

    async def provider(service, endpoint, params):
        calls.append(params)
        return {"features": []} if service == "geocode-photon" else []

    monkeypatch.setattr(travel, "_request", provider)
    asyncio.run(travel.geocode_search("Unknown"))
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + 301)
    asyncio.run(travel.geocode_search("Unknown"))
    assert len(calls) == 4


@pytest.mark.parametrize("payload", [None, [], {"features": None}, {"features": [None]},
    {"features": [{"properties": [], "geometry": None}]},
    {"features": [{"properties": {}, "geometry": {"type": "Point", "coordinates": []}}]},
    {"features": [{"properties": {"name": "Invalid"}, "geometry": {"type": "Point", "coordinates": [0, "nan"]}}]}])
def test_malformed_photon_payload_is_classified_and_never_cached(monkeypatch, payload):
    calls = []

    async def provider(service, endpoint, params):
        calls.append(service)
        return [] if service == "geocode" else payload

    monkeypatch.setattr(travel, "_request", provider)
    for _ in range(2):
        result = asyncio.run(travel.geocode_search("Unknown"))
        assert result["status"] == "invalid_response"
    assert calls.count("geocode-photon") == 2


def test_nonempty_wrong_shop_and_distant_campus_names_do_not_block_fallback(monkeypatch):
    async def provider(service, endpoint, params):
        if service == "geocode-photon":
            return photon()
        return [{"name": "Flock Stop", "display_name": "Flock Stop, Student Life Centre, Waterloo", "lat": 43.4713, "lon": -80.5454},
                {"name": "Student Life Centre", "display_name": "Student Life Centre, Barrie", "lat": 44.41, "lon": -79.66}]

    monkeypatch.setattr(travel, "_request", provider)
    result = asyncio.run(travel.geocode_search("SLC"))
    assert result["results"][0]["source"].startswith("Photon")
    assert result["results"][0]["lat"] == 43.4719722


def test_provider_url_tokens_are_not_returned_or_logged(monkeypatch, caplog):
    monkeypatch.setenv("GEOCODER_URL", "https://secret:password@provider.test/search?key=private-token")
    monkeypatch.setenv("GEOCODER_FALLBACK_URL", "")

    async def provider(*args):
        raise httpx.ConnectError("Potential sensitive URL")

    monkeypatch.setattr(travel, "_request", provider)
    result = asyncio.run(travel.geocode_search("Home private secret"))
    diagnostic_text = json.dumps(result["diagnostics"])
    assert "password" not in diagnostic_text and "private-token" not in diagnostic_text
    assert "Home private secret" not in caplog.text


def test_global_address_and_qualified_other_campus_are_preserved(monkeypatch):
    calls = []

    async def provider(service, endpoint, params):
        calls.append(params["q"])
        return {"features": []} if service == "geocode-photon" else []

    monkeypatch.setattr(travel, "_request", provider)
    result = asyncio.run(travel.geocode_search("123 King Street, Toronto", region="Waterloo, Ontario"))
    assert result["status"] == "no_results"
    assert calls == ["123 King Street, Toronto"] * 2
    assert travel.building_aliases("SLC London") == []


def test_coarse_context_bias_keeps_global_queries_unbounded_and_cache_separate(monkeypatch):
    calls = []

    async def provider(service, endpoint, params):
        calls.append(params)
        return [{"display_name": "Toronto City Hall, Toronto", "lat": 43.653, "lon": -79.384}]

    monkeypatch.setattr(travel, "_request", provider)
    result = asyncio.run(travel.geocode_search("Toronto City Hall", region="Waterloo, Ontario", center=(43.471234, -80.545678)))
    assert result["status"] == "ok" and result["results"][0]["lat"] == 43.653
    assert calls[0]["bounded"] == 0 and "43.471234" not in str(calls[0]) and "80.545678" not in str(calls[0])
    asyncio.run(travel.geocode_search("Toronto City Hall", region="London", center=(42.98, -81.25)))
    assert len(calls) == 2 and calls[0]["viewbox"] != calls[1]["viewbox"]


def test_api_exposes_structured_failure_and_reuses_saved_place(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    with TestClient(create_app(tmp_path / "api.sqlite")) as client:
        unavailable = client.post("/api/geocode", json={"query": "Uncached building"})
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["status"] == "unavailable"
        assert unavailable.json()["detail"]["diagnostics"][0]["reason"] == "offline"
        place = client.post("/api/locations", json={"name": "Office", "aliases": ["Work"], "lat": 43.47, "lon": -80.54}).json()
        response = client.post("/api/geocode", json={"query": "Work"})
        assert response.status_code == 200
        assert response.json()["results"][0]["location_id"] == place["id"]
        invalid = client.post("/api/geocode", json={"query": "  "})
        assert invalid.status_code == 422 and invalid.json()["detail"]["status"] == "invalid_query"
