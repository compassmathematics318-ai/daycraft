"""Replay real saved identities on an isolated database; no solver execution.

Only the copy receives preferences/completion writes. Completion is exercised
with an explicit later test clock; this does not attest real work was done.
"""
import json
import os
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SCHEDULE_BUILDER_OFFLINE"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from backend.app import task_library, work_confirmation  # noqa: E402
from backend.app.database import LogicalSession, Schedule, TaskChunk  # noqa: E402
from backend.app.main import create_app, settings_of  # noqa: E402


def rows(db):
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {table: sorted(db.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr) for table in tables}


def request(client, method, path, data=None):
    response = client.request(method, "/api" + path, json=data)
    assert response.is_success, response.text
    return response.json()


def main():
    output = ROOT / "test-results/session-completion"
    output.mkdir(exist_ok=True)
    source = ROOT / "data/schedule_builder.db"
    target = output / f"personal-replay-{datetime.now():%Y%m%d-%H%M%S}.sqlite"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db, sqlite3.connect(target) as copied:
        before = rows(db)
        db.backup(copied)
    levels = ["very_low", "low", "medium", "high", "very_high"]
    with TestClient(create_app(target)) as client:
        original = request(client, "GET", "/state")
        with client.app.state.session_factory() as db:
            plan = next(row for row in db.scalars(select(Schedule)) if any(block.get("logical_session_id") for block in row.payload["blocks"]))
            payload = deepcopy(plan.payload)
        block = next(block for block in payload["blocks"] if block.get("logical_session_id") and block["status"] != "completed")
        end = datetime.fromisoformat(block["end"])
        assert end > datetime.now(end.tzinfo), "Replay fixture no longer future; update the explicit real-clock assertion"
        response = client.post(f"/api/schedules/{plan.id}/blocks/{block['id']}/completion", json={"completed": True})
        assert response.status_code == 409, response.text
        for level in levels:
            saved = request(client, "PUT", f"/day-preferences/{plan.date}", {"workload_level": level})
            assert saved["workload_level"] == level
            assert request(client, "GET", f"/day-preferences/{plan.date}") == saved
        assert request(client, "GET", "/day-preferences/2099-01-01")["workload_level"] == "medium"
        after_preferences = request(client, "GET", "/state")
        assert after_preferences == original, "Workload metadata modified application settings or saved plans"
        clock = end + timedelta(days=1)
        with client.app.state.session_factory() as db:
            row = db.get(Schedule, plan.id)
            settings = settings_of(db)
            session = db.get(LogicalSession, block["logical_session_id"])
            original_completed = session.completed_minutes
            original_chunk_status = db.get(TaskChunk, block["id"]).status
            original_week = task_library.week_state(db, plan.date)
            preserved = task_library.regeneration_blocks(db, row.payload["blocks"], settings, now=clock)
            assert any(item["id"] == block["id"] and item.get("_elapsed_work_history") for item in preserved)
            assert session.completed_minutes == original_completed
            work_confirmation.confirm_block(db, row, block["id"], True, settings, now=clock)
            duration = task_library.length(block["start"], block["end"])
            assert session.completed_minutes == original_completed + duration
            confirmed = next(item for item in row.payload["blocks"] if item["id"] == block["id"])
            assert confirmed["completion_confirmed_at"] == clock.isoformat()
            assert all(confirmed.get(key) == block.get(key) for key in ("task_id", "task_assignment_id", "logical_session_id", "start", "end", "location_id", "resolved_location_id"))
            stamp = confirmed["completion_confirmed_at"]
            work_confirmation.confirm_block(db, row, block["id"], True, settings, now=clock + timedelta(minutes=1))
            assert session.completed_minutes == original_completed + duration
            assert next(item for item in row.payload["blocks"] if item["id"] == block["id"])["completion_confirmed_at"] == stamp
            db.commit()
        state = request(client, "GET", "/state")
        assert state["task_definitions"] == original["task_definitions"]
    with TestClient(create_app(target)) as restarted:
        assert request(restarted, "GET", f"/day-preferences/{plan.date}")["workload_level"] == "very_high"
        with restarted.app.state.session_factory() as db:
            row = db.get(Schedule, plan.id)
            assert next(item for item in row.payload["blocks"] if item["id"] == block["id"])["completion_confirmed_at"] == stamp
            work_confirmation.confirm_block(db, row, block["id"], False, settings_of(db), now=clock)
            assert db.get(LogicalSession, block["logical_session_id"]).completed_minutes == original_completed
            assert db.get(TaskChunk, block["id"]).status == original_chunk_status
            assert task_library.week_state(db, plan.date) == original_week
            db.commit()
        assert request(restarted, "GET", "/state")["task_definitions"] == original["task_definitions"]
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
        assert before == rows(db), "Personal database changed during replay"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    with sqlite3.connect(target) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    evidence = {"database_copy": str(target), "real_saved_block_id": block["id"],
                "future_confirmation_rejected_under_real_clock": True,
                "completion_clock_explicitly_simulated": clock.isoformat(),
                "idempotence_restart_and_exact_undo": True,
                "elapsed_history_preserved_without_credit": True,
                "workload_five_levels_persist_without_modifying_schedule_or_settings": True,
                "canonical_task_status_and_personal_database_unchanged": True,
                "cp_sat_executed": False}
    (output / "personal-replay.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
