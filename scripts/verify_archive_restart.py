"""Verify archive/completion persistence using real localhost server processes.

All writes target disposable QA databases. The personal database is read only.
The seeded past schedule is clearly marked; regeneration executes real CP-SAT.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.archive_history_audit import audit, compare  # noqa: E402


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class Server:
    def __init__(self, database, output):
        self.database = database
        self.output = output
        self.process = None
        self.run = 0
        self.env = {**os.environ, "SCHEDULE_BUILDER_DB": str(database),
                    "SCHEDULE_BUILDER_OFFLINE": "1",
                    "SCHEDULE_BUILDER_RUNTIME_DIR": str(output / "runtime"),
                    "SCHEDULE_BUILDER_ROUTE_CACHE": str(output / "routes.sqlite")}

    def request(self, method, path, data=None, expected=200):
        encoded = None if data is None else json.dumps(data).encode()
        request = Request(f"http://127.0.0.1:{self.port}{path}", data=encoded, method=method,
                          headers={"Content-Type": "application/json"})
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=2 if path == "/health" else 60) as response:
                status, body = response.status, response.read()
        except HTTPError as error:
            status, body = error.code, error.read()
        require(status == expected, f"{method} {path}: expected {expected}, got {status}: {body.decode()[:1000]}")
        return json.loads(body) if body else None

    def start(self):
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            self.port = candidate.getsockname()[1]
        self.run += 1
        self.instance = uuid4().hex
        self.stdout = (self.output / f"server-{self.database.stem}-{self.run}.out.log").open("wb")
        self.stderr = (self.output / f"server-{self.database.stem}-{self.run}.err.log").open("wb")
        self.process = subprocess.Popen([sys.executable, "scripts/serve.py", "--port", str(self.port), "--instance", self.instance],
                                        cwd=ROOT, env=self.env, stdout=self.stdout, stderr=self.stderr,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            require(self.process.poll() is None, "Server exited before health check; inspect isolated server logs")
            try:
                require(self.request("GET", "/health")["status"] == "ok", "Server unhealthy")
                identity = self.request("GET", "/_daycraft/runtime")
                require(identity["instance"] == self.instance, "Unexpected listener identity")
                self.pid = identity["pid"]
                return self
            except (URLError, TimeoutError, ConnectionError):
                time.sleep(0.1)
        raise AssertionError("Server startup exceeded 45 seconds")

    def stop(self):
        if self.process is None:
            return
        try:
            if self.process.poll() is None:
                stopped = subprocess.run([sys.executable, "scripts/stop.py", "--port", str(self.port), "--instance", self.instance],
                                         cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=25,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                require(stopped.returncode == 0, "Authenticated graceful stop failed: " + stopped.stderr)
                self.process.wait(timeout=20)
            require(self.process.returncode == 0, "Server did not shut down cleanly")
        finally:
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=10)
            self.stdout.close()
            self.stderr.close()
            self.process = None

    @contextmanager
    def running(self):
        try:
            yield self.start()
        finally:
            self.stop()


def copy_database(source, target):
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original, sqlite3.connect(target) as copied:
        original.backup(copied)


def seed_plan(database, definition, assignment):
    date = "2020-11-09"
    session_id, plan_id = "archive-qa-logical-session", "archive-qa-split-plan"
    blocks = [{"id": f"archive-qa-chunk-{index}", "title": definition["title"], "kind": "task",
               "task_id": definition["id"], "task_definition_id": definition["id"],
               "task_assignment_id": assignment["id"], "logical_session_id": session_id,
               "chunk_index": index, "start": f"{date}T{8 + index:02}:00:00-05:00",
               "end": f"{date}T{8 + index:02}:30:00-05:00", "status": "todo", "locked": False}
              for index in range(2)]
    plan = {"id": plan_id, "date": date, "mode": "balanced", "status": "feasible", "workload_level": "medium",
            "blocks": blocks, "unallocated": [], "conflicts": [], "explanations": [], "stats": {},
            "solver_status": "SEEDED_QA_FIXTURE_NOT_GENERATED"}
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO schedules(id,date,payload) VALUES(?,?,?)", (plan_id, date, json.dumps(plan)))
        db.execute('INSERT INTO logical_sessions(id,assignment_id,"index",target_minutes,completed_minutes,baseline_completed_minutes,status) VALUES(?,?,0,60,0,0,?)', (session_id, assignment["id"], "todo"))
        for block in blocks:
            db.execute("INSERT INTO task_chunks(id,logical_session_id,schedule_id,start,end,status,credited_minutes) VALUES(?,?,?,?,?,?,0)", (block["id"], session_id, plan_id, block["start"], block["end"], "todo"))
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/schedule_builder.db")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / "test-results/archive-history" / ("restart-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True, exist_ok=False)
    evidence = {"output": str(output), "personal_database_written": False, "fixture_provenance": "Explicit isolated split-session seed", "checks": []}
    def checked(name):
        evidence["checks"].append(name)
        print("PASS " + name, flush=True)
    personal_before = audit(args.source)
    copied = output / "personal-copy.sqlite"
    copy_database(args.source, copied)
    copied_before = audit(copied)
    personal = Server(copied, output)
    with personal.running():
        history = personal.request("GET", "/api/completed-tasks?limit=100")
        known = [block for block in copied_before["confirmed_blocks"] if block.get("completion_confirmed_at")]
        require(history["total"] >= len(known), "Timestamped confirmations not backfilled")
        imported_count = history["total"]
        first_pid = personal.pid
    copied_after = audit(copied)
    preservation = compare(copied_before, copied_after)
    require(all(row["table"] == "alembic_version" for row in preservation["missing_rows"]), "Migration removed existing records")
    require(not preservation["confirmed_blocks_missing_or_changed"], "Migration changed confirmed saved blocks")
    require(preservation["work_credit_unchanged"], "Migration changed session or chunk credit")
    require(all(row["table"] == "alembic_version" for row in preservation["changed_rows"]), "Migration rewrote personal data")
    checked("personal-copy migration preserves every existing row and verified work credit")
    with personal.running():
        require(personal.pid != first_pid, "Expected a new OS backend process")
        require(personal.request("GET", "/api/completed-tasks?limit=100")["total"] == imported_count, "Restart duplicated backfilled confirmations")
    checked("personal-copy backfill remains idempotent across actual process restart")

    fixture = output / "fixture.sqlite"
    server = Server(fixture, output)
    with server.running():
        settings = server.request("GET", "/api/state")["settings"]
        settings.update(meals=[], focus_minutes=60, break_minutes=0, work_start="08:00", work_end="18:00")
        server.request("PUT", "/api/settings", settings)
        definition = server.request("POST", "/api/task-definitions", {"title": "Archive QA split reading", "session_minutes": 60, "min_sessions_per_week": 1, "min_sessions_per_day": 0, "allow_splitting": True, "min_chunk_minutes": 30}, expected=201)
        assignment = server.request("POST", "/api/task-weeks", {"task_definition_id": definition["id"], "week_start": "2020-11-08"}, expected=201)
    plan = seed_plan(fixture, definition, assignment)
    with server.running():
        archive = server.request("POST", "/api/schedule-archives", {"schedule_id": plan["id"]})
        archive_id = archive["id"]
        repeated = server.request("POST", "/api/schedule-archives", {"schedule_id": plan["id"]})
        require(repeated["id"] == archive_id, "Repeat save created duplicate archive")
        saved_blocks = {block["id"]: block for block in archive["payload"]["blocks"]}
        require(all(all(saved_blocks.get(block["id"], {}).get(key) == value for key, value in block.items()) for block in plan["blocks"]), "Archive lost seeded block values")
        checked("explicit save captures full plan and repeated save is idempotent")
        edited = deepcopy(plan["blocks"])
        edited.append({"id": "archive-qa-personal", "title": "Archive QA personal block", "kind": "personal", "start": "2020-11-09T10:00:00-05:00", "end": "2020-11-09T10:15:00-05:00", "status": "todo", "locked": False})
        server.request("PUT", f"/api/schedules/{plan['id']}", {"blocks": edited})
        saved = server.request("GET", f"/api/schedule-archives/{archive_id}")
        require(any(block["id"] == "archive-qa-personal" for block in saved["payload"]["blocks"]), "Manual edit did not synchronize attached archive")
        checked("validated manual edit synchronizes attached archive")
        first = plan["blocks"][0]
        completion_path = f"/api/schedules/{plan['id']}/blocks/{first['id']}/completion"
        server.request("POST", completion_path, {"completed": True})
        once = server.request("GET", "/api/completed-tasks")
        server.request("POST", completion_path, {"completed": True})
        twice = server.request("GET", "/api/completed-tasks")
        require(twice == once and once["total"] == 1, "Repeated confirmation duplicated completion evidence")
        require(once["summary"]["completed_minutes"] == 30, "Split chunk credited wrong minutes")
        partial_archive = server.request("GET", f"/api/schedule-archives/{archive_id}")
        require(partial_archive["completed_count"] == 1 and partial_archive["completed_minutes"] == 30, "Archive completion summary not synchronized")
        server.request("POST", completion_path, {"completed": False})
        require(server.request("GET", "/api/completed-tasks")["total"] == 0, "Undo left current completion evidence")
        server.request("POST", completion_path, {"completed": True})
        second = plan["blocks"][1]
        server.request("POST", f"/api/schedules/{plan['id']}/blocks/{second['id']}/completion", {"completed": True})
        complete = server.request("GET", "/api/completed-tasks")
        require(complete["total"] == 2 and complete["summary"]["completed_minutes"] == 60, "Split work double counted or lost")
        require(complete["summary"]["logical_sessions_completed"] == 1, "Split chunks must count one completed logical session")
        checked("confirmation, repeated confirmation, undo and split-session totals remain exact")
        frozen = server.request("GET", f"/api/schedule-archives/{archive_id}")
        version = server.request("POST", "/api/schedule-archives", {"schedule_id": plan["id"], "new_version": True})
        require(version["id"] != archive_id, "Explicit new version reused old archive")
        require(not server.request("GET", f"/api/schedule-archives/{archive_id}")["attached"], "Prior revision remained attached")
        require(server.request("GET", "/api/completed-tasks")["total"] == 2, "Archiving duplicated completed work")
        server.request("PUT", f"/api/day-preferences/{plan['date']}", {"workload_level": "low"})
        stale = server.request("GET", f"/api/schedule-archives/{version['id']}")
        active = server.request("GET", f"/api/schedules?date={plan['date']}")[0]
        require(active.get("preferences_dirty"), "Changed preferences did not mark the active schedule stale")
        require(stale["payload"] == version["payload"], "Background preference edits rewrote the historical snapshot")
        require(server.request("GET", f"/api/schedule-archives/{archive_id}")["payload"] == frozen["payload"], "Frozen prior revision was changed")
        checked("new version freezes prior revision and changed preferences mark only the active plan stale")
        generated = server.request("POST", "/api/schedules/generate", {"date": plan["date"]})
        require(generated["solver_status"] in {"OPTIMAL", "FEASIBLE"}, "Regeneration did not execute CP-SAT successfully")
        require(server.request("GET", "/api/completed-tasks")["total"] == 2, "Regeneration duplicated or erased completed work")
        require(not server.request("GET", f"/api/schedule-archives/{version['id']}")["attached"], "Regeneration did not detach prior revision")
        current = server.request("POST", "/api/schedule-archives", {"schedule_id": plan["id"]})
        require(current["id"] not in {archive_id, version["id"]}, "Regenerated plan did not create fresh revision")
        checked("real CP-SAT regeneration creates a revision and preserves completion evidence")
        server.request("DELETE", f"/api/task-definitions/{definition['id']}?delete_assignments=true", expected=204)
        require(server.request("GET", "/api/completed-tasks")["total"] == 2, "Removing task definition erased completed history")
        require(server.request("GET", f"/api/schedule-archives/{archive_id}")["payload"] == frozen["payload"], "Task removal rewrote frozen history")
        before_delete = server.request("GET", "/api/completed-tasks")
        server.request("DELETE", f"/api/schedule-archives/{archive_id}", expected=204)
        require(server.request("GET", "/api/completed-tasks") == before_delete, "Archive deletion altered completion evidence")
        remaining = server.request("GET", "/api/schedule-archives")
        require(all(row["id"] != archive_id for row in remaining["items"]), "Deleted archive remained visible")
        first_pid = server.pid
        checked("task removal and archive deletion preserve independent completed work")
    with server.running():
        require(server.pid != first_pid, "Fixture restart reused old process")
        require(server.request("GET", "/api/completed-tasks") == before_delete, "Completed history changed after process restart")
        require(server.request("GET", "/api/schedule-archives")["total"] == remaining["total"], "Archive count changed after restart")
        require(not any(row["id"] == definition["id"] for row in server.request("GET", "/api/task-definitions")), "Removed definition returned after restart")
        server.request("GET", f"/api/schedule-archives/{archive_id}", expected=404)
    checked("archives, archive deletion and completed history survive actual OS process restart")
    require(audit(args.source) == personal_before, "Read-only integration changed the personal database")
    for path in (fixture, copied):
        result = audit(path)
        require(result["integrity_check"] == "ok" and not result["foreign_key_check"], "Isolated database integrity failed")
    checked("personal database unchanged and both isolated databases pass SQLite integrity/FK checks")
    evidence.update(status="passed", personal_copy_backfilled_completions=imported_count, real_process_runs=personal.run + server.run, cp_sat_executed=True)
    (output / "report.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    (output / "personal-copy-preservation.json").write_text(json.dumps(preservation, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
