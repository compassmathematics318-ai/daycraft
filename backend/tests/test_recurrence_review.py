"""Independent recurrence/copy preservation and malformed-write review."""
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app.database import LogicalSession, Schedule, TaskChunk, TaskWeek
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "review.sqlite")) as value:
        settings = value.get("/api/state").json()["settings"]
        settings.update(work_start="08:00", work_end="11:00", focus_minutes=120,
                        meals=[], break_minutes=0, travel_buffer_minutes=0)
        assert value.put("/api/settings", json=settings).status_code == 200
        yield value


def create(client, **values):
    response = client.post("/api/task-definitions", json={"title": "Independent recurring review", "session_minutes": 30, "importance": 1, "recurrence": {"start_week": "2030-11-10"}, **values})
    assert response.status_code == 201, response.text
    return response.json()


def week(client, date="2030-11-10"):
    response = client.get(f"/api/task-week?week_start={date}")
    assert response.status_code == 200, response.text
    return response.json()


def edit_week(client, assignment, **values):
    return client.put(f"/api/task-weeks/{assignment['id']}", json={
        "task_definition_id": assignment["task_definition_id"],
        "week_start": assignment["week_start"], **values,
    })


def test_reading_far_future_recurrence_is_lazy_and_progress_independent(client):
    create(client)
    for date in ("2030-11-10", "2030-11-17", "2099-12-31"):
        state = week(client, date)
        assert len(state["assignments"]) == 1
        assert state["assignments"][0]["is_virtual"]
        assert not state["sessions"]
    with client.app.state.session_factory() as db:
        assert not list(db.scalars(select(TaskWeek)))
        assert not list(db.scalars(select(LogicalSession)))
    first = week(client)["assignments"][0]
    response = client.post("/api/task-sessions", json={"assignment_id": first["id"]})
    assert response.status_code == 201, response.text
    assert week(client)["summary"]["completed_sessions"] == 1
    assert week(client, "2030-11-17")["summary"]["completed_sessions"] == 0
    with client.app.state.session_factory() as db:
        assert len(list(db.scalars(select(TaskWeek)))) == 1


def test_week_override_isolated_and_skip_preserves_history(client):
    task = create(client, min_sessions_per_week=2)
    original = week(client)["assignments"][0]
    response = edit_week(client, original, session_minutes=45, min_sessions_per_week=3,
                         overrides={"title": "One week only", "difficulty": 9.5})
    assert response.status_code == 200, response.text
    overridden = response.json()
    assert overridden["effective_definition"]["title"] == "One week only"
    assert overridden["session_minutes"] == 45
    assert client.post("/api/task-sessions", json={"assignment_id": original["id"]}).status_code == 201
    future = week(client, "2030-11-17")["assignments"][0]
    assert future["session_minutes"] == 30
    assert future["min_sessions_per_week"] == 2
    assert future["effective_definition"]["title"] == task["title"]
    response = edit_week(client, overridden, status="skipped", session_minutes=45, min_sessions_per_week=3,
                         overrides=overridden["overrides"])
    assert response.status_code == 200, response.text
    assert week(client)["summary"]["completed_minutes"] == 45
    plan = client.post("/api/schedules/generate", json={"date": "2030-11-10"})
    assert plan.status_code == 200, plan.text
    assert not any(block.get("task_id") == task["id"] for block in plan.json()["blocks"])


@pytest.mark.parametrize("override", [{"importance": True}, {"difficulty": 1.25}, {"task_type": "unknown"},
                                      {"preferred_days": [7]}, {"dependencies": ["missing"]},
                                      {"project_id": None}, {"session_minutes": 0}])
def test_week_overrides_cannot_bypass_definition_validation(client, override):
    create(client)
    original = week(client)["assignments"][0]
    response = edit_week(client, original, overrides=override)
    assert response.status_code == 422, response.text
    assert week(client)["assignments"][0]["overrides"] == {}


def test_crafted_recurring_identity_cannot_create_a_midweek_assignment(client):
    task = create(client)
    response = client.post("/api/task-sessions", json={
        "assignment_id": f"recurring:{task['id']}:2030-11-12",
    })
    assert response.status_code in (404, 422), response.text
    with client.app.state.session_factory() as db:
        assert not list(db.scalars(select(TaskWeek)))
        assert not list(db.scalars(select(LogicalSession)))


def test_pause_archive_exclude_future_work_without_erasing_progress(client):
    task = create(client)
    original = week(client)["assignments"][0]
    assert client.post("/api/task-sessions", json={"assignment_id": original["id"]}).status_code == 201
    writable = {key: value for key, value in task.items() if key not in {"legacy_task_id", "scheduling_model"}}
    for status in ("paused", "archived"):
        response = client.put(f"/api/task-definitions/{task['id']}", json={**writable, "status": status})
        assert response.status_code == 200, response.text
        response = client.post("/api/schedules/generate", json={"date": "2030-11-17"})
        assert response.status_code == 200, response.text
        assert not any(block.get("task_id") == task["id"] for block in response.json()["blocks"])
        assert week(client)["summary"]["completed_minutes"] == 30
    with client.app.state.session_factory() as db:
        assert not list(db.scalars(select(TaskChunk)))
        assert len(list(db.scalars(select(LogicalSession)))) == 1
        assert len(list(db.scalars(select(Schedule)))) == 1


