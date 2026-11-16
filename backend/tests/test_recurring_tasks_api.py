"""Regression coverage for recurrence writes and finite-to-recurring conversion."""
from datetime import datetime

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app.database import LogicalSession, TaskWeek
from backend.app.main import create_app
from backend.app import task_recurrence


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "tasks.sqlite")) as value:
        settings = value.get("/api/state").json()["settings"]
        settings.update(work_start="08:00", work_end="12:00", focus_minutes=120, meals=[], break_minutes=0, travel_buffer_minutes=0)
        assert value.put("/api/settings", json=settings).status_code == 200
        yield value


def create(client, **fields):
    response = client.post("/api/task-definitions", json={"title": "Recurring practice", "session_minutes": 30, "importance": 1, "recurrence": {"start_week": "2030-11-10"}, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def writable(task):
    return {key: value for key, value in task.items() if key not in ("legacy_task_id", "scheduling_model")}


def week(client, day="2030-11-10"):
    return client.get(f"/api/task-week?week_start={day}").json()


def test_no_required_dates_or_future_materialization(client):
    task = create(client, recurrence={"kind": "weekly"})
    assert task["recurrence"]["start_week"]
    assert task["recurrence"]["end_week"] is None
    assert len(week(client, "2099-12-31")["assignments"]) == 1
    with client.app.state.session_factory() as db:
        assert list(db.scalars(select(TaskWeek))) == []
    assert client.post("/api/task-definitions", json={"title": "Invalid absolute cutoff", "recurrence": {}, "due_at": "2030-11-11T17:00:00-05:00"}).status_code == 422


@pytest.mark.parametrize("status", ["paused", "archived"])
def test_inactive_explicit_week_opt_in_and_omitted_preservation(client, status):
    task = create(client, status=status)
    assignment = week(client)["assignments"][0]
    payload = {"task_definition_id": task["id"], "week_start": assignment["week_start"], "allow_inactive": True}
    response = client.put(f"/api/task-weeks/{assignment['id']}", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["allow_inactive"] is True
    assert response.json()["effective_definition"]["status"] == "active"
    payload.pop("allow_inactive")
    response = client.put(f"/api/task-weeks/{assignment['id']}", json={**payload, "notes": "Keep the explicit opt-in"})
    assert response.status_code == 200 and response.json()["allow_inactive"] is True
    generated = client.post("/api/schedules/generate", json={"date": "2030-11-10"})
    assert generated.status_code == 200, generated.text
    assert any(block.get("task_id") == task["id"] for block in generated.json()["blocks"])
    later = week(client, "2030-11-17")["assignments"][0]
    assert not later["allow_inactive"]
    assert later["effective_definition"]["status"] == status


def test_default_edits_leave_prior_session_targets_and_future_week_overrides(client):
    task = create(client)
    first = week(client)["assignments"][0]
    logged = client.post("/api/task-sessions", json={"assignment_id": first["id"]}).json()
    second = week(client, "2030-11-17")["assignments"][0]
    response = client.put(f"/api/task-weeks/{second['id']}", json={"task_definition_id": task["id"], "week_start": second["week_start"], "session_minutes": 45, "min_sessions_per_week": 3})
    assert response.status_code == 200, response.text
    response = client.put(f"/api/task-definitions/{task['id']}", json={**writable(task), "session_minutes": 75, "min_sessions_per_week": 2})
    assert response.status_code == 200, response.text
    assert week(client)["sessions"][0]["id"] == logged["id"]
    assert week(client)["sessions"][0]["target_minutes"] == 30
    assert week(client)["sessions"][0]["completed_minutes"] == 30
    assert week(client)["assignments"][0]["session_minutes"] == 75
    assert week(client)["assignments"][0]["min_sessions_per_week"] == 2
    fresh = client.post("/api/task-sessions", json={"assignment_id": first["id"]})
    assert fresh.status_code == 201, fresh.text
    assert fresh.json()["target_minutes"] == 75
    assert week(client)["sessions"][0]["target_minutes"] == 30
    assert week(client, "2030-11-17")["assignments"][0]["session_minutes"] == 45
    assert week(client, "2030-11-24")["assignments"][0]["session_minutes"] == 75


def test_historical_materialized_metadata_and_targets_stay_frozen(client, monkeypatch):
    task = create(client, title="Original historical title")
    assignment = week(client)["assignments"][0]
    assert client.post("/api/task-sessions", json={"assignment_id": assignment["id"]}).status_code == 201

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2030, 11, 20, 12, tzinfo=tz)

    monkeypatch.setattr(task_recurrence, "datetime", Later)
    response = client.put(f"/api/task-definitions/{task['id']}", json={**writable(task), "title": "Updated future title", "session_minutes": 90, "min_sessions_per_week": 4})
    assert response.status_code == 200, response.text
    historical = week(client)["assignments"][0]
    assert historical["effective_definition"]["title"] == "Original historical title"
    assert historical["session_minutes"] == 30
    assert historical["min_sessions_per_week"] == 1
    assert historical["completed_minutes"] == 30
    later = week(client, "2030-11-24")["assignments"][0]
    assert later["effective_definition"]["title"] == "Updated future title"
    assert later["session_minutes"] == 90
    assert later["min_sessions_per_week"] == 4


def test_legacy_conversion_reuses_identity_keeps_credit_and_removes_finite_limit(client):
    response = client.post("/api/tasks", json={"title": "Legacy finite", "duration_minutes": 60, "remaining_minutes": 40})
    assert response.status_code == 201, response.text
    key = response.json()["id"]
    task = next(item for item in client.get("/api/task-definitions").json() if item["id"] == key)
    response = client.put(f"/api/task-definitions/{key}", json={**writable(task), "recurrence": {"kind": "weekly"}, "min_sessions_per_week": 3, "due_at": None, "assessment_at": None, "deadline_at": None, "earliest_start": None})
    assert response.status_code == 200, response.text
    converted = response.json()
    assert converted["id"] == key and converted["scheduling_model"] == "weekly"
    current = week(client, converted["recurrence"]["start_week"])
    assert current["summary"]["completed_minutes"] == 20
    assert current["assignments"][0]["min_sessions_per_week"] == 3
    assert not current["assignments"][0].get("legacy_finite")
    assert client.put(f"/api/tasks/{key}", json={"id": key, "title": "Cannot erase recurrence", "duration_minutes": 60, "remaining_minutes": 40}).status_code == 409
    assert len(client.get("/api/task-definitions").json()) == 1


def test_override_validation_uses_effective_splitting_and_week_session_duration(client):
    task = create(client, allow_splitting=True, min_chunk_minutes=20)
    assignment = week(client)["assignments"][0]
    payload = {"task_definition_id": task["id"], "week_start": assignment["week_start"], "session_minutes": 10}
    assert client.put(f"/api/task-weeks/{assignment['id']}", json={**payload, "overrides": {"min_chunk_minutes": 15}}).status_code == 422
    response = client.put(f"/api/task-weeks/{assignment['id']}", json={**payload, "overrides": {"allow_splitting": False}})
    assert response.status_code == 200, response.text


def test_copy_shift_into_dst_gap_rejects_atomically(client):
    task = create(client, recurrence=None, due_at="2031-03-02T02:30:00-05:00")
    assert client.post("/api/task-weeks", json={"task_definition_id": task["id"], "week_start": "2031-03-02"}).status_code == 201
    response = client.post("/api/task-weeks/copy", json={"source_week": "2031-03-02", "target_week": "2031-03-09", "deadline_policy": "shift"})
    assert response.status_code == 422, response.text
    assert week(client, "2031-03-09")["assignments"] == []
    with client.app.state.session_factory() as db:
        assert list(db.scalars(select(LogicalSession))) == []
