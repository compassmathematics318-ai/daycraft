"""Explicit venue consent and unchanged historical plans through the API."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest

from backend.app.database import Schedule
from backend.app.main import create_app, routes_for


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.db"))
    with TestClient(create_app(tmp_path / "venues.db")) as value:
        yield value


def post(client, path, value):
    response = client.post(f"/api/{path}", json=value)
    assert response.status_code in (200, 201), response.text
    return response.json()


def places(client):
    return [post(client, "locations", {"name": name, "lat": 43.47, "lon": -80.54}) for name in ("PAC", "MC", "Library")]


@pytest.mark.parametrize("path,base", [
    ("activities", {"title": "Gym", "category": "commitment", "subtype": "Personal"}),
    ("task-definitions", {"title": "Gym"}),
    ("tasks", {"title": "Gym"}),
    ("classes", {"title": "Gym", "weekdays": [0], "start_time": "09:00", "end_time": "10:00"}),
])
def test_all_definition_writes_require_explicit_valid_alternative_consent(client, path, base):
    first, second, _ = places(client)
    policy = {"location_id": first["id"], "location_mode": "preferred"}
    saved = post(client, path, {**base, **policy})
    assert saved["allow_alternative_locations"] is False
    assert saved["alternative_location_ids"] == []
    enabled = {**policy, "allow_alternative_locations": True, "alternative_location_ids": [second["id"]]}
    saved = post(client, path, {**base, **enabled})
    assert saved["alternative_location_ids"] == [second["id"]]
    assert client.delete(f"/api/locations/{second['id']}").status_code == 409
    for bad in (
        {"alternative_location_ids": [second["id"]]},
        {"allow_alternative_locations": True},
        {"allow_alternative_locations": True, "alternative_location_ids": ["missing"]},
        {"allow_alternative_locations": True, "alternative_location_ids": [first["id"]]},
        {"allow_alternative_locations": True, "alternative_location_ids": [second["id"]], "location_mode": "required"},
    ):
        assert client.post(f"/api/{path}", json={**base, **policy, **bad}).status_code == 422


def test_week_and_occurrence_overrides_validate_and_reset_venue_consent(client):
    first, second, third = places(client)
    policy = {"location_id": first["id"], "location_mode": "preferred", "allow_alternative_locations": True, "alternative_location_ids": [second["id"]]}
    definition = post(client, "task-definitions", {"title": "Gym", **policy})
    week = post(client, "task-weeks", {"task_definition_id": definition["id"], "week_start": "2026-11-08", "overrides": {"location_id": third["id"]}})
    assert week["effective_definition"]["allow_alternative_locations"] is False
    assert week["effective_definition"]["alternative_location_ids"] == []
    assert client.post("/api/task-weeks", json={"task_definition_id": definition["id"], "week_start": "2026-11-15", "overrides": {"alternative_location_ids": ["missing"]}}).status_code == 422
    activity = post(client, "activities", {"title": "Gym", "category": "commitment", "subtype": "Personal", **policy})
    event = {"activity_id": activity["id"], "start": "2026-11-10T09:00:00-05:00", "end": "2026-11-10T10:00:00-05:00"}
    assert client.post("/api/occurrences", json={**event, "location_override": {**policy, "alternative_location_ids": ["missing"]}}).status_code == 422
    saved = post(client, "occurrences", {**event, "location_override": policy})
    assert saved["location_override"]["alternative_location_ids"] == [second["id"]]
    copy = client.post("/api/calendar/copy-previous-week", json={"week_start": "2026-11-15"}).json()
    assert copy["occurrences"][0]["location_override"] == saved["location_override"]


def test_older_clients_retain_consent_only_while_selected_venue_is_unchanged(client):
    first, second, third = places(client)
    value = post(client, "task-definitions", {"title": "Gym", "location_id": first["id"], "location_mode": "preferred", "allow_alternative_locations": True, "alternative_location_ids": [second["id"]]})
    old_client = {key: item for key, item in value.items() if key not in {"legacy_task_id", "scheduling_model", "allow_alternative_locations", "alternative_location_ids"}}
    updated = client.put(f"/api/task-definitions/{value['id']}", json=old_client)
    assert updated.status_code == 200, updated.text
    assert updated.json()["allow_alternative_locations"] is True
    old_client["location_id"] = third["id"]
    updated = client.put(f"/api/task-definitions/{value['id']}", json=old_client)
    assert updated.status_code == 200, updated.text
    assert updated.json()["allow_alternative_locations"] is False
    assert updated.json()["alternative_location_ids"] == []


def test_routes_include_weekly_whitelist_with_inherited_permission(client):
    first, second, third = places(client)
    definition = post(client, "task-definitions", {"title": "Study", "location_id": first["id"], "location_mode": "preferred", "allow_alternative_locations": True, "alternative_location_ids": [second["id"]]})
    post(client, "task-weeks", {"task_definition_id": definition["id"], "week_start": "2026-11-08", "overrides": {"alternative_location_ids": [third["id"]]}})
    settings = client.get("/api/state").json()["settings"]
    with client.app.state.session_factory() as db:
        _, matrix = asyncio.run(routes_for(db, settings))
    assert (first["id"], third["id"]) in matrix
    assert (third["id"], first["id"]) in matrix


def test_recorded_unauthorized_historical_venue_can_be_retained_through_schema_serialization(client):
    first, second, _ = places(client)
    block = {"id": "recorded", "title": "Gym", "kind": "personal", "start": "2026-11-10T14:00:00Z", "end": "2026-11-10T15:00:00Z", "location_id": first["id"], "location_mode": "preferred", "resolved_location_id": second["id"], "locked": True, "status": "completed"}
    with client.app.state.session_factory() as db:
        db.add(Schedule(id="recorded", date="2026-11-10", payload={"id": "recorded", "date": "2026-11-10", "status": "optimal", "blocks": [block]}))
        db.commit()
    response = client.put("/api/schedules/recorded", json={"blocks": [block]})
    assert response.status_code == 200, response.text
    saved = response.json()["blocks"][0]
    assert saved["location_id"] == first["id"]
    assert saved["resolved_location_id"] == second["id"]


@pytest.mark.parametrize("adjacent_alternative", [False, True])
def test_manual_preferred_override_commits_to_selected_actual_venue(client, adjacent_alternative):
    first, second, _ = places(client)
    prior = {"id": "before", "title": "At MC", "kind": "personal", "start": "2026-11-10T09:00:00-05:00", "end": "2026-11-10T10:00:00-05:00", "location_id": second["id"], "location_mode": "required", "resolved_location_id": second["id"]}
    initial = [prior] if adjacent_alternative else []
    with client.app.state.session_factory() as db:
        db.add(Schedule(id="manual", date="2026-11-10", payload={"id": "manual", "date": "2026-11-10", "status": "optimal", "blocks": initial}))
        db.commit()
    selected = {"id": "gym", "title": "Gym", "kind": "personal", "start": "2026-11-10T10:00:00-05:00", "end": "2026-11-10T11:00:00-05:00", "location_id": first["id"], "location_mode": "preferred", "location_override": True, "allow_alternative_locations": True, "alternative_location_ids": [second["id"]], "resolved_location_id": None}
    response = client.put("/api/schedules/manual", json={"blocks": initial + [selected]})
    if adjacent_alternative:
        # MC is an allowed possibility, but the manual choice is PAC and needs
        # travel. The server cannot validate MC then export PAC as the venue.
        assert response.status_code == 409, response.text
        assert "travel" in response.text.lower()
    else:
        assert response.status_code == 200, response.text
        assert response.json()["blocks"][0]["resolved_location_id"] == first["id"]
        saved = client.get("/api/schedules?date=2026-11-10").json()[0]["blocks"][0]
        assert saved["resolved_location_id"] == first["id"]
        exported = client.get("/api/schedules/manual/export").text
        assert "LOCATION:PAC" in exported


@pytest.mark.parametrize("historic,protected", [(False, False), (False, True), (True, False)])
def test_unsafe_pending_saved_plan_is_flagged_without_rewriting_history(client, historic, protected):
    first, second, _ = places(client)
    today = datetime.now(ZoneInfo("America/Toronto")).date()
    date = (today + timedelta(days=-10 if historic else 10)).isoformat()
    block = {"id": "gym", "title": "Gym", "kind": "personal", "start": f"{date}T09:00:00-05:00", "end": f"{date}T10:00:00-05:00", "location_id": first["id"], "location_mode": "preferred", "resolved_location_id": second["id"], "locked": protected}
    payload = {"id": "plan", "date": date, "status": "optimal", "blocks": [block]}
    original = deepcopy(payload)
    with client.app.state.session_factory() as db:
        db.add(Schedule(id="plan", date=date, payload=payload))
        db.commit()
    view = client.get("/api/schedules", params={"date": date}).json()[0]
    state = client.get("/api/state").json()["schedules"][0]
    assert view == state
    assert view["blocks"] == [block]
    unsafe = not historic and not protected
    assert view.get("needs_regeneration", False) is unsafe
    assert view["status"] == ("stale" if unsafe else "optimal")
    if unsafe:
        assert client.put("/api/schedules/plan", json={"blocks": [block]}).status_code == 409
        assert client.get("/api/schedules/plan/export").status_code == 409
    with client.app.state.session_factory() as db:
        assert db.get(Schedule, "plan").payload == original
