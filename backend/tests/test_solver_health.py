"""Diagnostic classification uses explicit fakes; readiness still needs a real solve."""
import json
import logging
from types import SimpleNamespace
import subprocess

import pytest

from backend.app import solver_health


class FakeModel:
    def new_int_var(self, *_):
        return 1

    def add(self, _):
        pass

    def validate(self):
        return ""


class FakeSolver:
    def __init__(self):
        self.parameters = SimpleNamespace()

    def solve(self, _):
        return 4

    def status_name(self, status):
        return {0: "UNKNOWN", 1: "MODEL_INVALID", 2: "FEASIBLE", 3: "INFEASIBLE", 4: "OPTIMAL"}[status]

    def value(self, _):
        return 1

    def response_stats(self):
        return "local solver detail"


@pytest.fixture
def fake_runtime(monkeypatch):
    module = SimpleNamespace(CpModel=FakeModel, CpSolver=FakeSolver, OPTIMAL=4, FEASIBLE=2, MODEL_INVALID=1)
    monkeypatch.setattr(solver_health, "import_module", lambda _: module)
    return module


@pytest.mark.parametrize("error,code", [
    (ModuleNotFoundError("No module named 'ortools'"), "missing_dependency"),
    (ImportError("DLL load failed: An Application Control policy has blocked this file."), "windows_policy_blocked"),
    (OSError("Native library not available"), "dependency_load_failed"),
    (ImportError("DLL load failed: The specified module could not be found."), "dependency_load_failed"),
    (RuntimeError("import-time initialization failed"), "dependency_load_failed"),
])
def test_import_failures_are_actionable_without_exposing_details(monkeypatch, caplog, error, code):
    def unavailable(_):
        raise error
    monkeypatch.setattr(solver_health, "import_module", unavailable)
    with caplog.at_level(logging.ERROR):
        result = solver_health._run_probe()
    assert result["status"] == "unavailable"
    assert result["code"] == code
    assert str(error) not in result["message"]
    assert any(record.exc_info for record in caplog.records)


def test_chained_windows_policy_code_is_recognized(monkeypatch):
    blocked = OSError("opaque native load error")
    blocked.winerror = 1260
    error = ImportError("dependency failed")
    error.__cause__ = blocked
    def unavailable(_):
        raise error
    monkeypatch.setattr(solver_health, "import_module", unavailable)
    assert solver_health._run_probe()["code"] == "windows_policy_blocked"


def test_invalid_image_hash_alone_does_not_claim_a_policy_block(monkeypatch):
    error = OSError("Windows cannot verify the digital signature for this file")
    error.winerror = 577
    def unavailable(_):
        raise error
    monkeypatch.setattr(solver_health, "import_module", unavailable)
    assert solver_health._run_probe()["code"] == "dependency_load_failed"


@pytest.mark.parametrize("status", [2, 4])
def test_readiness_requires_solver_success_and_checked_solution(fake_runtime, monkeypatch, status):
    monkeypatch.setattr(FakeSolver, "solve", lambda *_: status)
    result = solver_health._run_probe()
    assert result["status"] == "operational"
    assert result["solver_status"] in {"FEASIBLE", "OPTIMAL"}


def test_import_success_without_successful_solve_is_unavailable(fake_runtime, monkeypatch):
    monkeypatch.setattr(FakeSolver, "value", lambda *_: 0)
    assert solver_health._run_probe()["code"] == "solver_probe_failed"


@pytest.mark.parametrize("status,code", [(0, "solver_probe_failed"), (1, "solver_configuration_error"), (3, "solver_probe_failed")])
def test_known_feasible_probe_failure_never_reports_a_schedule_conflict(fake_runtime, monkeypatch, status, code):
    monkeypatch.setattr(FakeSolver, "solve", lambda *_: status)
    result = solver_health._run_probe()
    assert result["status"] == "unavailable"
    assert result["code"] == code
    assert "schedule cannot fit" not in result["message"]


def test_invalid_model_configuration_is_distinct(fake_runtime, monkeypatch):
    monkeypatch.setattr(FakeModel, "validate", lambda _: "private model validation detail")
    result = solver_health._run_probe()
    assert result["code"] == "solver_configuration_error"
    assert "private" not in result["message"]


@pytest.mark.parametrize("error,code", [(RuntimeError("native initialization failed"), "solver_initialization_failed"),
                                         (ValueError("invalid parameter"), "solver_configuration_error")])
def test_solver_exceptions_are_classified(fake_runtime, monkeypatch, error, code):
    def fail(*_):
        raise error
    monkeypatch.setattr(FakeSolver, "solve", fail)
    assert solver_health._run_probe()["code"] == code


def test_child_process_is_same_interpreter_bounded_and_without_database_access(monkeypatch):
    def run(command, **kwargs):
        assert command == [solver_health.sys.executable, "-m", "backend.app.solver_health", "--worker"]
        assert kwargs["cwd"] == solver_health.ROOT
        assert kwargs["timeout"] == solver_health.PROBE_TIMEOUT_SECONDS
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(command, 0, json.dumps({"code": "ready", "solver_status": "OPTIMAL", "message": "do not expose this"}), "")
    monkeypatch.setattr(solver_health.subprocess, "run", run)
    result = solver_health.check_solver_health()
    assert result["status"] == "operational"
    assert result["message"] == solver_health.MESSAGES["ready"]
    assert result["checked_at"]


@pytest.mark.parametrize("stdout,returncode", [
    ("", -1073741819),
    ("{broken", 0),
    ('{"code":"ready"}', 0),
    ('{"code":"ready","solver_status":"OPTIMAL"}', 1),
    ('{"code":"invented"}', 0),
    ('{"code":"ready","solver_status":"private error"}', 0),
])
def test_crashed_or_invalid_child_can_never_report_operational(monkeypatch, stdout, returncode):
    monkeypatch.setattr(solver_health.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout, "private native traceback"))
    result = solver_health.check_solver_health()
    assert result["status"] == "unavailable"
    assert "private" not in json.dumps(result)


def test_child_timeout_is_unavailable(monkeypatch):
    def timeout(*_, **__):
        raise subprocess.TimeoutExpired("solver check", 15)
    monkeypatch.setattr(solver_health.subprocess, "run", timeout)
    assert solver_health.check_solver_health()["code"] == "solver_probe_failed"


def test_blocked_interpreter_start_is_a_policy_failure(monkeypatch):
    def blocked(*_, **__):
        raise OSError("An Application Control policy has blocked this file")
    monkeypatch.setattr(solver_health.subprocess, "run", blocked)
    assert solver_health.check_solver_health()["code"] == "windows_policy_blocked"


def test_child_failure_retains_traceback_only_in_local_logs(monkeypatch, caplog):
    monkeypatch.setattr(solver_health.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 1, json.dumps({"code": "windows_policy_blocked"}), "private blocked file traceback"))
    with caplog.at_level(logging.ERROR):
        result = solver_health.check_solver_health()
    assert result["code"] == "windows_policy_blocked"
    assert "private blocked file traceback" in caplog.text
    assert "private" not in json.dumps(result)
