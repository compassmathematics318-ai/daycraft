"""Read-only online SQLite backup and row-level preservation audit for archive work.

Reports contain identifiers, hashes, and work-credit metadata; raw user content
remains in the database backup and source snapshot, never console output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def audit(path):
    result = {"tables": {}, "confirmed_blocks": [], "work_credit": {}}
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        result["integrity_check"] = db.execute("PRAGMA integrity_check").fetchone()[0]
        result["foreign_key_check"] = [list(row) for row in db.execute("PRAGMA foreign_key_check")]
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            columns = list(db.execute(f"PRAGMA table_info({quoted})"))
            primary = [row[1] for row in sorted(columns, key=lambda item: item[5]) if row[5]]
            rows = [dict(row) for row in db.execute(f"SELECT * FROM {quoted}")]
            records = []
            for row in rows:
                identity = {key: row[key] for key in primary} if primary else {"row_sha256": digest(row)}
                records.append({"identity": identity, "sha256": digest(row)})
            records.sort(key=lambda row: json.dumps(row["identity"], sort_keys=True))
            result["tables"][name] = {"count": len(rows), "sha256": digest(records), "rows": records}
            if name in {"logical_sessions", "task_chunks"}:
                fields = {"id", "assignment_id", "logical_session_id", "schedule_id", "index", "target_minutes", "completed_minutes", "baseline_completed_minutes", "status", "credited_minutes", "start", "end"}
                result["work_credit"][name] = [{key: val for key, val in row.items() if key in fields} for row in rows]
            if name == "schedules":
                for row in rows:
                    payload = json.loads(row["payload"])
                    for block in payload.get("blocks", []):
                        if block.get("completion_confirmed_at") or block.get("completed") or block.get("status") == "completed":
                            fields = {"id", "task_id", "task_definition_id", "assignment_id", "logical_session_id", "start", "end", "status", "completed", "completion_confirmed_at", "credited_minutes", "kind"}
                            result["confirmed_blocks"].append({"schedule_id": row["id"], "date": row["date"], "block_sha256": digest(block), **{key: val for key, val in block.items() if key in fields}})
    return result


def capture(database, output):
    output.mkdir(parents=True, exist_ok=False)
    backup = output / "schedule_builder.before.db"
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    report = audit(backup)
    report.update({"captured_at": datetime.now(timezone.utc).isoformat(), "database": str(database.resolve()), "backup": str(backup.resolve())})
    (output / "before.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    selected = [ROOT / name for name in ("backend", "frontend/src", "scripts", "docs")]
    with zipfile.ZipFile(output / "source.before.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for directory in selected:
            for path in sorted(directory.rglob("*")):
                if path.is_file() and not any(part in {"__pycache__", ".pytest_cache", "node_modules"} for part in path.parts):
                    archive.write(path, path.relative_to(ROOT))
        for name in ("AGENTS.md", "README.md", "Launch Schedule Builder.cmd", "Stop Daycraft.cmd", "frontend/package.json", "frontend/package-lock.json"):
            archive.write(ROOT / name, name)
    return report


def compare(before, after):
    report = {"tables": {}, "missing_rows": [], "changed_rows": [], "confirmed_blocks_missing_or_changed": [], "integrity_check": after["integrity_check"], "foreign_key_check": after["foreign_key_check"]}
    for name, table in before["tables"].items():
        new = after["tables"].get(name, {"count": 0, "rows": []})
        new_rows = {json.dumps(row["identity"], sort_keys=True): row["sha256"] for row in new["rows"]}
        report["tables"][name] = {"before": table["count"], "after": new["count"], "unchanged": table["sha256"] == new.get("sha256")}
        for row in table["rows"]:
            key = json.dumps(row["identity"], sort_keys=True)
            if key not in new_rows:
                report["missing_rows"].append({"table": name, "identity": row["identity"]})
            elif new_rows[key] != row["sha256"]:
                report["changed_rows"].append({"table": name, "identity": row["identity"]})
    current = {(row["schedule_id"], row.get("id")): row for row in after["confirmed_blocks"]}
    for block in before["confirmed_blocks"]:
        if current.get((block["schedule_id"], block.get("id"))) != block:
            report["confirmed_blocks_missing_or_changed"].append(block)
    report["work_credit_unchanged"] = before["work_credit"] == after["work_credit"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/schedule_builder.db")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare", type=Path, help="Existing before.json; write audit and comparison beside it")
    args = parser.parse_args()
    if args.compare:
        after = audit(args.database)
        before = json.loads(args.compare.read_text(encoding="utf-8"))
        result = compare(before, after)
        (args.compare.parent / "after.json").write_text(json.dumps(after, indent=2), encoding="utf-8")
        (args.compare.parent / "comparison.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({key: val for key, val in result.items() if key not in {"tables", "confirmed_blocks_missing_or_changed"}}, indent=2))
    else:
        output = args.output or ROOT / "test-results/archive-history" / datetime.now().strftime("%Y%m%d-%H%M%S")
        report = capture(args.database, output)
        print(json.dumps({"output": str(output.resolve()), "tables": {key: val["count"] for key, val in report["tables"].items()}, "confirmed_blocks": len(report["confirmed_blocks"]), "integrity_check": report["integrity_check"], "foreign_key_violations": len(report["foreign_key_check"])}, indent=2))


if __name__ == "__main__":
    main()