def test_copy_preview_selection_dedup_and_no_progress_or_schedule_cloning(client):
    recurring = create(client)
    explicit = create(client, title="Copy this finite task", recurrence=None,
                      due_at="2030-11-15T17:00:00-05:00", importance=8.5,
                      difficulty=6.5, description="Retain this metadata")
    excluded = create(client, title="Not selected", recurrence=None)
    for task in (explicit, excluded):
        response = client.post("/api/task-weeks", json={"task_definition_id": task["id"], "week_start": "2030-11-10", "session_minutes": 45, "min_sessions_per_week": 3})
        assert response.status_code == 201, response.text
    assignment = next(item for item in week(client)["assignments"] if item["task_definition_id"] == explicit["id"])
    assert client.post("/api/task-sessions", json={"assignment_id": assignment["id"]}).status_code == 201
    plan = client.post("/api/schedules/generate", json={"date": "2030-11-10"})
    assert plan.status_code == 200, plan.text
    before = client.get("/api/schedules").json()
    assert before
    payload = {"source_week": "2030-11-10", "target_week": "2031-01-05", "deadline_policy": "preserve", "definition_ids": [explicit["id"], recurring["id"]]}
    assert client.post("/api/task-weeks/copy", json={key: item for key, item in payload.items() if key != "deadline_policy"}).status_code == 422
    response = client.post("/api/task-weeks/copy", json={**payload, "preview": True})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert len(preview["copied"]) == 1
    assert [item["task_definition_id"] for item in preview["skipped"]] == [recurring["id"]]
    assert not any(item["task_definition_id"] == explicit["id"] for item in week(client, "2031-01-05")["assignments"])
    response = client.post("/api/task-weeks/copy", json=payload)
    assert response.status_code == 200, response.text
    copied = response.json()["copied"][0]
    assert copied["task_definition_id"] == explicit["id"]
    assert copied["status"] == "todo"
    assert copied["session_minutes"] == 45 and copied["min_sessions_per_week"] == 3
    assert copied["completed_minutes"] == copied["planned_minutes"] == 0
    assert copied["sessions"] == []
    assert copied["effective_definition"]["due_at"] == explicit["due_at"]
    assert copied["effective_definition"]["description"] == explicit["description"]
    assert copied["effective_definition"]["difficulty"] == explicit["difficulty"]
    assert copied["effective_definition"]["importance"] == explicit["importance"]
    again = client.post("/api/task-weeks/copy", json=payload).json()
    assert not again["copied"] and len(again["skipped"]) == 2
    assert client.get("/api/schedules").json() == before
    assert week(client)["summary"]["completed_minutes"] == 45


def test_copy_shift_preserves_toronto_wall_clock_across_dst(client):
    task = create(client, recurrence=None, task_type="academic", academic_subtype="assignment",
                  due_at="2031-03-07T17:00:00-05:00", assessment_at="2031-03-08T09:00:00-05:00",
                  earliest_start="2031-03-03T08:00:00-05:00")
    response = client.post("/api/task-weeks", json={"task_definition_id": task["id"], "week_start": "2031-03-02"})
    assert response.status_code == 201, response.text
    response = client.post("/api/task-weeks/copy", json={"source_week": "2031-03-02", "target_week": "2031-03-09", "deadline_policy": "shift"})
    assert response.status_code == 200, response.text
    effective = response.json()["copied"][0]["effective_definition"]
    assert effective["due_at"] == "2031-03-14T17:00:00-04:00"
    assert effective["assessment_at"] == "2031-03-15T09:00:00-04:00"
    assert effective["earliest_start"] == "2031-03-10T08:00:00-04:00"
    original = next(item for item in client.get("/api/task-definitions").json() if item["id"] == task["id"])
    assert original["due_at"] == task["due_at"]


def test_materialized_unstarted_week_uses_current_defaults_when_logging_session(client):
    task = create(client)
    assignment = week(client)["assignments"][0]
    assert edit_week(client, assignment, notes="Materialize without overriding duration").status_code == 200
    writable = {key: item for key, item in task.items() if key not in {"legacy_task_id", "scheduling_model"}}
    response = client.put(f"/api/task-definitions/{task['id']}", json={**writable, "session_minutes": 75})
    assert response.status_code == 200, response.text
    assert week(client)["assignments"][0]["session_minutes"] == 75
    response = client.post("/api/task-sessions", json={"assignment_id": assignment["id"]})
    assert response.status_code == 201, response.text
    assert response.json()["target_minutes"] == 75
    assert week(client)["summary"]["completed_minutes"] == 75
