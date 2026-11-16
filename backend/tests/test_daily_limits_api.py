"""Daily block limits, grouped map identity and room metadata preservation."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app.database import Activity, LogicalSession, Occurrence, Schedule, TaskDefinition, TaskWeek
from backend.app.main import create_app
from backend.app.migrate import migrate


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.db"))
    with TestClient(create_app(tmp_path / "planner.db")) as value:
        yield value


def post(client, path, **value):
    response = client.post("/api/" + path, json=value)
    assert response.status_code in (200, 201), response.text
    return response.json()


def writable(task):
    return {key: value for key, value in task.items() if key not in {"legacy_task_id", "scheduling_model"}}


@pytest.mark.parametrize("values", [
    {"min_sessions_per_day": True}, {"min_sessions_per_day": 1.5},
    {"min_sessions_per_day": -1}, {"min_sessions_per_day": None},
    {"min_sessions_per_day": "2"}, {"min_sessions_per_day": 9007199254740992},
    {"max_sessions_per_day": 0}, {"max_sessions_per_day": False},
    {"max_sessions_per_day": 1.5}, {"max_sessions_per_day": "3"},
    {"max_sessions_per_day": 9007199254740992},
    {"min_sessions_per_day": 3, "max_sessions_per_day": 2},
])
def test_daily_limit_validation_on_definition_and_week(client, values):
    assert client.post("/api/task-definitions", json={"title": "Invalid", **values}).status_code == 422
    task = post(client, "task-definitions", title="Valid")
    response = client.post("/api/task-weeks", json={"task_definition_id": task["id"], "week_start": "2030-11-10", "overrides": values})
    assert response.status_code == 422, response.text


def test_limits_defaults_override_copy_and_legacy_alias(client):
    default = post(client, "task-definitions", title="Default")
    assert default["min_sessions_per_day"] == 1 and default["max_sessions_per_day"] is None
    task = post(client, "task-definitions", title="Daily work", min_sessions_per_day=2, max_sessions_per_day=4, room="201")
    week = post(client, "task-weeks", task_definition_id=task["id"], week_start="2030-11-10", overrides={"min_sessions_per_day": 0, "max_sessions_per_day": None, "room": "202"})
    assert week["min_sessions_per_day"] == 0 and week["max_sessions_per_day"] is None
    assert week["effective_definition"]["room"] == "202"
    copy = post(client, "task-weeks/copy", source_week="2030-11-10", target_week="2030-11-17", deadline_policy="preserve")
    effective = copy["copied"][0]["effective_definition"]
    assert effective["min_sessions_per_day"] == 0 and effective["max_sessions_per_day"] is None and effective["room"] == "202"
    stored = next(item for item in client.get("/api/task-definitions").json() if item["id"] == task["id"])
    assert stored["min_sessions_per_day"] == 2 and stored["max_sessions_per_day"] == 4
    legacy = post(client, "tasks", title="Legacy", duration_minutes=60, remaining_minutes=30, min_sessions_per_day=2, max_sessions_per_day=3, room="L1")
    canonical = next(item for item in client.get("/api/task-definitions").json() if item["id"] == legacy["id"])
    assert canonical["room"] == "L1" and canonical["min_sessions_per_day"] == 2
    edited = client.put("/api/task-definitions/" + legacy["id"], json={**writable(canonical), "max_sessions_per_day": 5}).json()
    alias = next(item for item in client.get("/api/tasks").json() if item["id"] == edited["id"])
    assert alias["max_sessions_per_day"] == 5 and alias["remaining_minutes"] == 30


def test_room_reassignment_and_old_client_preservation(client):
    first = post(client, "locations", name="First", lat=43.47, lon=-80.54)
    second = post(client, "locations", name="Second", lat=43.48, lon=-80.54)
    activity = post(client, "activities", title="Group", category="commitment", subtype="Groupwork", location_id=first["id"], room="101", building="Legacy building")
    without_details = {key: value for key, value in activity.items() if key not in {"room", "building"}}
    updated = client.put("/api/activities/" + activity["id"], json={**without_details, "title": "Renamed"}).json()
    assert updated["room"] == "101" and updated["building"] == "Legacy building"
    changed = client.put("/api/activities/" + activity["id"], json={**without_details, "location_id": second["id"]}).json()
    assert changed["room"] == "" and changed["building"] == "Legacy building"
    task = post(client, "task-definitions", title="Room task", location_id=first["id"], room="T1", max_sessions_per_day=2)
    week = post(client, "task-weeks", task_definition_id=task["id"], week_start="2030-11-10", overrides={"location_id": second["id"]})
    assert week["effective_definition"]["room"] == ""
    assert client.get("/api/task-definitions").json()[0]["room"] == "T1"


def test_grouped_map_keeps_same_name_ids_and_all_nested_visits(client):
    place = post(client, "locations", name="Library", lat=43.47, lon=-80.54)
    first, second = [post(client, "activities", title="Same name", category="commitment", subtype="Personal", location_id=place["id"], room="101") for _ in range(2)]
    visits = []
    for day in (10, 11):
        visits.append(post(client, "occurrences", activity_id=first["id"], start=f"2030-11-{day}T09:00:00-05:00", end=f"2030-11-{day}T10:00:00-05:00"))
    before = client.get("/api/calendar?week_start=2030-11-10").json()
    overview = client.get("/api/location-overview?week_start=2030-11-10").json()
    refs = overview["locations"][0]["references"]
    assert len(refs) == 2 and {item["entity_id"] for item in refs} == {first["id"], second["id"]}
    group = next(item for item in refs if item["entity_id"] == first["id"])
    assert group["id"] == "activity:" + first["id"] and group["occurrence_count"] == 2
    assert {item["entity_id"] for item in group["occurrences"]} == {item["id"] for item in visits}
    assert all(item["start"] and item["edit_target"]["kind"] == "occurrence" for item in group["occurrences"])
    assert client.get("/api/calendar?week_start=2030-11-10").json() == before


def test_task_group_replaces_stale_default_and_preserves_real_historical_visit(client):
    first = post(client, "locations", name="First", lat=43.47, lon=-80.54)
    second = post(client, "locations", name="Second", lat=43.48, lon=-80.54)
    task = post(client, "task-definitions", title="Task", location_id=first["id"])
    post(client, "task-weeks", task_definition_id=task["id"], week_start="2026-11-08", overrides={"location_id": second["id"]})
    blocks = [{"id": f"chunk-{i}", "title": "Task", "kind": "task", "task_id": task["id"], "task_definition_id": task["id"], "location_id": first["id"], "location_mode": "required", "start": f"2026-11-10T{9+i:02}:00:00-05:00", "end": f"2026-11-10T{10+i:02}:00:00-05:00", "status": "completed"} for i in range(2)]
    with client.app.state.session_factory() as db:
        db.add(Schedule(id="history", date="2026-11-10", payload={"blocks": blocks, "status": "stale"}))
        db.commit()
    overview = client.get("/api/location-overview?week_start=2026-11-08").json()
    by_id = {item["id"]: item for item in overview["locations"]}
    assert len(by_id[first["id"]]["references"]) == 1
    assert by_id[first["id"]]["references"][0]["occurrence_count"] == 2
    assert len(by_id[second["id"]]["references"]) == 1
    assert by_id[second["id"]]["references"][0]["occurrence_count"] == 0
    with client.app.state.session_factory() as db:
        assert db.get(Schedule, "history").payload["blocks"] == blocks


def test_read_defaults_and_migration_do_not_rewrite_payloads_or_progress(client):
    task = post(client, "task-definitions", title="Preserve")
    week = post(client, "task-weeks", task_definition_id=task["id"], week_start="2030-11-10")
    with client.app.state.session_factory() as db:
        row = db.get(TaskDefinition, task["id"])
        row.payload = {key: value for key, value in row.payload.items() if key not in {"room", "min_sessions_per_day", "max_sessions_per_day"}}
        db.add(LogicalSession(id="progress", assignment_id=week["id"], index=0, target_minutes=60, completed_minutes=20, baseline_completed_minutes=20, status="in_progress"))
        db.commit()
        before = {model.__name__: deepcopy([dict(row.__dict__) for row in db.scalars(select(model))]) for model in (TaskDefinition, TaskWeek, LogicalSession, Activity, Occurrence, Schedule)}
        for rows in before.values():
            for item in rows:
                item.pop("_sa_instance_state", None)
        engine = db.get_bind()
    migrate(engine)
    assert client.get("/api/task-definitions").json()[0]["min_sessions_per_day"] == 1
    assert client.get("/api/task-week?week_start=2030-11-10").json()["assignments"][0]["effective_definition"]["max_sessions_per_day"] is None
    with client.app.state.session_factory() as db:
        for model in (TaskDefinition, TaskWeek, LogicalSession, Activity, Occurrence, Schedule):
            after = [{key: value for key, value in row.__dict__.items() if key != "_sa_instance_state"} for row in db.scalars(select(model))]
            assert after == before[model.__name__]


def test_manual_edits_recompute_daily_progress_when_removed_skipped_or_added(client):
    settings = client.get("/api/state").json()["settings"]
    settings.update(work_start="09:00", work_end="12:00", focus_minutes=60, break_minutes=0, travel_buffer_minutes=0, meals=[])
    assert client.put("/api/settings", json=settings).status_code == 200
    task = post(client, "tasks", title="Manual count", duration_minutes=120, remaining_minutes=120, min_session_minutes=25, max_session_minutes=60, min_sessions_per_day=2, max_sessions_per_day=3)
    generated = post(client, "schedules/generate", date="2030-11-10", mode="balanced")
    work = [item for item in generated["blocks"] if item.get("task_id") == task["id"]]
    assert len(work) == 2, generated
    assert generated["daily_progress"][0]["scheduled_sessions"] == 2

    def save(blocks):
        response = client.put("/api/schedules/" + generated["id"], json={"blocks": blocks})
        assert response.status_code == 200, response.text
        result = response.json()
        assert client.get("/api/schedules?date=2030-11-10").json()[0]["daily_progress"] == result["daily_progress"]
        return result["daily_progress"]

    single = save([work[0]])
    assert single[0]["scheduled_sessions"] == 1 and single[0]["expected_shortfall"] == 1
    assert save([{**work[0], "status": "skipped"}]) == []
    restored = save(work)
    assert restored[0]["scheduled_sessions"] == 2 and restored[0]["expected_shortfall"] == 0
