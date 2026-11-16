"""Generated relationship snapshots survive edits without trusting client values."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from backend.app.main import create_app


@pytest.mark.parametrize("linked", [False, True])
def test_generated_context_roundtrip_omission_and_forgery(tmp_path, monkeypatch, linked):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "context.sqlite")) as client:
        relation = None
        if linked:
            response = client.post("/api/projects", json={"name": "Preserved project context"})
            assert response.status_code == 201, response.text
            relation = {"kind": "project", "id": response.json()["id"]}
        response = client.post("/api/activities", json={"title": "Fixed commitment", "category": "commitment", "subtype": "Personal", "related_entity": relation})
        assert response.status_code == 201, response.text
        activity = response.json()
        response = client.post("/api/occurrences", json={"activity_id": activity["id"], "start": "2030-11-13T09:00:00-05:00", "end": "2030-11-13T10:00:00-05:00"})
        assert response.status_code == 201, response.text
        response = client.post("/api/schedules/generate", json={"date": "2030-11-13"})
        assert response.status_code == 200, response.text
        plan = response.json()
        assert plan["solver_status"] in {"OPTIMAL", "FEASIBLE"}
        endpoint = f"/api/schedules/{plan['id']}"
        fixed = next(block for block in plan["blocks"] if block.get("activity_id") == activity["id"])
        assert fixed["related_entity"] == relation
        response = client.put(endpoint, json={"blocks": plan["blocks"]})
        assert response.status_code == 200, response.text
        saved = response.json()
        for field in ("related_entity", "related_entity_context"):
            forged = deepcopy(saved["blocks"])
            target = next(block for block in forged if block.get("activity_id") == activity["id"])
            target[field] = {"kind": "project", "id": "client-invented"}
            rejected = client.put(endpoint, json={"blocks": forged})
            assert rejected.status_code == 422, rejected.text
            assert "read-only" in rejected.text
            assert client.get("/api/schedules?date=2030-11-13").json()[0]["blocks"] == saved["blocks"]
        omitted = [{key: value for key, value in block.items() if key not in {"related_entity", "related_entity_context"}} for block in saved["blocks"]]
        response = client.put(endpoint, json={"blocks": omitted})
        assert response.status_code == 200, response.text
        actual = next(block for block in response.json()["blocks"] if block.get("activity_id") == activity["id"])
        for field in ("related_entity", "related_entity_context"):
            assert actual.get(field) == fixed.get(field)
        assert actual["start"] == fixed["start"] and actual["end"] == fixed["end"]
