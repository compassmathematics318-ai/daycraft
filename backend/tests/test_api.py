"""API tests use isolated SQLite databases and never contact public map providers."""
from copy import deepcopy
from datetime import datetime

from fastapi.testclient import TestClient
import pytest

from backend.app import main, task_library, work_confirmation
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "route-cache.db"))
    with TestClient(create_app(tmp_path / "planner.db")) as client:
        yield client


def task(client, **values):
    payload = {"title": "Write assignment", "duration_minutes": 50, "remaining_minutes": 50, "min_session_minutes": 25, "max_session_minutes": 50, **values}
    response = client.post("/api/tasks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def simple_settings(client):
    settings = client.get("/api/state").json()["settings"]
    settings.update(work_start="08:00", work_end="11:00", meals=[], break_minutes=10, travel_buffer_minutes=0)
    response = client.put("/api/settings", json=settings)
    assert response.status_code == 200, response.text
    return response.json()


def generate(client):
    response = client.post("/api/schedules/generate", json={"date": "2026-11-10", "mode": "balanced"})
    assert response.status_code == 200, response.text
    return response.json()


def set_test_clock(monkeypatch, instant):
    """Keep elapsed-work lifecycle assertions independent of the wall clock."""
    fixed = datetime.fromisoformat(instant)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    for module in (main, task_library, work_confirmation):
        monkeypatch.setattr(module, "datetime", Clock)


def test_health_and_empty_state(client):
    assert client.get("/health").json() == {"status": "ok", "app": "schedule-builder"}
    state = client.get("/api/state").json()
    assert state["tasks"] == state["classes"] == state["locations"] == state["schedules"] == []
    assert state["settings"]["timezone"] == "America/Toronto"


def test_validation_and_task_defaults(client):
    assert client.post("/api/tasks", json={"title": "Bad", "priority": 10}).status_code == 422
    assert client.post("/api/tasks", json={"title": "Bad", "unknown": "data"}).status_code == 422
    assert client.post("/api/tasks", json={"title": "Bad", "duration_minutes": 31}).status_code == 422
    value = client.post("/api/tasks", json={"title": "Good", "duration_minutes": 120}).json()
    assert value["remaining_minutes"] == 120
    assert client.post("/api/tasks", json={"title": "Bad", "location_id": "absent"}).status_code == 422
    assert client.put("/api/tasks/absent", json=value).status_code == 404


def test_settings_constraints(client):
    settings = client.get("/api/state").json()["settings"]
    settings["work_start"] = "23:30"
    assert client.put("/api/settings", json=settings).status_code == 422
    settings["work_start"] = "08:00"
    settings["timezone"] = "Not/AZone"
    assert client.put("/api/settings", json=settings).status_code == 422
    settings["timezone"] = "America/Toronto"
    settings["meals"] = [{"name": "A", "time": "12:00", "duration_minutes": 30}, {"name": "B", "time": "12:15", "duration_minutes": 30}]
    # Legacy times are soft preferences; overlapping preferences are valid.
    assert client.put("/api/settings", json=settings).status_code == 200


def test_dependencies_are_validated(client):
    first = task(client, title="Read")
    second = task(client, title="Write", dependencies=[first["id"]])
    first["dependencies"] = [second["id"]]
    assert client.put(f"/api/tasks/{first['id']}", json=first).status_code == 422
    assert client.delete(f"/api/tasks/{first['id']}").status_code == 204
    assert client.get("/api/tasks").json()[0]["dependencies"] == []
    assert client.post("/api/tasks", json={"title": "Bad", "dependencies": ["missing"]}).status_code == 422


def test_class_dates_and_location_integrity(client):
    location = client.post("/api/locations", json={"name": "DC", "lat": 43.47, "lon": -80.54}).json()
    payload = {"title": "Class", "date": "2026-11-10", "start_time": "09:00", "end_time": "10:00", "location_id": location["id"]}
    response = client.post("/api/classes", json=payload)
    assert response.status_code == 201, response.text
    assert client.delete(f"/api/locations/{location['id']}").status_code == 409
    assert client.post("/api/classes", json={**payload, "end_time": "08:00"}).status_code == 422
    assert client.post("/api/classes", json={**payload, "date": None, "weekdays": [7]}).status_code == 422
    assert client.delete(f"/api/classes/{response.json()['id']}").status_code == 204
    assert client.delete(f"/api/locations/{location['id']}").status_code == 204


def test_dst_deadline_validation(client):
    response = client.post("/api/tasks", json={"title": "Invalid local time", "deadline": "2027-03-14T02:30"})
    assert response.status_code == 422
    valid = task(client, deadline="2027-03-14T03:30")
    assert valid["deadline"].endswith("-04:00")


def test_generate_edit_complete_and_regenerate(client, monkeypatch):
    set_test_clock(monkeypatch, "2026-11-10T12:00:00-05:00")
    simple_settings(client)
    work = task(client)
    schedule = generate(client)
    assert schedule["status"] in ("optimal", "feasible"), schedule
    assert len(client.get("/api/schedules?date=2026-11-10").json()) == 1
    blocks = deepcopy(schedule["blocks"])
    selected = next(block for block in blocks if block.get("task_id") == work["id"])
    selected.update(locked=True, status="completed")
    length = round((datetime.fromisoformat(selected["end"]) - datetime.fromisoformat(selected["start"])).total_seconds() / 60)
    response = client.put(f"/api/schedules/{schedule['id']}", json={"blocks": blocks})
    assert response.status_code == 200, response.text
    remaining = client.get("/api/tasks").json()[0]["remaining_minutes"]
    assert remaining == 50 - length
    # Repeated status saves cannot count the same work twice.
    assert client.put(f"/api/schedules/{schedule['id']}", json={"blocks": response.json()["blocks"]}).status_code == 200
    assert client.get("/api/tasks").json()[0]["remaining_minutes"] == remaining
    regenerated = generate(client)
    preserved = next(block for block in regenerated["blocks"] if block["id"] == selected["id"])
    assert preserved["start"] == selected["start"] and preserved["status"] == "completed"
    # Delete everywhere withdraws demand but retains confirmed historical work.
    assert client.delete(f"/api/tasks/{work['id']}").status_code == 204
    assert client.get("/api/tasks").json() == []
    assert client.get("/api/task-definitions").json() == []
    history = client.get("/api/schedules").json()[0]
    deleted_work = next(block for block in history["blocks"] if block["id"] == selected["id"])
    assert deleted_work == preserved
    assert history["tasks_dirty"]


def test_fixed_class_manual_move_rejected(client):
    simple_settings(client)
    client.post("/api/classes", json={"title": "Fixed", "date": "2026-11-10", "start_time": "09:00", "end_time": "10:00"})
    schedule = generate(client)
    blocks = deepcopy(schedule["blocks"])
    selected = next(block for block in blocks if block["kind"] == "class")
    selected["start"] = "2026-11-10T09:05:00-05:00"
    response = client.put(f"/api/schedules/{schedule['id']}", json={"blocks": blocks})
    assert response.status_code == 409
    assert client.get("/api/schedules").json()[0]["blocks"] == schedule["blocks"]


def test_deleting_unstarted_task_removes_saved_schedule_references(client, monkeypatch):
    set_test_clock(monkeypatch, "2026-11-10T07:00:00-05:00")
    simple_settings(client)
    work = task(client)
    schedule = generate(client)
    assert any(b.get("task_id") == work["id"] for b in schedule["blocks"])
    assert client.delete(f"/api/tasks/{work['id']}").status_code == 204
    saved = client.get("/api/schedules").json()[0]
    assert not any(b.get("task_id") == work["id"] for b in saved["blocks"])
    assert not saved["unallocated"]
    assert saved["tasks_dirty"] and saved["status"] == "stale"
    assert client.put(f"/api/schedules/{saved['id']}", json={"blocks": saved["blocks"]}).status_code == 409
    assert not any(b.get("task_id") == work["id"] for b in generate(client)["blocks"])


def test_whole_task_completion_preserves_saved_planner_work_evidence(client, monkeypatch):
    set_test_clock(monkeypatch, "2026-11-10T07:00:00-05:00")
    simple_settings(client)
    work = task(client)
    original = generate(client)
    work.update(status="completed", remaining_minutes=0)
    assert client.put(f"/api/tasks/{work['id']}", json=work).status_code == 200
    saved = client.get("/api/schedules").json()[0]
    assert saved["blocks"] == original["blocks"]
    assert saved["tasks_dirty"]
    assert client.get("/api/task-definitions").json()[0]["status"] == "completed"
    assert not any(b.get("task_id") == work["id"] for b in generate(client)["blocks"])


def test_location_delete_cleans_directional_overrides(client):
    a = client.post("/api/locations", json={"name": "A", "lat": 43.47, "lon": -80.54}).json()
    b = client.post("/api/locations", json={"name": "B", "lat": 43.48, "lon": -80.55}).json()
    a["travel_overrides"] = {b["id"]: 15}
    assert client.put(f"/api/locations/{a['id']}", json=a).status_code == 200
    assert client.delete(f"/api/locations/{b['id']}").status_code == 204
    saved = client.get("/api/locations").json()[0]
    assert saved["travel_overrides"] == {}
    assert client.put(f"/api/locations/{a['id']}", json=saved).status_code == 200


def test_regeneration_uses_current_class_and_meal_sources(client):
    simple_settings(client)
    settings = client.get("/api/state").json()["settings"]
    settings["meals"] = [{"name": "Lunch", "time": "12:00", "duration_minutes": 30}]
    assert client.put("/api/settings", json=settings).status_code == 200
    cls = client.post("/api/classes", json={"title": "Fixed", "date": "2026-11-10", "start_time": "09:00", "end_time": "10:00"}).json()
    first = generate(client)
    assert len(first["blocks"]) == 2
    cls.update(start_time="10:00", end_time="11:00")
    assert client.put(f"/api/classes/{cls['id']}", json=cls).status_code == 200
    settings["meals"][0]["time"] = "13:00"
    assert client.put("/api/settings", json=settings).status_code == 200
    changed = generate(client)
    assert next(b for b in changed["blocks"] if b["kind"] == "class")["start"][11:16] == "10:00"
    assert next(b for b in changed["blocks"] if b["kind"] == "meal")["start"][11:16] == "13:00"
    assert client.delete(f"/api/classes/{cls['id']}").status_code == 204
    settings["meals"] = []
    assert client.put("/api/settings", json=settings).status_code == 200
    assert generate(client)["blocks"] == []


def test_invalid_edit_does_not_commit_progress(client):
    simple_settings(client)
    task(client)
    schedule = generate(client)
    blocks = deepcopy(schedule["blocks"])
    selected = next(block for block in blocks if block["kind"] == "task")
    selected.update(start="2026-11-10T07:00:00-05:00", status="completed")
    response = client.put(f"/api/schedules/{schedule['id']}", json={"blocks": blocks})
    assert response.status_code in (409, 422)
    assert client.get("/api/tasks").json()[0]["remaining_minutes"] == 50


def test_exports_and_demo_additive(client):
    personal = task(client, title="My real task")
    first = client.post("/api/demo").json()
    second = client.post("/api/demo").json()
    assert len(first["tasks"]) == len(second["tasks"]) == 4
    assert any(item["id"] == personal["id"] for item in second["tasks"])
    simple_settings(client)
    schedule = generate(client)
    response = client.get(f"/api/schedules/{schedule['id']}/export?format=ics")
    assert response.status_code == 200
    assert "BEGIN:VCALENDAR" in response.text and "DTSTART:" in response.text
    response = client.get(f"/api/schedules/{schedule['id']}/export?format=csv")
    assert response.status_code == 200 and "Title,Kind,Start,End" in response.text
    assert client.get(f"/api/schedules/{schedule['id']}/export?format=bad").status_code == 422


def test_route_offline_override_and_search_error(client):
    origin = client.post("/api/locations", json={"name": "A", "lat": 43.47, "lon": -80.54}).json()
    destination = client.post("/api/locations", json={"name": "B", "lat": 43.48, "lon": -80.55}).json()
    response = client.post("/api/route", json={"origin_id": origin["id"], "destination_id": destination["id"]})
    assert response.status_code == 200 and response.json()["estimated"]
    origin["travel_overrides"] = {destination["id"]: 15}
    assert client.put(f"/api/locations/{origin['id']}", json=origin).status_code == 200
    response = client.post("/api/route", json={"origin_id": origin["id"], "destination_id": destination["id"]})
    assert response.json()["minutes"] == 15 and not response.json()["estimated"]
    assert client.post("/api/geocode", json={"query": "Waterloo"}).status_code == 503


def test_persistence_and_repeat_migration(tmp_path):
    path = tmp_path / "persistent.db"
    with TestClient(create_app(path)) as client:
        created = task(client, title="Survives restarts")
    with TestClient(create_app(path)) as client:
        assert client.get("/api/tasks").json()[0]["id"] == created["id"]
        state = client.get("/api/state").json()
        assert state["settings"]["theme"] == "light"


def test_utc_serialization_does_not_move_locked_blocks(client):
    settings = simple_settings(client)
    settings["timezone"] = "UTC"
    client.put("/api/settings", json=settings)
    client.post("/api/classes", json={"title": "Fixed", "date": "2026-11-10", "start_time": "09:00", "end_time": "10:00"})
    schedule = generate(client)
    # Pydantic serializes +00:00 as Z. Equality must compare instants, not strings.
    response = client.put(f"/api/schedules/{schedule['id']}", json={"blocks": schedule["blocks"]})
    assert response.status_code == 200, response.text
