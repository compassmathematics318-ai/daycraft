"""Read-only verification of the compiled project redesign on localhost."""
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
    projects = json.loads(get("/api/projects"))
    assert projects == state["projects"]
    html = get("/")
    assert html == (ROOT / "frontend" / "dist" / "index.html").read_bytes()
    assets = {}
    for path in re.findall(r'"(/assets/[^\"]+)"', html.decode("utf-8")):
        content = get(path)
        assert content == (ROOT / "frontend" / "dist" / path.lstrip("/")).read_bytes()
        assets[path] = hashlib.sha256(content).hexdigest()
    assert len(assets) >= 2
    week = json.loads(get("/api/calendar?week_start=2026-11-11"))
    assert (week["week_start"], week["week_end"]) == ("2026-11-08", "2026-11-14")
    database = ROOT / "data" / "schedule_builder.db"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert revision == "0003_personal_projects"
        assert len(projects) == db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    report = {"url": URL, "healthy": True, "migration": revision,
              "project_api_and_state_match": True, "project_count": len(projects),
              "compiled_assets_match": True, "assets": assets,
              "calendar_week_unchanged": True}
    (ROOT / "test-results" / "projects-live-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
