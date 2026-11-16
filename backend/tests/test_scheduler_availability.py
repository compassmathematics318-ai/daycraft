"""Dependency failures are explicit and cannot mutate saved plans or work credit."""
from copy import deepcopy
import logging

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app import main
from backend.app.database import Base, LogicalSession, Schedule, TaskChunk


DAY = "2020-11-08"
WORKLOADS = ["very_low", "low", "medium", "high", "very_high"]
BLOCKED = "DLL load failed while importing pandas_parser: An Application Control policy has blocked this file."


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(main.create_app(tmp_path / "availability.sqlite")) as value:
        yield value


def seed(client):
    response = client.post("/api/task-definitions", json={"title": "Saved work", "session_minutes": 60})
    assert response.status_code == 201, response.text
    definition = response.json()
    response = client.post("/api/task-weeks", json={"task_definition_id": definition["id"], "week_start": DAY})
    assert response.status_code == 201, response.text
    assignment = response.json()
    block = {"id": "saved-chunk", "kind": "task", "title": "Saved work", "task_id": definition["id"],
             "task_definition_id": definition["id"], "task_assignment_id": assignment["id"],
             "logical_session_id": "saved-session", "chunk_index": 0,
             "start": f"{DAY}T08:00:00-05:00", "end": f"{DAY}T09:00:00-05:00", "status": "todo"}
    plan = {"id": "saved-plan", "date": DAY, "mode": "deep", "status": "feasible", "blocks": [block],
            "unallocated": [], "conflicts": [], "explanations": [], "stats": {}}
    with client.app.state.session_factory() as db:
        db.add(LogicalSession(id="saved-session", assignment_id=assignment["id"], index=0,
                              target_minutes=60, completed_minutes=0, baseline_completed_minutes=0, status="todo"))
        db.add(Schedule(id=plan["id"], date=DAY, payload=plan))
        db.flush()
        db.add(TaskChunk(id=block["id"], logical_session_id="saved-session", schedule_id=plan["id"],
                         start=block["start"], end=block["end"], status="todo", credited_minutes=0))
        db.commit()
    # Persist real credit through the authoritative endpoint before testing failure.
    response = client.post(f"/api/schedules/{plan['id']}/blocks/{block['id']}/completion", json={"completed": True})
    assert response.status_code == 200, response.text
    return response.json()


def snapshot(client):
    with client.app.state.session_factory() as db:
        return {table.name: deepcopy([dict(row) for row in db.execute(select(table)).mappings()])
                for table in Base.metadata.sorted_tables}


def block_dependency(monkeypatch, error=None):
    def unavailable(name):
        assert name == "ortools.sat.python.cp_model"
        raise error if error is not None else ImportError(BLOCKED)
    monkeypatch.setattr(main, "import_module", unavailable)


@pytest.mark.parametrize("workload", WORKLOADS)
def test_blocked_generation_preserves_every_table_and_workload(client, monkeypatch, caplog, workload):
    seed(client)
    assert client.put(f"/api/day-preferences/{DAY}", json={"workload_level": workload}).status_code == 200
    before = snapshot(client)
    block_dependency(monkeypatch)
    with caplog.at_level(logging.ERROR, logger="backend.app.main"):
        response = client.post("/api/schedules/generate", json={"date": DAY, "mode": "deep", "reoptimize": True})
    assert response.status_code == 503, response.text
    assert "Windows Application Control" in response.json()["detail"]
    assert "saved plan has not changed" in response.json()["detail"]
    assert snapshot(client) == before
    assert "pandas_parser" in caplog.text
    assert any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize("workload", WORKLOADS)
def test_workload_is_metadata_and_not_a_generation_mode(client, monkeypatch, workload):
    seed(client)
    assert client.put(f"/api/day-preferences/{DAY}", json={"workload_level": workload}).status_code == 200
    before = snapshot(client)

    def must_not_load():
        pytest.fail("Invalid requests must be rejected before loading the solver")
    monkeypatch.setattr(main, "ensure_scheduler_dependencies", must_not_load)
    for body in ({"date": DAY, "mode": workload}, {"date": DAY, "mode": "deep", "workload_level": workload}):
        response = client.post("/api/schedules/generate", json=body)
        assert response.status_code == 422, response.text
        assert snapshot(client) == before


def test_manual_validation_reports_same_dependency_failure_without_writing(client, monkeypatch):
    plan = seed(client)
    before = snapshot(client)
    block_dependency(monkeypatch)
    response = client.put(f"/api/schedules/{plan['id']}", json={"blocks": plan["blocks"]})
    assert response.status_code == 503, response.text
    assert "Windows Application Control" in response.json()["detail"]
    assert snapshot(client) == before


def test_manual_completion_guard_precedes_dependency_loading(client, monkeypatch):
    plan = seed(client)
    before = snapshot(client)
    blocks = deepcopy(plan["blocks"])
    blocks[0]["completion_confirmed_at"] = "2020-11-09T00:00:00Z"

    def must_not_load():
        pytest.fail("Completion evidence must be checked before loading the solver")
    monkeypatch.setattr(main, "ensure_scheduler_dependencies", must_not_load)
    response = client.put(f"/api/schedules/{plan['id']}", json={"blocks": blocks})
    assert response.status_code == 422, response.text
    assert snapshot(client) == before


@pytest.mark.parametrize("error", [ModuleNotFoundError("No module named 'ortools'"), OSError("Native library unavailable")])
def test_other_dependency_load_failures_do_not_claim_windows_policy(monkeypatch, error):
    block_dependency(monkeypatch, error)
    with pytest.raises(HTTPException) as caught:
        main.ensure_scheduler_dependencies()
    assert caught.value.status_code == 503
    assert "Windows Application Control" not in caught.value.detail
    assert caught.value.__cause__ is error


def test_unexpected_runtime_errors_are_not_mislabeled_as_dependency_failures(monkeypatch):
    error = RuntimeError("Unexpected programming failure")
    block_dependency(monkeypatch, error)
    with pytest.raises(RuntimeError) as caught:
        main.ensure_scheduler_dependencies()
    assert caught.value is error
