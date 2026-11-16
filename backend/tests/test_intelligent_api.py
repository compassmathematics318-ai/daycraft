"""Real CP-SAT integration with isolated SQLite data and read-only forecasting."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app.database import LogicalSession, Schedule, TaskWeek
from backend.app.main import create_app
from backend.app import task_library


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "intelligence.sqlite")) as value:
        yield value


def test_new_defaults_and_legacy_meal_preferences_are_lossless(client):
    settings = client.get("/api/state").json()["settings"]
    assert [(m["name"], m["duration_minutes"]) for m in settings["meals"]] == [("Breakfast", 30), ("Lunch", 45), ("Dinner", 30)]
    settings["meals"] = [{"name": "My lunch", "duration_minutes": 55, "time": "12:00"}, {"name": "Snack", "duration_minutes": 15, "time": "12:00", "enabled": False}]
    response = client.put("/api/settings", json=settings)
    assert response.status_code == 200, response.text
    assert response.json()["meals"][0]["duration_minutes"] == 55
    assert response.json()["meals"][0]["time"] == "12:00"
    assert response.json()["meals"][1]["enabled"] is False
    settings["meals"][0]["location_id"] = "missing"
    assert client.put("/api/settings", json=settings).status_code == 422


def test_workload_applied_and_settings_changes_preserve_saved_blocks(client):
    date = "2030-11-13"
    response = client.post("/api/schedules/generate", json={"date": date, "mode": "deep"})
    assert response.status_code == 200, response.text
    original = response.json()
    assert original["workload_level"] == "medium"
    meals = [b for b in original["blocks"] if b["kind"] == "meal"]
    assert len(meals) == 3
    assert min(b["start"] for b in meals)[11:16] < "08:00"
    assert client.put(f"/api/day-preferences/{date}", json={"workload_level": "very_high"}).status_code == 200
    saved = client.get(f"/api/schedules?date={date}").json()[0]
    assert saved["blocks"] == original["blocks"]
    assert saved["workload_level"] == "medium" and saved["preferences_dirty"]
    changed = client.post("/api/schedules/generate", json={"date": date}).json()
    assert changed["workload_level"] == "very_high" and changed["mode"] == "deep"
    assert not changed.get("preferences_dirty")
    settings = client.get("/api/state").json()["settings"]
    settings["theme"] = "dark"
    client.put("/api/settings", json=settings)
    assert not client.get(f"/api/schedules?date={date}").json()[0].get("preferences_dirty")
    settings["meals"][0]["duration_minutes"] = 35
    client.put("/api/settings", json=settings)
    saved = client.get(f"/api/schedules?date={date}").json()[0]
    assert saved["preferences_dirty"] and saved["blocks"] == changed["blocks"]


def test_forecast_reads_future_assignments_without_materializing_or_overwriting(client):
    definition = client.post("/api/task-definitions", json={"title": "Recurring study", "session_minutes": 60, "importance": 8, "difficulty": 6, "min_sessions_per_week": 3,
        "recurrence": {"start_week": "2030-11-10"}})
    assert definition.status_code == 201, definition.text
    future = client.post("/api/schedules/generate", json={"date": "2030-11-18"})
    assert future.status_code == 200, future.text
    with client.app.state.session_factory() as db:
        before_plans = {r.id: deepcopy(r.payload) for r in db.scalars(select(Schedule))}
        before_assignments = {r.id for r in db.scalars(select(TaskWeek))}
        before_sessions = {r.id for r in db.scalars(select(LogicalSession))}
        settings = client.get("/api/state").json()["settings"]
        _, _, _, context = task_library.planning_inputs(db, "2030-11-13", settings, [])
        assert len(context["days"]) >= 14
        assert any(a["week_start"] == "2030-11-17" for a in context["forecast_assignments"])
        assert {r.id: r.payload for r in db.scalars(select(Schedule))} == before_plans
        assert {r.id for r in db.scalars(select(TaskWeek))} == before_assignments
        assert {r.id for r in db.scalars(select(LogicalSession))} == before_sessions
    generated = client.post("/api/schedules/generate", json={"date": "2030-11-13"})
    assert generated.status_code == 200, generated.text
    forecast = generated.json()["horizon_forecast"]
    assert forecast["forecast_only"] and forecast["end"] >= "2030-11-26"
    assert client.get("/api/schedules?date=2030-11-18").json()[0] == future.json()


def test_legacy_meal_identity_survives_preference_rename_and_explicit_lock(client):
    settings = client.get("/api/state").json()["settings"]
    settings["meals"] = [{"name": "Lunch", "time": "12:00", "duration_minutes": 35}]
    saved = client.put("/api/settings", json=settings).json()
    identity = saved["meals"][0]["id"]
    assert identity
    plan = client.post("/api/schedules/generate", json={"date": "2030-11-13"}).json()
    meal = next(b for b in plan["blocks"] if b["kind"] == "meal")
    assert meal["meal_id"] == identity
    meal["locked"] = True
    response = client.put(f"/api/schedules/{plan['id']}", json={"blocks": plan["blocks"]})
    assert response.status_code == 200, response.text
    protected = next(b for b in response.json()["blocks"] if b["kind"] == "meal")
    saved["meals"][0].update(name="Midday meal", duration_minutes=40)
    assert client.put("/api/settings", json=saved).status_code == 200
    result = client.post("/api/schedules/generate", json={"date": "2030-11-13"}).json()
    assert [b for b in result["blocks"] if b["kind"] == "meal"] == [protected]
    assert client.get("/api/state").json()["settings"]["meals"][0]["id"] == identity
