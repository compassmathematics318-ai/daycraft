"""Lead integration scenario using an isolated database, never personal data."""
from pathlib import Path
import json
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SCHEDULE_BUILDER_OFFLINE"] = "1"
from fastapi.testclient import TestClient  # noqa: E402
from backend.app.main import create_app  # noqa: E402


def main():
    with tempfile.TemporaryDirectory(prefix="daycraft-location-") as directory:
        os.environ["SCHEDULE_BUILDER_ROUTE_CACHE"] = str(Path(directory) / "routes.sqlite")
        with TestClient(create_app(Path(directory) / "scenario.sqlite")) as client:
            def post(path, value):
                response = client.post("/api/" + path, json=value)
                assert response.is_success, response.text
                return response.json()

            other = post("locations", {"name": "RCH", "lat": 43.4702765, "lon": -80.5407103})
            mc = post("locations", {"name": "MC", "lat": 43.4721069, "lon": -80.5439272,
                                    "travel_overrides": {other["id"]: 6}})
            settings = client.get("/api/state").json()["settings"]
            settings.update(meals=[], break_minutes=0, travel_buffer_minutes=5)
            assert client.put("/api/settings", json=settings).is_success
            for title, place, start, end in [("MATH145", mc, "09:20", "10:20"),
                                             ("Reality Labs", other, "10:20", "11:20")]:
                activity = post("activities", {"title": title, "category": "commitment",
                    "subtype": "Groupwork", "location_id": place["id"], "location_mode": "required"})
                occurrence = post("occurrences", {"activity_id": activity["id"],
                    "start": f"2032-11-09T{start}:00-05:00", "end": f"2032-11-09T{end}:00-05:00"})
            impossible = post("schedules/generate", {"date": "2032-11-09"})
            assert impossible["status"] == "infeasible", impossible
            response = client.put("/api/occurrences/" + occurrence["id"], json={
                "activity_id": activity["id"], "start": "2032-11-09T10:35:00-05:00",
                "end": "2032-11-09T11:35:00-05:00"})
            assert response.is_success, response.text
            feasible = post("schedules/generate", {"date": "2032-11-09"})
            assert feasible["status"] in {"optimal", "feasible"}, feasible
            walks = [block for block in feasible["blocks"] if block["kind"] == "travel"]
            assert len(walks) == 1 and not walks[0]["estimated"], walks
            assert feasible["stats"]["travel_minutes"] == 15
            result = {"isolated_database": True, "back_to_back_status": impossible["status"],
                      "back_to_back_conflicts": impossible["conflicts"],
                      "with_transition_status": feasible["status"], "travel": walks,
                      "manual_walk_minutes": 6, "buffer_minutes": 5,
                      "grid_reserved_minutes": 15}
            (ROOT / "test-results" / "locations-lead-scenario.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
