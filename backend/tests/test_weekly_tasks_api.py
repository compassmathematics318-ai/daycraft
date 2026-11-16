"""Canonical weekly work, exact-minute sessions, progress and compatibility."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text

from backend.app import work_confirmation
from backend.app.database import Configuration, Entity, LogicalSession, Schedule, TaskChunk, TaskDefinition, TaskWeek, build_database
from backend.app.main import create_app
from backend.app.migrate import migrate
from backend.app.schemas import Settings, sunday_of


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "tasks.sqlite")) as value:
        yield value


def definition(client, **values):
    response = client.post("/api/task-definitions", json={"title": "Read a chapter", "session_minutes": 60, "importance": 5, "difficulty": 5, **values})
    assert response.status_code == 201, response.text
    return response.json()


def assignment(client, task, week="2030-11-10", **values):
    response = client.post("/api/task-weeks", json={"task_definition_id": task["id"], "week_start": week, "min_sessions_per_week": 1, **values})
    assert response.status_code == 201, response.text
    return response.json()


def writable(value):
    return {key: item for key, item in value.items() if key not in ("legacy_task_id", "scheduling_model")}


def settings(client, end="09:00"):
    value = client.get("/api/state").json()["settings"]
    value.update(work_start="08:00", work_end=end, focus_minutes=120, meals=[], break_minutes=0, travel_buffer_minutes=0)
    assert client.put("/api/settings", json=value).status_code == 200


def generate(client, date="2030-11-10"):
    response = client.post("/api/schedules/generate", json={"date": date})
    assert response.status_code == 200, response.text
    return response.json()


def after_work(monkeypatch, block):
    """Confirmation tests run at the saved end, never at an implicit real date."""
    instant = datetime.fromisoformat(block["end"])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(work_confirmation, "datetime", Clock)


def test_definition_all_metadata_and_no_unassigned_work(client):
    settings(client)
    task = definition(client, task_type="academic", academic_subtype="assignment", due_at="2030-11-12T17:00:00-05:00", assessment_at="2030-11-13T09:00:00-05:00", deadline_at="2030-11-14T17:00:00-05:00", course="CS246", earliest_start="2030-11-10T08:00:00-05:00", preferred_start="08:00", preferred_end="09:00", description="Explicit context", importance=8.5, difficulty=6.5, allow_splitting=True, min_chunk_minutes=20)
    assert client.get("/api/task-definitions").json() == [task]
    assert client.get("/api/state").json()["task_definitions"] == [task]
    assert client.get("/api/state").json()["tasks"][0]["remaining_minutes"] == 0
    assert generate(client)["blocks"] == []
    updated = {**writable(task), "title": "Revised definition", "session_minutes": 137}
    response = client.put(f"/api/task-definitions/{task['id']}", json=updated)
    assert response.status_code == 200, response.text
    assert response.json()["session_minutes"] == 137
    assert client.delete(f"/api/task-definitions/{task['id']}").status_code == 204


@pytest.mark.parametrize("invalid", [{"session_minutes": 0}, {"session_minutes": True}, {"session_minutes": 1.5}, {"min_sessions_per_week": -1}, {"min_sessions_per_week": True}, {"importance": 1.25}, {"importance": True}, {"difficulty": -1}, {"task_type": "bad"}, {"task_type": "academic", "academic_subtype": "guess"}, {"due_at": "2030-11-11"}, {"assessment_at": "2030-11-11"}, {"earliest_start": "2030-11-11"}, {"allow_splitting": True, "session_minutes": 5, "min_chunk_minutes": 6}, {"project_id": "missing"}, {"related_activity_id": "missing"}, {"unknown": "never silently stored"}])
def test_definition_validation(client, invalid):
    response = client.post("/api/task-definitions", json={"title": "Invalid", **invalid})
    assert response.status_code == 422, response.text


def test_huge_duration_target_are_metadata_not_materialized_rows(client):
    task = definition(client, session_minutes=9007199254740991, min_sessions_per_week=9007199254740991)
    week = assignment(client, task, min_sessions_per_week=9007199254740991)
    assert week["sessions"] == []
    assert week["session_minutes"] == 9007199254740991
    assert week["min_sessions_per_week"] == 9007199254740991
    with client.app.state.session_factory() as db:
        assert list(db.scalars(select(LogicalSession))) == []


def test_assignment_sunday_boundary_reuse_and_independent_progress(client):
    task = definition(client)
    first = assignment(client, task, week="2030-11-12", min_sessions_per_week=3)
    second = assignment(client, task, week="2030-11-17", min_sessions_per_week=1)
    assert first["week_start"] == "2030-11-10"
    assert client.get("/api/task-week?week_start=2030-11-16").json()["week_end"] == "2030-11-16"
    assert client.post("/api/task-weeks", json={"task_definition_id": task["id"], "week_start": "2030-11-13"}).status_code == 409
    logged = client.post("/api/task-sessions", json={"assignment_id": first["id"]})
    assert logged.status_code == 201, logged.text
    assert logged.json()["completed_minutes"] == 60
    one = client.get("/api/task-week?week_start=2030-11-10").json()
    two = client.get("/api/task-week?week_start=2030-11-17").json()
    assert one["summary"]["completed_sessions"] == 1
    assert one["summary"]["target_sessions"] == 3
    assert two["summary"]["completed_sessions"] == 0
    assert two["assignments"][0]["id"] == second["id"]
    assert client.delete(f"/api/task-weeks/{first['id']}").status_code == 204
    removed = client.get("/api/task-week?week_start=2030-11-10").json()
    assert removed["assignments"] == []
    assert removed["history_assignments"][0]["completed_minutes"] == 60
    assert client.delete(f"/api/task-weeks/{second['id']}").status_code == 204
    assert len(client.get("/api/task-definitions").json()) == 1


def test_closing_week_never_fabricates_completed_sessions(client):
    task = definition(client)
    week = assignment(client, task, min_sessions_per_week=100)
    response = client.put(f"/api/task-weeks/{week['id']}", json={"task_definition_id": task["id"], "week_start": week["week_start"], "min_sessions_per_week": 100, "status": "completed"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    assert response.json()["completed_sessions"] == response.json()["completed_minutes"] == 0
    assert response.json()["sessions"] == []


@pytest.mark.parametrize("duration", [1, 7, 137])
def test_assigned_exact_minute_work_and_week_eligibility(client, duration):
    settings(client, end="12:00")
    task = definition(client, session_minutes=duration, allow_splitting=False)
    week = assignment(client, task)
    result = generate(client)
    blocks = [item for item in result["blocks"] if item.get("task_id") == task["id"]]
    assert len(blocks) == 1, result
    block = blocks[0]
    assert round((datetime.fromisoformat(block["end"]) - datetime.fromisoformat(block["start"])).total_seconds() / 60) == duration
    assert block["task_assignment_id"] == week["id"]
    assert block["logical_session_id"]
    assert not any(item.get("task_id") == task["id"] for item in generate(client, "2030-11-17")["blocks"])
    saved = client.get("/api/task-week?week_start=2030-11-10").json()
    assert saved["summary"]["scheduled_sessions"] == 1
    assert saved["summary"]["completed_sessions"] == 0
    assert saved["summary"]["remaining_minutes"] == duration


def test_minimum_lowering_preserves_actual_sessions_and_chunk_history(client):
    settings(client)
    task = definition(client)
    week = assignment(client, task)
    generated = generate(client)
    old_blocks = deepcopy(generated["blocks"])
    response = client.put(f"/api/task-weeks/{week['id']}", json={"task_definition_id": task["id"], "week_start": week["week_start"], "min_sessions_per_week": 0, "session_minutes": 90})
    assert response.status_code == 200, response.text
    assert response.json()["sessions"][0]["target_minutes"] == 60
    assert client.get("/api/schedules").json()[0]["blocks"] == old_blocks


@pytest.mark.parametrize("original,new_duration,expected_target", [(137, 60, 257), (60, 137, 334)])
def test_mixed_session_snapshots_preserve_exact_weekly_workload(client, original, new_duration, expected_target):
    task = definition(client, session_minutes=original)
    week = assignment(client, task, min_sessions_per_week=3)
    logged = client.post("/api/task-sessions", json={"assignment_id": week["id"], "completed_minutes": 20})
    assert logged.status_code == 201, logged.text
    response = client.put(f"/api/task-weeks/{week['id']}", json={"task_definition_id": task["id"], "week_start": week["week_start"], "min_sessions_per_week": 3, "session_minutes": new_duration})
    assert response.status_code == 200, response.text
    assert response.json()["sessions"][0]["target_minutes"] == original
    assert response.json()["target_minutes"] == expected_target
    assert response.json()["remaining_minutes"] == expected_target - 20
    state = client.get("/api/task-week?week_start=2030-11-10").json()
    assert state["summary"]["target_minutes"] == expected_target
    assert state["summary"]["remaining_minutes"] == expected_target - 20


def test_manual_chunk_completion_idempotence_undo_and_identity_forgery(client, monkeypatch):
    settings(client)
    task = definition(client)
    assignment(client, task)
    result = generate(client)
    blocks = deepcopy(result["blocks"])
    work = next(item for item in blocks if item.get("logical_session_id"))
    after_work(monkeypatch, work)
    forged = deepcopy(blocks)
    forged[blocks.index(work)]["logical_session_id"] = "other-session"
    assert client.put(f"/api/schedules/{result['id']}", json={"blocks": forged}).status_code == 422
    work["status"] = "completed"
    response = client.put(f"/api/schedules/{result['id']}", json={"blocks": blocks})
    assert response.status_code == 200, response.text
    assert client.put(f"/api/schedules/{result['id']}", json={"blocks": response.json()["blocks"]}).status_code == 200
    progress = client.get("/api/task-week?week_start=2030-11-10").json()
    assert progress["summary"]["completed_sessions"] == 1
    assert progress["summary"]["scheduled_sessions"] == 0
    assert progress["summary"]["completed_minutes"] == 60
    undo = deepcopy(response.json()["blocks"])
    next(item for item in undo if item.get("logical_session_id"))["status"] = "todo"
    response = client.put(f"/api/schedules/{result['id']}", json={"blocks": undo})
    assert response.status_code == 200, response.text
    assert client.get("/api/task-week?week_start=2030-11-10").json()["summary"]["completed_minutes"] == 0


def test_partial_manual_baseline_survives_chunk_complete_and_undo(client, monkeypatch):
    settings(client)
    task = definition(client, allow_splitting=True, min_chunk_minutes=20)
    week = assignment(client, task)
    logged = client.post("/api/task-sessions", json={"assignment_id": week["id"], "completed_minutes": 20}).json()
    # Force all remaining weekly capacity into the chosen day for one 40m chunk.
    updated = {**writable(task), "due_at": None, "deadline_at": "2030-11-10T09:00:00-05:00"}
    assert client.put(f"/api/task-definitions/{task['id']}", json=updated).status_code == 200
    result = generate(client)
    work = next(item for item in result["blocks"] if item.get("logical_session_id") == logged["id"])
    after_work(monkeypatch, work)
    blocks = deepcopy(result["blocks"])
    next(item for item in blocks if item["id"] == work["id"])["status"] = "completed"
    saved = client.put(f"/api/schedules/{result['id']}", json={"blocks": blocks})
    assert saved.status_code == 200, saved.text
    assert client.get("/api/task-week?week_start=2030-11-10").json()["summary"]["completed_minutes"] == 60
    blocks = saved.json()["blocks"]
    next(item for item in blocks if item["id"] == work["id"])["status"] = "todo"
    saved = client.put(f"/api/schedules/{result['id']}", json={"blocks": blocks})
    assert saved.status_code == 200, saved.text
    assert client.get("/api/task-week?week_start=2030-11-10").json()["summary"]["completed_minutes"] == 20


def test_past_pending_chunks_reserve_same_logical_work_until_skipped(client):
    settings(client, end="08:20")
    task = definition(client, allow_splitting=True, min_chunk_minutes=20, deadline_at="2030-11-11T09:00:00-05:00")
    assignment(client, task)
    sunday = generate(client)
    sunday_work = [item for item in sunday["blocks"] if item.get("logical_session_id")]
    assert sum(round((datetime.fromisoformat(item["end"]) - datetime.fromisoformat(item["start"])).total_seconds() / 60) for item in sunday_work) == 20
    settings(client, end="09:00")
    monday = generate(client, "2030-11-11")
    monday_work = [item for item in monday["blocks"] if item.get("logical_session_id") == sunday_work[0]["logical_session_id"]]
    planned = client.get("/api/task-week?week_start=2030-11-10").json()["sessions"][0]["planned_minutes"]
    assert planned == 60, {"planned_minutes": planned, "sunday": sunday_work, "monday": monday_work}


def test_project_deletion_detaches_new_definition_without_losing_week_work(client):
    container = client.post("/api/projects", json={"name": "Vector"}).json()
    task = definition(client, project_id=container["id"])
    week = assignment(client, task)
    assert client.delete(f"/api/projects/{container['id']}").status_code == 409
    assert client.delete(f"/api/projects/{container['id']}?detach_tasks=true").status_code == 204
    assert client.get("/api/task-definitions").json()[0]["project_id"] is None
    assert client.get("/api/task-week?week_start=2030-11-10").json()["assignments"][0]["id"] == week["id"]


def test_paused_project_weekly_exclusion_names_task_and_reason(client):
    settings(client)
    container = client.post("/api/projects", json={"name": "Paused Vector", "status": "paused"}).json()
    task = definition(client, title="Implement semantic processor", project_id=container["id"])
    week = assignment(client, task, min_sessions_per_week=2)
    result = generate(client)
    assert not any(item.get("task_id") == task["id"] for item in result["blocks"])
    excluded = [item for item in result["excluded_tasks"] if item["task_id"] == task["id"]]
    assert len(excluded) == 1
    assert excluded[0]["title"] == task["title"]
    assert excluded[0]["task_assignment_id"] == week["id"]
    assert excluded[0]["project_id"] == container["id"]
    assert excluded[0]["minutes"] == 120
    assert "Paused Vector" in excluded[0]["reason"] and "paused" in excluded[0]["reason"]
    progress = next(item for item in result["weekly_progress"] if item["task_definition_id"] == task["id"])
    assert progress["title"] == task["title"]
    assert progress["exclusion_reason"] == excluded[0]["reason"]


def test_canonical_legacy_definition_edits_are_used_by_compatibility_api(client):
    old = client.post("/api/tasks", json={"title": "Old client task", "duration_minutes": 60, "remaining_minutes": 40}).json()
    task = client.get("/api/task-definitions").json()[0]
    assert task["scheduling_model"] == "legacy"
    updated = {**writable(task), "title": "Canonical title", "description": "Canonical context", "importance": 10, "session_minutes": 90}
    response = client.put(f"/api/task-definitions/{task['id']}", json=updated)
    assert response.status_code == 200, response.text
    projected = client.get("/api/tasks").json()[0]
    assert projected["title"] == "Canonical title" and projected["notes"] == "Canonical context"
    assert projected["remaining_minutes"] == 70  # original 20m completion survives
    assert projected["priority"] == 5 and projected["id"] == old["id"]


def test_switching_compatibility_work_to_weekly_keeps_finite_completion(client):
    old = client.post("/api/tasks", json={"title": "Finite", "duration_minutes": 120, "remaining_minutes": 80}).json()
    task = client.get("/api/task-definitions").json()[0]
    week = assignment(client, task)
    assert week["sessions"][0]["target_minutes"] == 120
    assert week["sessions"][0]["completed_minutes"] == 40
    assert week["remaining_minutes"] == 80
    assert client.get("/api/task-definitions").json()[0]["scheduling_model"] == "weekly"
    assert client.get("/api/tasks").json()[0]["id"] == old["id"]


def test_definition_project_edit_updates_legacy_link_and_context(client):
    first = client.post("/api/projects", json={"name": "First"}).json()
    second = client.post("/api/projects", json={"name": "Second"}).json()
    client.post("/api/tasks", json={"title": "Legacy work", "project_id": first["id"]})
    task = client.get("/api/task-definitions").json()[0]
    response = client.put(f"/api/task-definitions/{task['id']}", json={**writable(task), "project_id": second["id"]})
    assert response.status_code == 200, response.text
    assert client.get("/api/tasks").json()[0]["project_id"] == second["id"]
    assert client.delete(f"/api/projects/{first['id']}").status_code == 204


def test_migration_preserves_legacy_rows_and_finite_credit(tmp_path):
    path = tmp_path / "legacy.sqlite"
    engine, factory = build_database(path)
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0003_personal_projects")
    task = {"id": "old", "title": "Original", "kind": "academic", "duration_minutes": 120, "remaining_minutes": 80, "priority": 4, "notes": "Keep every field", "custom": {"original": True}, "status": "in_progress"}
    schedule = {"id": "saved", "date": "2026-11-10", "blocks": [{"id": "done", "task_id": "old", "kind": "task", "title": "Original", "start": "2026-11-10T08:00:00-05:00", "end": "2026-11-10T08:20:00-05:00", "status": "completed"}]}
    with factory() as db:
        db.add(Configuration(id="settings", payload=Settings().model_dump(mode="json")))
        db.add(Entity(collection="tasks", id="old", payload=task))
        db.add(Schedule(id="saved", date=schedule["date"], payload=schedule))
        db.commit()
    migrate(engine)
    migrate(engine)
    with factory() as db:
        assert db.get(Entity, ("tasks", "old")).payload == task
        assert db.get(Schedule, "saved").payload == schedule
        definition = db.get(TaskDefinition, "old")
        assert definition.legacy_snapshot == task and definition.scheduling_model == "weekly"
        week = db.scalar(select(TaskWeek))
        assert week.week_start == sunday_of(datetime.now().date()).isoformat()
        logical = db.scalar(select(LogicalSession))
        assert logical.target_minutes == 120 and logical.completed_minutes == 40
        assert logical.baseline_completed_minutes == 20
        assert db.get(TaskChunk, "done").credited_minutes == 20
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()
