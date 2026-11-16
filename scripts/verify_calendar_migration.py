"""Read-only audit that a calendar upgrade retains pre-upgrade personal records."""
import argparse
import json
from pathlib import Path
import sqlite3


def snapshot(path):
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        return {
            "entities": {(collection, key): json.loads(payload) for collection, key, payload in db.execute("SELECT collection,id,payload FROM entities")},
            "configuration": {key: json.loads(payload) for key, payload in db.execute("SELECT id,payload FROM configuration")},
            "schedules": {key: json.loads(payload) for key, payload in db.execute("SELECT id,payload FROM schedules")},
        }


def audit(before_path, after_path):
    before, after = snapshot(before_path), snapshot(after_path)
    for table in ("entities", "configuration"):
        for key, value in before[table].items():
            assert key in after[table], f"Missing original {table} record: {key}"
            current = after[table][key]
            assert all(current.get(field) == item for field, item in value.items()), f"Changed original {table} fields: {key}"
    for key, value in before["schedules"].items():
        assert key in after["schedules"], f"Missing saved schedule: {key}"
        assert after["schedules"][key]["blocks"] == value["blocks"], f"Changed historical schedule blocks: {key}"
    counts = {table: len(rows) for table, rows in before.items()}
    print("Original records retained:", json.dumps(counts))
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", help="Pre-upgrade SQLite backup")
    parser.add_argument("after", help="Upgraded SQLite database")
    arguments = parser.parse_args()
    audit(arguments.before, arguments.after)
