"""Exercise lifecycle and relationship adapters on a copy of personal data.

This does not execute CP-SAT and does not claim optimizer verification.
"""
import json
import os
from datetime import datetime
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SCHEDULE_BUILDER_OFFLINE"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from backend.app import calendar, task_library  # noqa: E402
from backend.app.calendar_scheduler import fixed_blocks_for_day  # noqa: E402
from backend.app.main import create_app  # noqa: E402


def rows(db):
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {table: sorted(db.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr) for table in tables}


def request(client, method, path, data=None):
    response = client.request(method, "/api" + path, json=data)
    assert response.is_success, response.text
    return response.json() if response.status_code != 204 else None


def main():
    output = ROOT / "test-results/task-lifecycle"
    output.mkdir(exist_ok=True)
    source = ROOT / "data/schedule_builder.db"
    target = output / f"integrated-{datetime.now():%Y%m%d-%H%M%S}.sqlite"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db, sqlite3.connect(target) as copy:
        before = rows(db)
        db.backup(copy)
    with TestClient(create_app(target)) as client:
        state = request(client, "GET", "/state")
        original_links = [(item["id"], item["project_id"], item["related_activity_id"], item["course"]) for item in state["task_definitions"]]
        project = state["projects"][0]
        place = state["locations"][0]
        meeting = request(client, "POST", "/activities", {
            "title": "Isolated relationship integration meeting", "category": "commitment", "subtype": "Groupwork",
            "location_id": place["id"], "location_mode": "required", "room": "Integration",
            "related_entity": {"kind": "project", "id": project["id"]}})
        request(client, "POST", "/occurrences", {"activity_id": meeting["id"],
                "start": "2032-11-15T10:00:00-05:00", "end": "2032-11-15T11:00:00-05:00"})
        task = request(client, "POST", "/task-definitions", {
            "title": "Isolated relationship integration task", "project_id": project["id"],
            "related_activity_id": meeting["id"], "location_id": place["id"], "location_mode": "preferred"})
        assignment = request(client, "POST", "/task-weeks", {"task_definition_id": task["id"], "week_start": "2032-11-15"})
        with client.app.state.session_factory() as db:
            definitions, assignments, _, _ = task_library.planning_inputs(db, "2032-11-15", state["settings"], [])
            value = next(item for item in definitions if item["id"] == task["id"])
            assert value["project"]["name"] == project["name"]
            assert value["related_activity"]["id"] == meeting["id"]
            assert value["related_activity"]["related_entity_context"]["id"] == project["id"]
            assert len(value["related_activity"]["occurrences"]) == 1
            assert any(item["id"] == assignment["id"] for item in assignments)
            events = calendar.occurrences_between(db, "2032-11-15", "2032-11-15", state["settings"])
            activities = [calendar.enrich_related_context(db, item, events) for item in calendar.activities_list(db)]
            fixed = fixed_blocks_for_day("2032-11-15", state["settings"], activities, events)
            blocks = [item for item in fixed if item["activity_id"] == meeting["id"]]
            assert len(blocks) == 1 and blocks[0]["related_entity_context"]["id"] == project["id"]
            assert len(fixed) == len(events)
        request(client, "DELETE", f"/task-definitions/{task['id']}?delete_assignments=true")
        assert task["id"] not in json.dumps(request(client, "GET", "/location-overview?week_start=2032-11-14"))
        state_after = request(client, "GET", "/state")
        assert original_links == [(item["id"], item["project_id"], item["related_activity_id"], item["course"]) for item in state_after["task_definitions"]]
        assert any(item["id"] == place["id"] for item in state_after["locations"])
    with TestClient(create_app(target)) as restarted:
        state_after = request(restarted, "GET", "/state")
        assert not any(item["id"] == task["id"] for item in state_after["task_definitions"])
        saved_meeting = next(item for item in state_after["activities"] if item["id"] == meeting["id"])
        assert saved_meeting["related_entity"] == {"kind": "project", "id": project["id"]}
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
        assert before == rows(db), "Personal database changed during isolated verification"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    evidence = {"database_copy": str(target), "existing_definitions_preserved": len(original_links),
                "task_dual_links_reach_planning_adapter": True, "commitment_project_context_in_fixed_block": True,
                "no_extra_calendar_events": True, "delete_persists_after_factory_restart": True,
                "personal_data_unchanged": True, "cp_sat_executed": False}
    (output / "integration-summary.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
