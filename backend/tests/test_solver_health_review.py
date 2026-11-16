"""Independent protocol review: child output cannot manufacture readiness."""
import json
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from backend.app import main, solver_health


@pytest.mark.parametrize("payload", [None, [], "ready", {"code": []},
                                     {"code": "ready", "solver_status": []},
                                     {"code": "ready", "solver_status": "INFEASIBLE"},
                                     {"code": "ready", "solver_status": "UNKNOWN"}])
def test_invalid_child_shapes_and_unsolved_statuses_are_unavailable(monkeypatch, payload):
    monkeypatch.setattr(solver_health.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 0, json.dumps(payload), ""))
    result = solver_health.check_solver_health()
    assert result["status"] == "unavailable"
    assert result["code"] == "solver_probe_failed"


@pytest.mark.parametrize("code,status", [("ready", "OPTIMAL"),
                                        ("windows_policy_blocked", None)])
def test_native_crash_overrides_even_plausible_result(monkeypatch, code, status):
    payload = {"code": code, "solver_status": status}
    monkeypatch.setattr(solver_health.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, -1073741819, json.dumps(payload), ""))
    result = solver_health.check_solver_health()
    assert result["status"] == "unavailable"
    assert result["code"] == "solver_initialization_failed"


def test_policy_exception_cycle_terminates_without_inventing_evidence():
    first = ImportError("ordinary import failure")
    second = OSError("ordinary native failure")
    first.__cause__ = second
    second.__cause__ = first
    assert solver_health._policy_blocked(first) is False


def test_machine_output_is_sanitized_and_timestamp_is_parent_generated(monkeypatch):
    payload = {"code": "ready", "solver_status": "FEASIBLE", "status": "unknown",
               "message": "private dependency path", "checked_at": "untrusted timestamp"}
    monkeypatch.setattr(solver_health.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 0, "native startup output\n" + json.dumps(payload), ""))
    result = solver_health.check_solver_health()
    assert result["status"] == "operational"
    assert result["solver_status"] == "FEASIBLE"
    assert result["message"] == solver_health.MESSAGES["ready"]
    assert result["checked_at"] != payload["checked_at"]
    assert "private" not in json.dumps(result)


def test_solver_health_endpoint_operational_status_contract_only(tmp_path, monkeypatch):
    # This explicit fake verifies HTTP mapping, not the installed solver runtime.
    result = solver_health._result("ready", "OPTIMAL")
    monkeypatch.setattr(main, "check_solver_health", lambda: result)
    with TestClient(main.create_app(tmp_path / "contract.sqlite")) as client:
        response = client.get("/api/solver-health")
        assert response.status_code == 200
        assert response.json() == result


def test_actual_solver_health_endpoint_reports_truth_without_reading_database(tmp_path):
    # Runs the real isolated child; works on either a ready or a blocked machine.
    app = main.create_app(tmp_path / "actual.sqlite")
    with TestClient(app) as client:
        def forbid_database_access(*_args, **_kwargs):
            pytest.fail("The solver runtime check must not read or write personal data")
        event.listen(app.state.engine, "before_cursor_execute", forbid_database_access)
        try:
            liveness = client.get("/health")
            response = client.get("/api/solver-health")
        finally:
            event.remove(app.state.engine, "before_cursor_execute", forbid_database_access)
        assert liveness.status_code == 200
        assert liveness.json() == {"status": "ok", "app": "schedule-builder"}
        result = response.json()
        assert result["checked_at"]
        assert result["code"] in solver_health.MESSAGES
        assert result["message"] == solver_health.MESSAGES[result["code"]]
        if result["status"] == "operational":
            assert response.status_code == 200
            assert result["code"] == "ready"
            assert result["solver_status"] in {"FEASIBLE", "OPTIMAL"}
        else:
            assert response.status_code == 503
            assert result["status"] == "unavailable"
            assert result["code"] != "ready"
