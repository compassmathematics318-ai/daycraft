"""Read-only data audit and real localhost geocoding delivery checks."""
import argparse
import json
from pathlib import Path
import sqlite3
import time

import httpx

from verify_daily_limits_migration import TABLES, fingerprint, readonly, rows

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "schedule_builder.db"
BACKUP = ROOT / "data" / "backups" / "pre-search-repair-20261111.sqlite"
QUERIES = ["SLC Waterloo", "Student Life Centre University of Waterloo", "Student Life Centre",
           "QNC Waterloo", "Quantum Nano Centre Waterloo", "MC University of Waterloo",
           "East Campus 4 Waterloo"]


def backup():
    if BACKUP.exists():
        raise SystemExit(f"Preserving existing backup: {BACKUP}")
    with readonly(DATABASE) as source, sqlite3.connect(BACKUP) as destination:
        source.backup(destination)
    print(f"Backup created: {BACKUP}")


def audit():
    with readonly(BACKUP) as before, readonly(DATABASE) as after:
        result = {}
        for table in TABLES:
            old, new = rows(before, table), rows(after, table)
            assert old == new, f"Personal {table} records changed"
            result[table] = fingerprint(new)
        assert after.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not after.execute("PRAGMA foreign_key_check").fetchall()
        result["original_records_preserved"] = True
    return result


def search(base_url):
    results = []
    with httpx.Client(timeout=45) as client:
        for query in QUERIES:
            start = time.monotonic()
            response = client.post(f"{base_url}/api/geocode", json={"query": query})
            payload = response.json()
            results.append({"query": query, "http_status": response.status_code,
                            "elapsed_seconds": round(time.monotonic() - start, 2), "response": payload})
            print(json.dumps({"query": query, "status": response.status_code,
                              "candidates": len(payload.get("results", []))}))
            time.sleep(1.2)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "audit", "search"))
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    if args.action == "backup":
        backup()
    else:
        result = audit() if args.action == "audit" else search(args.url)
        destination = ROOT / "test-results" / f"search-repair-{args.action}.json"
        destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"Evidence saved: {destination}")
