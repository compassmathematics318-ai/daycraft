"""Repair only the user-identified, independently audited unassigned test task.

Read-only by default. --apply invokes the existing localhost deletion API after
rechecking its stable identity and absence of dependencies or historical work.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
import sqlite3
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "946c47d8-5ade-4394-81c3-b5a23653361b"
PLACE_ID = "06cd07fb-6fc6-4496-b865-ce01ea7a5dfa"


def api(path, method="GET"):
    with urlopen(Request("http://127.0.0.1:8765/api" + path, method=method), timeout=15) as response:
        return json.load(response) if response.status != 204 else None


def snapshot(db):
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {table: sorted(db.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr) for table in tables}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    database = ROOT / "data/schedule_builder.db"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        before = snapshot(db)
        row = db.execute("SELECT payload,legacy_task_id,project_id,related_activity_id FROM task_definitions WHERE id=?", (TASK_ID,)).fetchone()
        if not row or json.loads(row[0]).get("deleted_at"):
            print("Identified task is already deleted; no change made.")
            return
        definition = json.loads(row[0])
        assert definition["title"] == "hi" and definition["location_id"] == PLACE_ID
        assert not any(row[1:]) and not definition.get("recurrence")
        assert not db.execute("SELECT 1 FROM task_weeks WHERE task_definition_id=?", (TASK_ID,)).fetchone()
        assert not any(TASK_ID in json.loads(payload).get("dependencies", []) for (payload,) in db.execute("SELECT payload FROM task_definitions"))
        assert not any(TASK_ID in json.loads(payload).get("overrides", {}).get("dependencies", []) for (payload,) in db.execute("SELECT payload FROM task_weeks"))
        assert not any(TASK_ID in (block.get("task_id"), block.get("task_definition_id"))
                       for (payload,) in db.execute("SELECT payload FROM schedules") for block in json.loads(payload).get("blocks", []))
        live = next(item for item in api("/state")["task_definitions"] if item["id"] == TASK_ID)
        assert live["title"] == "hi" and live["location_id"] == PLACE_ID
        if not args.apply:
            print("Verified exact ID and CMH location; no weeks, sessions, schedule history or inbound dependencies. Dry run only.")
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = ROOT / "data/backups" / f"pre-reported-hi-repair-{stamp}.sqlite"
        with sqlite3.connect(backup) as target:
            db.backup(target)
    api(f"/task-definitions/{TASK_ID}?delete_assignments=true", "DELETE")
    state = api("/state")
    assert not any(item["id"] == TASK_ID for item in state["task_definitions"])
    assert any(item["id"] == PLACE_ID for item in state["locations"])
    overview = api("/location-overview")
    assert TASK_ID not in json.dumps(overview)
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        after = snapshot(db)
        for table in before:
            if table == "task_definitions":
                assert [row for row in before[table] if row[0] != TASK_ID] == [row for row in after[table] if row[0] != TASK_ID]
            else:
                assert before[table] == after[table], f"Unexpected changed table: {table}"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    evidence = {"task_id": TASK_ID, "place_id": PLACE_ID, "backup": str(backup),
                "absent_from_active_definitions_and_map": True, "shared_place_preserved": True,
                "all_other_records_unchanged": True}
    path = ROOT / "test-results/task-lifecycle/reported-hi-repair.json"
    path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
