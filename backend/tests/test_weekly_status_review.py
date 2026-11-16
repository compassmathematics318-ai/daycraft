"""Target satisfaction must never become an implicit scheduling quota."""
from fastapi.testclient import TestClient
import pytest

from backend.app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "planner.sqlite")) as client:
        settings = client.get("/api/state").json()["settings"]
        settings.update(work_start="08:00", work_end="11:00", meals=[], break_minutes=0, travel_buffer_minutes=0)
        assert client.put("/api/settings", json=settings).status_code == 200
        yield client


def create_work(client, importance):
    response = client.post("/api/task-definitions", json={"title": "Ongoing work", "session_minutes": 30, "min_sessions_per_week": 1, "importance": importance})
    assert response.status_code == 201, response.text
    task = response.json()
    response = client.post("/api/task-weeks", json={"task_definition_id": task["id"], "week_start": "2030-11-10", "min_sessions_per_week": 1})
    assert response.status_code == 201, response.text
    assignment = response.json()
    assert client.post("/api/task-sessions", json={"assignment_id": assignment["id"]}).status_code == 201
    return task, assignment


def week(client):
    return client.get("/api/task-week?week_start=2030-11-10").json()


def test_met_minimum_stays_eligible_for_meaningful_extras(client):
    task, _ = create_work(client, 10)
    assignment = week(client)["assignments"][0]
    assert assignment["completed_sessions"] == 1 and assignment["target_met"]
    assert assignment["status"] == "in_progress"
    response = client.post("/api/schedules/generate", json={"date": "2030-11-10"})
    assert response.status_code == 200, response.text
    assert any(block.get("task_id") == task["id"] for block in response.json()["blocks"])
    assert not response.json()["weekly_progress"][0]["excluded"]


def test_raising_met_goal_roundtrips_without_closing_week(client):
    task, original = create_work(client, 1)
    previous = week(client)["assignments"][0]
    payload = {"task_definition_id": task["id"], "week_start": "2030-11-10", "min_sessions_per_week": 3, "status": previous["status"]}
    response = client.put(f"/api/task-weeks/{original['id']}", json=payload)
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["status"] == "in_progress" and not updated["target_met"]
    assert updated["completed_sessions"] == 1 and updated["remaining_target_sessions"] == 2
    plan = client.post("/api/schedules/generate", json={"date": "2030-11-10"}).json()
    assert any(block.get("task_id") == task["id"] for block in plan["blocks"])
    response = client.put(f"/api/task-weeks/{original['id']}", json={**payload, "status": "completed"})
    assert response.status_code == 200 and response.json()["status"] == "completed"
    assert response.json()["completed_sessions"] == 1
    closed = client.post("/api/schedules/generate", json={"date": "2030-11-10"}).json()
    assert not any(block.get("task_id") == task["id"] for block in closed["blocks"])
