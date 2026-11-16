"""Offline geospatial regressions: aliases remain suggestions until confirmed."""
import asyncio

import pytest

from backend.app import travel


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "travel.sqlite"))
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "0")


@pytest.mark.parametrize("query,alias", [
    ("MC", "MC"), ("MC Waterloo", "MC"), ("Mathematics & Computer Building", "MC"),
    ("Mathematics and Computer Building UWaterloo", "MC"), ("RCH", "RCH"),
    ("University of Waterloo RCH", "RCH"), ("J.R. Coutts Engineering Lecture Hall", "RCH"),
    ("UWaterloo", "UWaterloo"),
])
def test_known_aliases_explain_expansion_without_fabricating_coordinates(query, alias):
    suggestion, = travel.building_aliases(query)
    assert suggestion["alias"] == alias
    assert "University of Waterloo" in suggestion["resolved_query"]
    assert suggestion["requires_confirmation"]
    assert suggestion["alias_source"].startswith("https://uwaterloo.ca/")
    assert "lat" not in suggestion


@pytest.mark.parametrize("query", ["MC Toronto", "Mc Donald Road", "RCH London", "Waterloo", "123 King St"])
def test_unrelated_places_are_not_forced_to_campus(query):
    assert travel.building_aliases(query) == []


def test_aliases_share_cached_provider_response_and_keep_each_query(monkeypatch):
    calls = []

    async def provider(service, endpoint, params):
        calls.append(params)
        return [{"display_name": "Mathematics and Computer Building, Waterloo", "lat": "43.47", "lon": "-80.54",
                 "address": {"road": "Ring Road", "city": "Waterloo", "invalid": None}}]

    monkeypatch.setattr(travel, "_request", provider)
    first, = asyncio.run(travel.geocode("MC Waterloo"))
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    second, = asyncio.run(travel.geocode("Mathematics and Computer Building"))
    assert len(calls) == 1
    assert calls[0]["addressdetails"] == 1
    assert first["query"] == "MC Waterloo"
    assert second["query"] == "Mathematics and Computer Building"
    assert second["resolved_query"] == first["resolved_query"]
    assert first["address"] == {"road": "Ring Road", "city": "Waterloo"}
    assert first["match_type"] == "alias" and first["requires_confirmation"]
    assert "OpenStreetMap" in first["attribution"]


def test_general_search_preserves_multiple_choices_and_original_query(monkeypatch):
    async def provider(service, endpoint, params):
        assert params["q"] == "Paris"
        return [{"display_name": name, "lat": "48", "lon": "2"} for name in ("Paris France", "Paris Ontario")]

    monkeypatch.setattr(travel, "_request", provider)
    results = asyncio.run(travel.geocode("Paris"))
    assert len(results) == 2
    assert all(result["requires_confirmation"] and result["match_type"] == "provider" for result in results)


@pytest.mark.parametrize("query,expected", [
    ("MC Waterloo", "Mathematics & Computer, Waterloo"),
    ("RCH", "J.R. Coutts Engineering Lecture Hall, Waterloo"),
])
def test_empty_alias_search_retries_once_with_official_name_and_caches_provenance(monkeypatch, query, expected):
    calls = []

    async def provider(service, endpoint, params):
        calls.append(params["q"])
        return [] if len(calls) == 1 else [{"display_name": expected, "lat": "43.47", "lon": "-80.54"}]

    monkeypatch.setattr(travel, "_request", provider)
    candidate, = asyncio.run(travel.geocode(query))
    assert len(calls) == 2 and calls[1] == expected
    assert candidate["initial_query"] == calls[0]
    assert candidate["resolved_query"] == expected and candidate["fallback_used"]
    assert candidate["requires_confirmation"]
    assert asyncio.run(travel.geocode(query)) == [candidate]
    assert len(calls) == 2


def test_empty_alias_fallback_is_bounded_and_never_returns_campus_centroid(monkeypatch):
    calls = []

    async def provider(service, endpoint, params):
        calls.append(params["q"])
        return {"features": []} if service == "geocode-photon" else []

    monkeypatch.setattr(travel, "_request", provider)
    assert asyncio.run(travel.geocode("MC")) == []
    assert len(calls) == 3
    assert asyncio.run(travel.geocode("MC")) == []
    assert len(calls) == 3


def test_invalid_provider_result_does_not_poison_cache(monkeypatch):
    calls = []

    async def provider(*args):
        calls.append(args)
        return [{"display_name": "Bad", "lat": "nan", "lon": "0"}]

    monkeypatch.setattr(travel, "_request", provider)
    for _ in range(2):
        with pytest.raises(ValueError, match="unavailable"):
            asyncio.run(travel.geocode("bad point"))
    assert len(calls) == 4


def test_known_different_and_unsaved_locations_do_not_get_free_travel(monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    a, b = {"lat": 43.47, "lon": -80.54}, {"lat": 43.48, "lon": -80.54}
    route = asyncio.run(travel.get_route(a, b, {}))
    assert route["minutes"] > 0 and route["estimated"]
    assert travel.estimate_minutes({**a, "id": "a"}, {**a, "id": "b"}, {}) == 1
