"""Read-only CP-SAT runtime diagnosis, isolated from the API process and user data.

This checks a known-feasible model, not the feasibility of any personal schedule.
Detailed exceptions stay in the server's local log; public results use fixed text.
"""
from datetime import datetime, timezone
from importlib import import_module
import json
import logging
from pathlib import Path
import subprocess
import sys


logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
PROBE_TIMEOUT_SECONDS = 15
MESSAGES = {
    "ready": "CP-SAT passed a small test solve and is ready to generate schedules.",
    "missing_dependency": "A required solver package is missing. Review the local diagnostic log and repair the project dependencies, then retry.",
    "windows_policy_blocked": "Windows Application Control blocked a required solver component. See the local Windows runtime guide for recovery; administrator rights alone cannot override this block.",
    "dependency_load_failed": "A solver dependency could not load. Review the local server log and repair the installed solver dependencies, then retry.",
    "solver_configuration_error": "The solver rejected its test configuration. Review the local server log and repair the solver installation, then retry.",
    "solver_initialization_failed": "The solver could not initialize or run. Review the local server log and repair the solver installation, then retry.",
    "solver_probe_failed": "The solver test did not finish successfully. Review the local server log, then retry the runtime check.",
}


def _result(code, solver_status=None):
    result = {
        "status": "operational" if code == "ready" else "unavailable",
        "code": code,
        "message": MESSAGES[code],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if solver_status is not None:
        result["solver_status"] = solver_status
    return result


def _policy_blocked(error):
    """Recognize explicit policy evidence, including chained DLL load errors."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        message = str(error).lower()
        # ERROR_INVALID_IMAGE_HASH (577) alone can also mean a corrupt binary;
        # ERROR_ACCESS_DISABLED_BY_POLICY (1260) explicitly identifies policy.
        if (getattr(error, "winerror", None) == 1260
                or "application control" in message
                or "blocked by group policy" in message):
            return True
        error = error.__cause__ or error.__context__
    return False


def _run_probe():
    """Execute inside a short-lived child; tests explicitly mock this boundary."""
    try:
        cp_model = import_module("ortools.sat.python.cp_model")
    except Exception as error:
        logger.exception("CP-SAT runtime check: dependency import failed")
        code = ("windows_policy_blocked" if _policy_blocked(error)
                else "missing_dependency" if isinstance(error, ModuleNotFoundError)
                else "dependency_load_failed")
        return _result(code)

    try:
        model = cp_model.CpModel()
        value = model.new_int_var(0, 1, "runtime_check")
        model.add(value == 1)
        validation_error = model.validate()
        if validation_error:
            logger.error("CP-SAT runtime check: model validation failed: %s", validation_error)
            return _result("solver_configuration_error")
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 2
        solver.parameters.num_search_workers = 1
        solver.parameters.log_search_progress = False
        solver.parameters.random_seed = 42
        status = solver.solve(model)
        status_name = solver.status_name(status)
        if status == cp_model.MODEL_INVALID:
            logger.error("CP-SAT runtime check: MODEL_INVALID: %s", solver.response_stats())
            return _result("solver_configuration_error", "MODEL_INVALID")
        if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            logger.error("CP-SAT runtime check: known-feasible test returned %s: %s", status_name, solver.response_stats())
            # INFEASIBLE here is a broken runtime probe, never an infeasible user schedule.
            return _result("solver_probe_failed", status_name)
        if solver.value(value) != 1:
            logger.error("CP-SAT runtime check: solved value did not satisfy the test constraint")
            return _result("solver_probe_failed", status_name)
        return _result("ready", status_name)
    except Exception as error:
        logger.exception("CP-SAT runtime check: solver construction or execution failed")
        code = ("windows_policy_blocked" if _policy_blocked(error)
                else "solver_configuration_error" if isinstance(error, (ValueError, TypeError, AttributeError))
                else "solver_initialization_failed")
        return _result(code)


def check_solver_health():
    """Actually solve using this interpreter, without exposing native crashes to API."""
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "backend.app.solver_health", "--worker"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=PROBE_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        logger.exception("CP-SAT runtime check timed out after %s seconds", PROBE_TIMEOUT_SECONDS)
        return _result("solver_probe_failed")
    except Exception as error:
        logger.exception("CP-SAT runtime check could not start the interpreter")
        return _result("windows_policy_blocked" if _policy_blocked(error) else "solver_initialization_failed")
    if completed.stderr.strip():
        logger.error("CP-SAT runtime check local diagnostic:\n%s", completed.stderr.rstrip())
    try:
        # Keep native diagnostic output out of the public response.
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        code = payload["code"]
        if code not in MESSAGES:
            raise ValueError("Unknown diagnostic code")
        solver_status = payload.get("solver_status")
        if solver_status not in {None, "OPTIMAL", "FEASIBLE", "INFEASIBLE", "MODEL_INVALID", "UNKNOWN"}:
            raise ValueError("Unknown solver status")
        if code == "ready" and (completed.returncode != 0 or solver_status not in {"OPTIMAL", "FEASIBLE"}):
            raise ValueError("Runtime did not report a successful solve")
        if code != "ready" and completed.returncode not in {0, 1}:
            raise ValueError("Runtime process exited abnormally")
        return _result(code, solver_status)
    except (ValueError, KeyError, IndexError, TypeError):
        logger.exception("CP-SAT runtime check exited without a valid result (exit %s); stdout: %s", completed.returncode, completed.stdout)
        return _result("solver_initialization_failed" if completed.returncode else "solver_probe_failed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    result = _run_probe() if "--worker" in sys.argv else check_solver_health()
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "operational" else 1)
