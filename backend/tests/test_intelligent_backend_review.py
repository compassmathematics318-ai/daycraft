"""Independent API/data regressions for intelligent planning contracts."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app import task_library
from backend.app.database import LogicalSession, Schedule, TaskWeek
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "backend-review.sqlite")) as value:
        yield value


@pytest.mark.parametrize("week,deadline,horizon_end,included", [
    ("2030-12-01", "2030-12-03", "2030-12-03", True),
    ("2030-12-08", "2030-12-10", "2030-12-10", True),
    ("2030-12-08", "2030-12-11", "2030-11-26", False),
])
def test_future_assignment_only_deadline_extends_bounded_readonly_horizon(client, week, deadline, horizon_end, included):
    response = client.post("/api/task-definitions", json={
        "title": "Future preparation", "task_type": "academic",
        "recurrence": {"start_week": "2030-11-10"},
    })
    assert response.status_code == 201, response.text
    definition = response.json()
    response = client.post("/api/task-weeks", json={
        "task_definition_id": definition["id"], "week_start": week,
        "overrides": {"assessment_at": f"{deadline}T09:00:00-05:00"},
    })
    assert response.status_code == 201, response.text
    future_assignment = response.json()
    settings = client.get("/api/state").json()["settings"]
    with client.app.state.session_factory() as db:
        before = {
            cls: {row.id: deepcopy(row.payload) if hasattr(row, "payload") else row.completed_minutes
                  for row in db.scalars(select(cls))}
            for cls in (TaskWeek, LogicalSession, Schedule)
        }
        _, _, _, context = task_library.planning_inputs(db, "2030-11-13", settings, [])
        assert context["horizon_end"] == horizon_end
        assert any(item["id"] == future_assignment["id"] for item in context["forecast_assignments"]) is included
        assert len(context["days"]) <= 28
        assert {
            cls: {row.id: deepcopy(row.payload) if hasattr(row, "payload") else row.completed_minutes
                  for row in db.scalars(select(cls))}
            for cls in (TaskWeek, LogicalSession, Schedule)
        } == before


def test_meal_identity_is_server_owned_with_legacy_client_roundtrip(client):
    response = client.post("/api/schedules/generate", json={"date": "2030-11-13"})
    assert response.status_code == 200, response.text
    original = response.json()
    blocks = deepcopy(original["blocks"])
    meal = next(block for block in blocks if block["kind"] == "meal")
    meal["meal_id"] = "forged-meal"
    response = client.put(f"/api/schedules/{original['id']}", json={"blocks": blocks})
    assert response.status_code == 422, response.text
    assert client.get("/api/schedules?date=2030-11-13").json()[0]["blocks"] == original["blocks"]
    for block in blocks:
        block.pop("meal_id", None)
    response = client.put(f"/api/schedules/{original['id']}", json={"blocks": blocks})
    assert response.status_code == 200, response.text
    assert {b["id"]: b.get("meal_id") for b in response.json()["blocks"] if b["kind"] == "meal"} == {
        b["id"]: b.get("meal_id") for b in original["blocks"] if b["kind"] == "meal"
    }


def test_workload_staleness_is_date_scoped_and_blocks_manual_edit_until_regeneration(client):
    plans = []
    for date in ("2030-11-13", "2030-11-14"):
        response = client.post("/api/schedules/generate", json={"date": date})
        assert response.status_code == 200, response.text
        plans.append(response.json())
    response = client.put("/api/day-preferences/2030-11-13", json={"workload_level": "low"})
    assert response.status_code == 200, response.text
    saved = client.get("/api/schedules?date=2030-11-13").json()[0]
    assert saved["preferences_dirty"] and saved["blocks"] == plans[0]["blocks"]
    assert client.get("/api/schedules?date=2030-11-14").json()[0] == plans[1]
    response = client.put(f"/api/schedules/{plans[0]['id']}", json={"blocks": plans[0]["blocks"]})
    assert response.status_code == 409, response.text
    assert "preferences" in response.json()["detail"].lower()


def test_meal_venue_cannot_be_deleted_even_when_meal_disabled(client):
    response = client.post("/api/locations", json={"name": "Dining room", "lat": 43.47, "lon": -80.54})
    assert response.status_code == 201, response.text
    location = response.json()
    settings = client.get("/api/state").json()["settings"]
    settings["meals"] = [{"name": "Lunch", "duration_minutes": 55, "enabled": False, "location_id": location["id"], "time": "12:15"}]
    response = client.put("/api/settings", json=settings)
    assert response.status_code == 200, response.text
    response = client.delete(f"/api/locations/{location['id']}")
    assert response.status_code == 409, response.text
    meal = client.get("/api/state").json()["settings"]["meals"][0]
    assert meal["id"]
    assert {key: value for key, value in meal.items() if key != "id"} == {
        "name": "Lunch", "duration_minutes": 55, "enabled": False,
        "location_id": location["id"], "time": "12:15",
    }


@pytest.mark.parametrize("now,expected_minutes", [
    ("2030-11-13T20:00:00Z", 180),  # 15:00 Toronto, three work hours remain.
    ("2030-11-13T10:00:00Z", 600),  # Before today's work window.
    ("2030-11-12T20:00:00Z", 600),  # Selecting a future date retains its full window.
])
def test_remaining_day_capacity_clips_only_selected_date_without_writing_future_plan(client, now, expected_minutes):
    settings = client.get("/api/state").json()["settings"]
    settings.update(work_start="08:00", work_end="18:00", meals=[], break_minutes=0)
    response = client.put("/api/settings", json=settings)
    assert response.status_code == 200, response.text
    response = client.post("/api/schedules/generate", json={"date": "2030-11-15"})
    assert response.status_code == 200, response.text
    future = response.json()
    with client.app.state.session_factory() as db:
        before_plans = {row.id: deepcopy(row.payload) for row in db.scalars(select(Schedule))}
        before_weeks = {row.id for row in db.scalars(select(TaskWeek))}
        before_sessions = {row.id for row in db.scalars(select(LogicalSession))}
        _, _, _, context = task_library.planning_inputs(db, "2030-11-13", settings, [], now=now)
        capacity = {day["date"]: day["capacity_minutes"] for day in context["days"]}
        assert capacity["2030-11-13"] == expected_minutes
        assert capacity["2030-11-14"] == 600
        assert {row.id: row.payload for row in db.scalars(select(Schedule))} == before_plans
        assert {row.id for row in db.scalars(select(TaskWeek))} == before_weeks
        assert {row.id for row in db.scalars(select(LogicalSession))} == before_sessions
    assert client.get("/api/schedules?date=2030-11-15").json()[0] == future
