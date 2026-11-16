"""Independent API review of daily caps and stable map grouping."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from backend.app.database import TaskDefinition
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "review.sqlite")) as value:
        settings = value.get("/api/state").json()["settings"]
        settings.update(work_start="08:00", work_end="12:00", focus_minutes=120,
                        meals=[], break_minutes=0, travel_buffer_minutes=0)
        assert value.put("/api/settings", json=settings).status_code == 200
        yield value


def post(client, path, **data):
    response = client.post("/api/" + path, json=data)
    assert response.status_code in (200, 201), response.text
    return response.json()


def test_daily_maximum_is_shared_across_sessions_and_manual_validation(client):
    task = post(client, "task-definitions", title="Capped last-day work", session_minutes=30,
                min_sessions_per_week=8, min_sessions_per_day=0, max_sessions_per_day=2,
                importance=10, difficulty=0)
    post(client, "task-weeks", task_definition_id=task["id"], week_start="2030-11-10")
    plan = post(client, "schedules/generate", date="2030-11-16")
    blocks = [b for b in plan["blocks"] if b.get("task_definition_id") == task["id"]]
    assert len(blocks) == 2, plan
    assert len({b["logical_session_id"] for b in blocks}) == 2
    before = deepcopy(plan["blocks"])
    # Simulate a restored historical payload whose newer policy is stricter,
    # without the normal API invalidation flag hiding manual validation.
    with client.app.state.session_factory() as db:
        row = db.get(TaskDefinition, task["id"])
        row.payload = {**row.payload, "max_sessions_per_day": 1}
        db.commit()
    response = client.put(f"/api/schedules/{plan['id']}", json={"blocks": before})
    assert response.status_code == 409, response.text
    assert "daily" in response.text.lower() and "maximum" in response.text.lower(), response.text
    assert client.get("/api/schedules?date=2030-11-16").json()[0]["blocks"] == before


def test_map_identity_is_per_place_and_nested_rooms_edit_occurrences(client):
    first = post(client, "locations", name="First room building", lat=43.47, lon=-80.54)
    second = post(client, "locations", name="Second room building", lat=43.48, lon=-80.54)
    task = post(client, "activities", title="One recurring study group", category="commitment",
                subtype="Groupwork", location_id=first["id"], room="101")
    visits = []
    for day, room, override in [(10, "102", {}), (11, "203", {"location_id": second["id"]}),
                                (12, "104", {})]:
        visits.append(post(client, "occurrences", activity_id=task["id"],
                           start=f"2030-11-{day}T09:00:00-05:00", end=f"2030-11-{day}T10:00:00-05:00",
                           location_override={"location_id": first["id"], "room": room, **override}))
    before = client.get("/api/calendar?week_start=2030-11-10").json()
    overview = client.get("/api/location-overview?week_start=2030-11-10").json()
    by_place = {p["id"]: p["references"] for p in overview["locations"]}
    assert len(by_place[first["id"]]) == len(by_place[second["id"]]) == 1
    assert by_place[first["id"]][0]["id"] == by_place[second["id"]][0]["id"]
    nested = [v for refs in by_place.values() for ref in refs for v in ref["occurrences"]]
    assert {v["room"] for v in nested} == {"102", "203", "104"}
    assert {v["edit_target"]["id"] for v in nested} == {v["id"] for v in visits}
    assert client.get("/api/calendar?week_start=2030-11-10").json() == before
