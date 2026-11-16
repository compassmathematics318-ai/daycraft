"""Opportunity generation uses real API persistence without altering future history."""
from copy import deepcopy
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app.database import LogicalSession
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "advanced.sqlite")) as client:
        yield client


def test_advance_work_roundtrips_preserves_future_and_locked_session(client):
    day, future = "2030-11-13", "2030-11-20"
    settings = client.get("/api/state").json()["settings"]
    settings.update(meals=[], work_start="08:00", work_end="13:00", break_minutes=10)
    assert client.put("/api/settings", json=settings).status_code == 200
    assert client.post("/api/schedules/generate", json={"date": future}).status_code == 200
    definition = client.post("/api/task-definitions", json={
        "title": "Advance research", "task_type": "academic", "session_minutes": 60,
        "min_sessions_per_week": 4, "max_sessions_per_day": 3,
        "importance": 9, "difficulty": 5, "location_mode": "remote"})
    assert definition.status_code == 201, definition.text
    assignment = client.post("/api/task-weeks", json={
        "task_definition_id": definition.json()["id"], "week_start": "2030-11-10"})
    assert assignment.status_code == 201, assignment.text
    future_before = deepcopy(client.get(f"/api/schedules?date={future}").json())
    assert client.put(f"/api/day-preferences/{day}", json={"workload_level": "very_high"}).status_code == 200
    response = client.post("/api/schedules/generate", json={"date": day})
    assert response.status_code == 200, response.text
    plan = response.json()
    work = [b for b in plan["blocks"] if b.get("task_id") == definition.json()["id"]]
    assert len(work) >= 2
    assert len(work) <= 3
    assert not plan["conflicts"]
    assert client.get(f"/api/schedules?date={future}").json() == future_before
    # Moving a valid plan must not retain generated tail/optimality claims.
    for block in plan["blocks"]:
        for key in ("start", "end"):
            block[key] = (datetime.fromisoformat(block[key]) + timedelta(minutes=5)).isoformat()
    moved = client.put(f"/api/schedules/{plan['id']}", json={"blocks": plan["blocks"]})
    assert moved.status_code == 200, moved.text
    plan = moved.json()
    assert "tail_diagnostics" not in plan["stats"]
    assert "objective_value" not in plan["stats"]
    assert plan["solver_status"] == "NOT_RUN"
    work = [b for b in plan["blocks"] if b.get("task_id") == definition.json()["id"]]
    work[0]["locked"] = True
    saved = client.put(f"/api/schedules/{plan['id']}", json={"blocks": plan["blocks"]})
    assert saved.status_code == 200, saved.text
    locked = next(b for b in saved.json()["blocks"] if b["id"] == work[0]["id"])
    regenerated = client.post("/api/schedules/generate", json={"date": day}).json()
    assert not regenerated["conflicts"]
    actual = next(b for b in regenerated["blocks"] if b["id"] == locked["id"])
    for key in ("start", "end", "logical_session_id", "task_id", "locked", "status"):
        assert actual[key] == locked[key]
    assert client.get(f"/api/schedules?date={future}").json() == future_before
    with client.app.state.session_factory() as db:
        assert all(s.completed_minutes == 0 for s in db.scalars(select(LogicalSession)))
