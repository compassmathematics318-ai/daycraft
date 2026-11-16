"""Consistent personal backup and read-only weekly-task upgrade audit."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "schedule_builder.db"
BACKUP = ROOT / "data" / "backups" / "pre-universal-locations-20261111.sqlite"
TABLES = ("entities", "configuration", "activities", "occurrences", "projects", "task_projects", "schedules", "task_definitions", "task_weeks", "logical_sessions", "task_chunks")


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def rows(connection, table, columns=None):
    projection = ",".join(f'"{column}"' for column in columns) if columns else "*"
    return sorted(connection.execute(f'SELECT {projection} FROM "{table}"').fetchall(), key=repr)


def fingerprint(value):
    digest = hashlib.sha256(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    return {"count": len(value), "sha256": digest}


def backup():
    if BACKUP.exists():
        raise SystemExit(f"Preserving existing backup: {BACKUP}")
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    with readonly(DATABASE) as source, sqlite3.connect(BACKUP) as target:
        source.backup(target)
    with readonly(BACKUP) as source:
        result = {table: fingerprint(rows(source, table)) for table in TABLES}
    result["backup"] = str(BACKUP)
    (ROOT / "test-results" / "locations-data-before.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def audit(path):
    with readonly(BACKUP) as before, readonly(path) as after:
        result = {}
        for table in TABLES:
            columns = [item[1] for item in before.execute(f'PRAGMA table_info("{table}")')]
            old, new = rows(before, table), rows(after, table, columns)
            assert old == new, f"Original {table} records changed during migration"
            result[table] = fingerprint(new)
        assert after.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not after.execute("PRAGMA foreign_key_check").fetchall()
        result.update(original_records_preserved=True, foreign_keys_valid=True,
                      migration=after.execute("SELECT version_num FROM alembic_version").fetchone()[0])
    name = "locations-data-after.json" if Path(path).resolve() == DATABASE else "locations-staged-migration-audit.json"
    (ROOT / "test-results" / name).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def stage():
    sys.path.insert(0, str(ROOT))
    from backend.app.database import build_database
    from backend.app.migrate import migrate
    target = ROOT / "test-results" / f"locations-staged-migration-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite"
    if target.exists():
        raise SystemExit(f"Preserving existing staged database: {target}")
    with readonly(BACKUP) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    engine, _ = build_database(target)
    migrate(engine)
    engine.dispose()
    audit(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "stage", "audit"))
    parser.add_argument("--database", type=Path, default=DATABASE)
    args = parser.parse_args()
    if args.action == "backup":
        backup()
    elif args.action == "stage":
        stage()
    else:
        audit(args.database)


