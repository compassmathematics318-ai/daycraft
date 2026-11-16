"""Independent cross-layer location regressions, always using isolated databases."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from backend.app.database import Schedule
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.db"))
    with TestClient(create_app(tmp_path / "review.db")) as value:
        yield value


def post(client, path, value):
    response = client.post(f"/api/{path}", json=value)
    assert response.status_code in (200, 201), response.text
    return response.json()


def place(client, name, lat):
    return post(client, "locations", {"name": name, "lat": lat, "lon": -80.54})


def test_map_reference_types_support_filters_and_definitions_have_no_times(client):
    saved = place(client, "Study building", 43.47)
    for hour, (category, subtype) in enumerate([("class", "Lecture"), ("assessment", None), ("commitment", "Groupwork")], start=9):
        times = {"start": f"2026-11-10T{hour:02}:00:00-05:00", "end": f"2026-11-10T{hour + 1:02}:00:00-05:00"}
        assessment = {"assessment_start": times["start"], "assessment_end": times["end"]} if category == "assessment" else {}
        activity = post(client, "activities", {"title": f"Review {category}", "category": category, "subtype": subtype, "location_id": saved["id"], **assessment})
        if category != "assessment":
            post(client, "occurrences", {"activity_id": activity["id"], **times})
    post(client, "task-definitions", {"title": "Untimed task", "task_type": "project_work", "location_id": saved["id"]})
    response = client.get("/api/location-overview?week_start=2026-11-10")
    assert response.status_code == 200
    refs = response.json()["locations"][0]["references"]
    assert {ref["category"] for ref in refs} == {"class", "assessment", "commitment", "project_work"}
    assert len(refs) == 4
    assert sum(ref["occurrence_count"] for ref in refs) == 3
    for ref in refs:
        assert ref["edit_target"]["id"] == ref["entity_id"]
        if ref["source"] in ("activity", "task_definition"):
            assert ref["start"] is None and ref["end"] is None
        else:
            assert ref["source"] == "occurrence" and ref["start"] and ref["end"]


@pytest.mark.parametrize("status,locked", [("todo", True), ("in_progress", False), ("completed", False)])
def test_protected_physical_resolution_cannot_be_rewritten(client, status, locked):
    first, second = place(client, "First", 43.47), place(client, "Second", 43.48)
    block = {"id": "retained", "title": "Recorded preferred work", "kind": "personal", "start": "2026-11-10T09:00:00-05:00", "end": "2026-11-10T10:00:00-05:00", "location_id": first["id"], "location_mode": "preferred", "resolved_location_id": first["id"], "locked": locked, "status": status}
    with client.app.state.session_factory() as db:
        db.add(Schedule(id="retained-plan", date="2026-11-10", payload={"id": "retained-plan", "date": "2026-11-10", "blocks": [block], "status": "optimal"}))
        db.commit()
    changed = deepcopy(block)
    changed["resolved_location_id"] = second["id"]
    response = client.put("/api/schedules/retained-plan", json={"blocks": [changed]})
    assert response.status_code == 409, response.text
    assert client.get("/api/schedules?date=2026-11-10").json()[0]["blocks"] == [block]


def test_generated_preferred_alternative_survives_api_edit_and_maps_actual_position(client):
    first, preferred = place(client, "Actual campus", 43.47), place(client, "Preferred library", 43.48)
    settings = client.get("/api/state").json()["settings"]
    settings.update(work_start="10:00", work_end="11:00", break_minutes=0, travel_buffer_minutes=0, meals=[])
    assert client.put("/api/settings", json=settings).status_code == 200
    for title, start, end in [("Before", "09:00", "10:00"), ("After", "11:00", "12:00")]:
        activity = post(client, "activities", {"title": title, "category": "commitment", "subtype": "Personal", "location_id": first["id"]})
        post(client, "occurrences", {"activity_id": activity["id"], "start": f"2026-11-10T{start}:00-05:00", "end": f"2026-11-10T{end}:00-05:00"})
    task = post(client, "task-definitions", {"title": "Preferred session", "session_minutes": 60, "location_id": preferred["id"], "location_mode": "preferred", "allow_alternative_locations": True, "alternative_location_ids": [first["id"]]})
    post(client, "task-weeks", {"task_definition_id": task["id"], "week_start": "2026-11-08"})
    result = post(client, "schedules/generate", {"date": "2026-11-10", "mode": "balanced"})
    assert result["status"] in ("optimal", "feasible"), result
    session = next(block for block in result["blocks"] if block.get("task_definition_id") == task["id"])
    assert session["location_id"] == preferred["id"]
    assert session["resolved_location_id"] == first["id"]
    response = client.put(f"/api/schedules/{result['id']}", json={"blocks": result["blocks"]})
    assert response.status_code == 200, response.text
    overview = client.get("/api/location-overview?week_start=2026-11-08").json()
    actual = next(item for item in overview["locations"] if item["id"] == first["id"])
    assert any(visit["entity_id"] == session["id"] for ref in actual["references"] for visit in ref["occurrences"])


def test_remote_meeting_cannot_absorb_required_walk_between_venues(client):
    first, second = place(client, "West campus", 43.47), place(client, "East campus", 43.48)
    settings = client.get("/api/state").json()["settings"]
    settings.update(meals=[], break_minutes=0, travel_buffer_minutes=0)
    assert client.put("/api/settings", json=settings).status_code == 200
    for title, start, end, policy in [("At west", "09:00", "10:00", {"location_id": first["id"]}), ("Online", "10:00", "10:30", {"location_mode": "remote"}), ("At east", "10:30", "11:00", {"location_id": second["id"]})]:
        activity = post(client, "activities", {"title": title, "category": "commitment", "subtype": "Personal", **policy})
        post(client, "occurrences", {"activity_id": activity["id"], "start": f"2026-11-10T{start}:00-05:00", "end": f"2026-11-10T{end}:00-05:00"})
    result = post(client, "schedules/generate", {"date": "2026-11-10", "mode": "balanced"})
    assert result["status"] == "infeasible"
    assert result["conflicts"]
