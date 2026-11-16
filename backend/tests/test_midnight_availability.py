"""Configured midnight availability is consistent across API, forecast and solve."""
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from backend.app import task_library
from backend.app.main import create_app
from backend.app.schemas import Settings


def test_midnight_sleep_keeps_work_and_forecast_on_selected_day(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "midnight.sqlite")) as client:
        settings = client.get("/api/state").json()["settings"]
        settings.update(wake_time="07:00", work_start="08:00", work_end="23:30", sleep_time="00:00",
                        meals=[{"name": "Dinner", "duration_minutes": 30}])
        response = client.put("/api/settings", json=settings)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["sleep_time"] == "00:00"
        with client.app.state.session_factory() as db:
            _, _, _, context = task_library.planning_inputs(db, "2030-11-13", saved, [])
        # Dinner can occupy the awake half-hour after work; no spurious negative
        # midnight interval consumes the forecast's configured capacity.
        assert context["days"][0]["capacity_minutes"] == 930
        plan = client.post("/api/schedules/generate", json={"date": "2030-11-13"})
        assert plan.status_code == 200, plan.text
        assert not plan.json()["conflicts"]
        assert plan.json()["solver_status"] in {"OPTIMAL", "FEASIBLE"}
        assert plan.json()["stats"]["effective_work_end"].endswith("23:30:00-05:00")


def test_midnight_sleep_does_not_allow_other_overnight_work_windows():
    with pytest.raises(ValidationError):
        Settings(wake_time="07:00", work_start="22:00", work_end="01:00", sleep_time="00:00")
    with pytest.raises(ValidationError):
        Settings(wake_time="07:00", work_start="08:00", work_end="23:30", sleep_time="22:00")
