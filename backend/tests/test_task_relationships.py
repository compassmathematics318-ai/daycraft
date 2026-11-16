"""Live calendar links and allocation are independent of explicit completion."""
from datetime import datetime

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app import task_library, work_confirmation
from backend.app.database import Entity, LogicalSession, TaskChunk, TaskWeek
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "relationships.sqlite")) as client:
        settings = client.get("/api/state").json()["settings"]
        settings.update(work_start="08:00", work_end="09:00", meals=[], break_minutes=0, travel_buffer_minutes=0)
        assert client.put("/api/settings", json=settings).status_code == 200
        yield client


def task(client, **values):
    response = client.post("/api/task-definitions", json={"title": "Reading", "importance": 5, **values})
    assert response.status_code == 201, response.text
    return response.json()


def writable(value):
    return {key: item for key, item in value.items() if key not in ("legacy_task_id", "scheduling_model")}


def assign(client, value, **extra):
    response = client.post("/api/task-weeks", json={"task_definition_id": value["id"], "week_start": "2030-11-10", **extra})
    assert response.status_code == 201, response.text
    return response.json()


def plan(client):
    response = client.post("/api/schedules/generate", json={"date": "2030-11-10"})
    assert response.status_code == 200, response.text
    return response.json()


def test_course_is_preserved_when_hidden_and_omitted(client):
    value = task(client, task_type="academic", course="CS 246")
    payload = {**writable(value), "task_type": "personal", "academic_subtype": None}
    payload.pop("course")
    response = client.put(f"/api/task-definitions/{value['id']}", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["course"] == "CS 246"


@pytest.mark.parametrize("category,extra", [
    ("class", {"subtype": "Lecture"}),
    ("commitment", {"subtype": "Personal"}),
    ("assessment", {"assessment_start": "2030-11-18T10:00:00-05:00", "assessment_end": "2030-11-18T11:00:00-05:00"}),
])
def test_live_related_activity_link_rename_delete_and_occurrences(client, category, extra):
    response = client.post("/api/activities", json={"title": "Source context", "category": category, **extra})
    assert response.status_code == 201, response.text
    activity = response.json()
    if category != "assessment":
        response = client.post("/api/occurrences", json={"activity_id": activity["id"], "start": "2030-11-12T10:00:00-05:00", "end": "2030-11-12T11:00:00-05:00"})
        assert response.status_code == 201, response.text
    value = task(client, related_activity_id=activity["id"], due_at="2030-11-14T17:00:00-05:00", course="Original course")
    assignment = assign(client, value, overrides={"related_activity_id": activity["id"]})
    first = plan(client)
    context = first["task_week_context"]["definitions"][0]
    assert context["related_activity"]["title"] == "Source context"
    assert context["related_activity"]["category"] == category
    assert context["due_at"] == value["due_at"] and context["assessment_at"] is None
    # The rolling horizon now includes the following week's assessment.
    assert len(context["related_activity"]["occurrences"]) == 1
    if category == "assessment":
        assert context["related_activity"]["occurrences"][0]["start"].startswith("2030-11-18")
    if category == "assessment":
        assert context["related_activity"]["assessment_start"] is not None
    response = client.put(f"/api/activities/{activity['id']}", json={**activity, "title": "Renamed source"})
    assert response.status_code == 200, response.text
    assert client.get("/api/schedules").json()[0]["tasks_dirty"]
    assert plan(client)["task_week_context"]["definitions"][0]["related_activity"]["title"] == "Renamed source"
    assert client.delete(f"/api/activities/{activity['id']}").status_code == 204
    saved = client.get("/api/task-definitions").json()[0]
    assert saved["related_activity_id"] is None and saved["course"] == "Original course"
    assert saved["due_at"] == value["due_at"] and saved["status"] == "active"
    week = client.get("/api/task-week?week_start=2030-11-10").json()["assignments"][0]
    assert week["effective_definition"]["related_activity_id"] is None
    assert week["overrides"]["related_activity_id"] is None
    response = client.put(f"/api/task-weeks/{assignment['id']}", json={"task_definition_id": value["id"], "week_start": "2030-11-10", "overrides": week["overrides"]})
    assert response.status_code == 200, response.text
    assert plan(client)["task_week_context"]["definitions"][0]["related_activity"] is None


def test_allocated_target_and_elapsed_work_never_complete_task(client):
    value = task(client)
    assigned = assign(client, value)
    plan(client)
    with client.app.state.session_factory() as db:
        row = db.get(TaskWeek, assigned["id"])
        sessions = list(db.scalars(select(LogicalSession)))
        chunks = list(db.scalars(select(TaskChunk)))
        before = task_library.assignment_value(row, sessions, chunks, datetime.fromisoformat("2030-11-10T07:00:00-05:00"))
        during = task_library.assignment_value(row, sessions, chunks, datetime.fromisoformat("2030-11-10T08:30:00-05:00"))
        after = task_library.assignment_value(row, sessions, chunks, datetime.fromisoformat("2030-11-11T07:00:00-05:00"))
    assert before["future_scheduled_minutes"] == 60 and before["elapsed_scheduled_minutes"] == 0
    assert during["future_scheduled_minutes"] == during["elapsed_scheduled_minutes"] == 30
    assert after["future_scheduled_minutes"] == 0 and after["elapsed_scheduled_minutes"] == 60
    assert after["allocated_sessions"] == after["planned_sessions"] == after["scheduled_sessions"] == 1
    assert after["target_met"] and after["remaining_target_sessions"] == 0
    assert after["completed_sessions"] == after["verified_completed_minutes"] == 0
    assert after["status"] == "todo"
    assert client.get("/api/task-definitions").json()[0]["status"] == "active"


def test_partial_chunk_is_not_full_session_and_verified_history_counts(client):
    value = task(client)
    assigned = assign(client, value)
    response = client.post("/api/task-sessions", json={"assignment_id": assigned["id"], "completed_minutes": 20})
    assert response.status_code == 201, response.text
    week = client.get("/api/task-week?week_start=2030-11-10").json()["assignments"][0]
    assert week["allocated_sessions"] == 0 and not week["target_met"]
    assert week["verified_completed_minutes"] == 20
    response = client.put(f"/api/task-sessions/{response.json()['id']}", json={"status": "completed"})
    assert response.status_code == 200, response.text
    week = client.get("/api/task-week?week_start=2030-11-10").json()["assignments"][0]
    assert week["allocated_sessions"] == week["completed_sessions"] == 1 and week["target_met"]
    assert week["status"] == "in_progress"
    assert client.get("/api/task-definitions").json()[0]["status"] == "active"


def test_split_chunks_cover_one_logical_session_and_skipped_work_releases_target():
    row = TaskWeek(id="week", task_definition_id="task", week_start="2030-11-10", payload={"min_sessions_per_week": 1, "session_minutes": 60})
    session = LogicalSession(id="session", assignment_id="week", index=0, target_minutes=60, completed_minutes=0, status="todo")
    chunks = [TaskChunk(id=str(index), logical_session_id="session", schedule_id="schedule", start=start, end=end, status="todo") for index, (start, end) in enumerate([
        ("2030-11-10T08:00:00-05:00", "2030-11-10T08:30:00-05:00"),
        ("2030-11-11T08:00:00-05:00", "2030-11-11T08:30:00-05:00"),
    ])]
    now = datetime.fromisoformat("2030-11-10T10:00:00-05:00")
    covered = task_library.assignment_value(row, [session], chunks, now)
    assert covered["allocated_sessions"] == 1 and covered["target_met"]
    assert covered["elapsed_scheduled_minutes"] == covered["future_scheduled_minutes"] == 30
    chunks[1].status = "skipped"
    partial = task_library.assignment_value(row, [session], chunks, now)
    assert partial["allocated_sessions"] == 0 and not partial["target_met"]
    assert partial["remaining_target_sessions"] == 1 and partial["completed_minutes"] == 0


def test_completed_definition_blocks_overrides_and_reopen_preserves_history(client):
    value = task(client)
    assigned = assign(client, value, overrides={"status": "active"}, allow_inactive=True)
    generated = plan(client)
    assert any(block.get("task_id") == value["id"] for block in generated["blocks"])
    response = client.put(f"/api/task-definitions/{value['id']}", json={**writable(value), "status": "completed"})
    assert response.status_code == 200, response.text
    completed = response.json()
    assert not any(block.get("task_id") == value["id"] for block in plan(client)["blocks"])
    week = client.get("/api/task-week?week_start=2030-11-10").json()
    assert week["summary"]["excluded_tasks"] == 1
    assert week["assignments"][0]["id"] == assigned["id"]
    assert week["assignments"][0]["completed_minutes"] == 0
    # An older client's omitted lifecycle cannot reopen a completed definition.
    omitted = writable(completed)
    omitted.pop("status")
    response = client.put(f"/api/task-definitions/{value['id']}", json=omitted)
    assert response.status_code == 200 and response.json()["status"] == "completed"
    response = client.put(f"/api/task-definitions/{value['id']}", json={**writable(completed), "status": "active"})
    assert response.status_code == 200, response.text
    assert any(block.get("task_id") == value["id"] for block in plan(client)["blocks"])


@pytest.mark.parametrize("legacy", [False, True])
def test_definition_completion_reopen_never_invents_or_erases_credit(client, legacy):
    if legacy:
        response = client.post("/api/tasks", json={"title": "Legacy history", "duration_minutes": 60, "remaining_minutes": 40})
        assert response.status_code == 201, response.text
        value = client.get("/api/task-definitions").json()[0]
        assign(client, value)
    else:
        value = task(client)
        assigned = assign(client, value)
        assert client.post("/api/task-sessions", json={"assignment_id": assigned["id"], "completed_minutes": 20}).status_code == 201
    plan(client)

    def ledger():
        with client.app.state.session_factory() as db:
            return (
                [(row.id, row.completed_minutes, row.baseline_completed_minutes, row.status) for row in db.scalars(select(LogicalSession))],
                [(row.id, row.credited_minutes, row.status) for row in db.scalars(select(TaskChunk))],
                [(row.id, row.payload["remaining_minutes"], row.payload["status"]) for row in db.scalars(select(Entity).where(Entity.collection == "tasks"))],
            )

    before = ledger()
    original_projection = client.get("/api/tasks").json()[0]["status"]
    assert before[0][0][1] == 20
    assert len(before[1]) == 1
    for status in ("completed", "active"):
        response = client.put(f"/api/task-definitions/{value['id']}", json={**writable(value), "status": status})
        assert response.status_code == 200, response.text
        assert ledger() == before
        assert client.get("/api/tasks").json()[0]["status"] == ("completed" if status == "completed" else original_projection)


def test_legacy_exhausted_work_budget_stays_open_until_explicit_completion(client, monkeypatch):
    response = client.post("/api/tasks", json={"title": "Finite legacy", "duration_minutes": 60, "remaining_minutes": 60})
    assert response.status_code == 201, response.text
    value = response.json()
    generated = plan(client)
    blocks = generated["blocks"]
    work = next(item for item in blocks if item.get("task_id") == value["id"])

    class AfterWork(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(work["end"]).astimezone(tz)

    monkeypatch.setattr(work_confirmation, "datetime", AfterWork)
    work["status"] = "completed"
    response = client.put(f"/api/schedules/{generated['id']}", json={"blocks": blocks})
    assert response.status_code == 200, response.text
    projected = client.get("/api/tasks").json()[0]
    assert projected["remaining_minutes"] == 0 and projected["status"] == "in_progress"
    assert client.get("/api/task-definitions").json()[0]["status"] == "active"
    for status, lifecycle in (("completed", "completed"), ("todo", "active")):
        response = client.put(f"/api/tasks/{value['id']}", json={**projected, "status": status})
        assert response.status_code == 200, response.text
        assert client.get("/api/task-definitions").json()[0]["status"] == lifecycle
        assert next(item for item in client.get("/api/schedules").json()[0]["blocks"] if item.get("task_id") == value["id"])["status"] == "completed"


def test_legacy_close_reopen_partial_work_preserves_budget_and_weekly_credit(client):
    response = client.post("/api/tasks", json={"title": "Partly worked finite task", "duration_minutes": 60, "remaining_minutes": 40})
    assert response.status_code == 201, response.text
    value = response.json()
    scheduled = plan(client)
    blocks = scheduled["blocks"]
    assert any(item.get("task_id") == value["id"] for item in blocks)
    for status, lifecycle in (("completed", "completed"), ("todo", "active")):
        # Older status-only writers must not reset finite progress on omission.
        response = client.put(f"/api/tasks/{value['id']}", json={"title": value["title"], "status": status})
        assert response.status_code == 200, response.text
        assert response.json()["remaining_minutes"] == 40
        assert client.get("/api/task-definitions").json()[0]["status"] == lifecycle
        assert client.get("/api/schedules").json()[0]["blocks"] == blocks
        with client.app.state.session_factory() as db:
            assert list(db.scalars(select(LogicalSession))) == []
            assert list(db.scalars(select(TaskChunk))) == []
    canonical = client.get("/api/task-definitions").json()[0]
    converted = assign(client, canonical)
    assert converted["completed_minutes"] == 20
    assert converted["sessions"][0]["completed_minutes"] == 20
    assert converted["completed_sessions"] == 0
    assert converted["remaining_minutes"] == 40


def test_new_legacy_completed_status_does_not_invent_completed_work(client):
    response = client.post("/api/tasks", json={"title": "Explicitly closed", "status": "completed", "duration_minutes": 60, "remaining_minutes": 40})
    assert response.status_code == 201, response.text
    assert response.json()["remaining_minutes"] == 40
    assert client.get("/api/task-definitions").json()[0]["status"] == "completed"
