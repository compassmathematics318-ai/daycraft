"""Read-only verification of the weekly-task production deployment."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8765"


def get(path):
    with urllib.request.urlopen(URL + path, timeout=5) as response:
        assert response.status == 200
        return response.read()


def main():
    assert json.loads(get("/health"))["status"] == "ok"
    state = json.loads(get("/api/state"))
    definitions = json.loads(get("/api/task-definitions"))
    assert definitions == state["task_definitions"]
    week = json.loads(get("/api/task-week?week_start=2026-11-11"))
    assert (week["week_start"], week["week_end"]) == ("2026-11-08", "2026-11-14")
    boundary = json.loads(get("/api/task-week?week_start=2027-01-01"))
    assert (boundary["week_start"], boundary["week_end"]) == ("2026-12-27", "2027-01-02")
    calendar = json.loads(get("/api/calendar?week_start=2026-11-11"))
    assert calendar["week_start"] == week["week_start"]
    html = get("/")
    assert html == (ROOT / "frontend" / "dist" / "index.html").read_bytes()
    assets = {}
    for path in re.findall(r'"(/assets/[^\"]+)"', html.decode("utf-8")):
        data = get(path)
        assert data == (ROOT / "frontend" / "dist" / path.lstrip("/")).read_bytes()
        assets[path] = hashlib.sha256(data).hexdigest()
    assert len(assets) >= 2
    database = ROOT / "data" / "schedule_builder.db"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert revision == "0004_weekly_tasks"
    report = {"url": URL, "healthy": True, "migration": revision,
              "definition_count": len(definitions), "definition_state_matches": True,
              "sunday_week_and_year_boundary": True, "calendar_compatibility": True,
              "production_assets_match": True, "assets": assets}
    (ROOT / "test-results" / "tasks-live-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
