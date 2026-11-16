"""Back up and audit the personal database without adding demonstration records."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "schedule_builder.db"
BACKUP = ROOT / "data" / "backups" / "pre-project-redesign-20261110.sqlite"


def connect_readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def records(connection, table):
    return sorted(connection.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr)


def fingerprint(rows):
    encoded = json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode()
    return {"count": len(rows), "sha256": hashlib.sha256(encoded).hexdigest()}


def backup():
    if BACKUP.exists():
        raise SystemExit(f"Preserving existing backup: {BACKUP}")
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    with connect_readonly(DATABASE) as source, sqlite3.connect(BACKUP) as target:
        source.backup(target)
    with connect_readonly(BACKUP) as source:
        report = {name: fingerprint(records(source, name)) for name in
                  ("entities", "configuration", "activities", "occurrences", "schedules")}
    report["backup"] = str(BACKUP)
    (ROOT / "test-results" / "projects-data-before.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def audit(after_path):
    with connect_readonly(BACKUP) as before, connect_readonly(after_path) as after:
        report = {}
        for table in ("configuration", "activities", "occurrences", "schedules"):
            original, current = records(before, table), records(after, table)
            assert current == original, f"Changed original {table} records"
            report[table] = fingerprint(current)
        original = {(r[0], r[1]): json.loads(r[2]) for r in records(before, "entities")}
        current = {(r[0], r[1]): json.loads(r[2]) for r in records(after, "entities")}
        assert original.keys() == current.keys(), "Existing entities added or removed"
        legacy_count = 0
        for key, payload in original.items():
            value = current[key]
            assert all(value.get(field) == item for field, item in payload.items()), f"Original fields changed: {key}"
            assert set(value) - set(payload) <= {"project_id"}, f"Unexpected migration fields: {key}"
            if key[0] == "tasks" and payload.get("kind") == "project":
                legacy_count += 1
                project_id = value.get("project_id")
                assert project_id, f"Legacy work lacks project association: {key}"
                link = after.execute("SELECT project_id FROM task_projects WHERE task_id=?", (key[1],)).fetchone()
                assert link == (project_id,), f"Missing FK link: {key}"
                project = after.execute("SELECT legacy_snapshot FROM projects WHERE id=?", (project_id,)).fetchone()
                assert project and json.loads(project[0]) == payload, f"Legacy snapshot differs: {key}"
        assert after.execute("PRAGMA foreign_key_check").fetchall() == [], "Invalid foreign keys"
        assert after.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        report.update(original_entities_preserved=len(original), legacy_work_linked=legacy_count,
                      historical_schedules_unchanged=True, foreign_keys_valid=True)
    output = ROOT / "test-results" / ("projects-data-after.json" if Path(after_path).resolve() == DATABASE else "projects-staged-migration-audit.json")
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def stage():
    """Exercise the real upgrade against a copy before touching the live DB."""
    sys.path.insert(0, str(ROOT))
    from backend.app.database import build_database
    from backend.app.migrate import migrate

    staged = ROOT / "test-results" / "projects-staged-migration.sqlite"
    if staged.exists():
        raise SystemExit(f"Staged database already exists; preserve it: {staged}")
    with connect_readonly(BACKUP) as source, sqlite3.connect(staged) as target:
        source.backup(target)
    engine, _ = build_database(staged)
    migrate(engine)
    engine.dispose()
    audit(staged)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "stage", "audit"))
    parser.add_argument("--database", type=Path, default=DATABASE)
    options = parser.parse_args()
    if options.action == "backup":
        backup()
    elif options.action == "stage":
        stage()
    else:
        audit(options.database)
