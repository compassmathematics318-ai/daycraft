"""Ordered settings persist across application lifetimes without history loss."""
from copy import deepcopy

from fastapi.testclient import TestClient

from backend.app.main import create_app


def configure(monkeypatch, tmp_path):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    return tmp_path / "meal-order.sqlite"


def test_reordered_legacy_meals_survive_restart_without_field_or_identity_changes(tmp_path, monkeypatch):
    path = configure(monkeypatch, tmp_path)
    with TestClient(create_app(path)) as client:
        settings = client.get("/api/state").json()["settings"]
        venue = client.post("/api/locations", json={"name": "Kitchen", "lat": 43.47, "lon": -80.54}).json()
        settings["meals"] = [
            {"name": "Lunch", "duration_minutes": 55, "time": "12:15", "location_id": venue["id"]},
            {"name": "Dinner", "duration_minutes": 40, "enabled": False},
            {"name": "Breakfast", "duration_minutes": 25},
        ]
        response = client.put("/api/settings", json=settings)
        assert response.status_code == 200, response.text
        before = response.json()
        reordered = {**before, "meals": [before["meals"][2], before["meals"][0], before["meals"][1]]}
        assert all(meal["id"] for meal in reordered["meals"])
        saved = client.put("/api/settings", json=reordered)
        assert saved.status_code == 200 and saved.json() == reordered
    # A new application/engine reads the actual saved database, not client state.
    with TestClient(create_app(path)) as client:
        restored = client.get("/api/state").json()["settings"]
        assert restored == reordered
        assert {m["id"]: m for m in restored["meals"]} == {m["id"]: m for m in before["meals"]}
        plan = client.post("/api/schedules/generate", json={"date": "2035-11-13"})
        assert plan.status_code == 200, plan.text
        generated = plan.json()
        assert generated["solver_status"] in {"OPTIMAL", "FEASIBLE"}
        assert not generated["conflicts"]
        meals = [b for b in generated["blocks"] if b["kind"] == "meal"]
        assert [b["meal_id"] for b in meals] == [m["id"] for m in restored["meals"] if m["enabled"]]


def test_reorder_marks_plan_stale_and_conflict_keeps_locked_completed_meals(tmp_path, monkeypatch):
    path = configure(monkeypatch, tmp_path)
    with TestClient(create_app(path)) as client:
        settings = client.get("/api/state").json()["settings"]
        settings["meals"] = [
            {"id": "early", "name": "Early snack", "duration_minutes": 20, "time": "08:00"},
            {"id": "late", "name": "Late snack", "duration_minutes": 25, "time": "10:00"},
        ]
        settings = client.put("/api/settings", json=settings).json()
        plan = client.post("/api/schedules/generate", json={"date": "2035-11-13"}).json()
        meals = [b for b in plan["blocks"] if b["kind"] == "meal"]
        meals[0]["status"] = "completed"
        meals[1]["locked"] = True
        response = client.put(f"/api/schedules/{plan['id']}", json={"blocks": plan["blocks"]})
        assert response.status_code == 200, response.text
        protected = deepcopy([b for b in response.json()["blocks"] if b["kind"] == "meal"])
        settings["meals"].reverse()
        assert client.put("/api/settings", json=settings).status_code == 200
        stale = client.get("/api/schedules?date=2035-11-13").json()[0]
        assert stale["preferences_dirty"] and stale["needs_regeneration"]
        assert [b for b in stale["blocks"] if b["kind"] == "meal"] == protected
        result = client.post("/api/schedules/generate", json={"date": "2035-11-13", "reoptimize": True})
        assert result.status_code == 200, result.text
        failed = result.json()
        assert failed["status"] == "infeasible"
        assert any("order" in message.lower() for message in failed["conflicts"])
        assert [b for b in failed["blocks"] if b["kind"] == "meal"] == protected
        persisted = client.get("/api/schedules?date=2035-11-13").json()[0]
        assert [b for b in persisted["blocks"] if b["kind"] == "meal"] == protected
