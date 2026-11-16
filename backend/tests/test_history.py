"""Archive lifecycle, independent actual-work evidence, and additive migration."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sqlite3

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, select

from backend.app import history, schemas, task_library
from backend.app.database import CompletedWork, Configuration, Entity, LogicalSession, Schedule, TaskDefinition, TaskWeek, build_database
from backend.app.main import create_app
from backend.app.migrate import migrate
from backend.tests.test_work_confirmation import confirm, seed, week


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "history.sqlite")) as value:
        yield value


def save(client, plan, new_version=False):
    response = client.post("/api/schedule-archives", json={"schedule_id": plan["id"], "new_version": new_version})
    assert response.status_code == 200, response.text
    return response.json()


def completed(client, **filters):
    response = client.get("/api/completed-tasks", params=filters)
    assert response.status_code == 200, response.text
    return response.json()


def archived(client, key):
    response = client.get(f"/api/schedule-archives/{key}")
    assert response.status_code == 200, response.text
    return response.json()


def test_save_is_additive_deduplicated_and_never_completes_elapsed_work(client):
    _, _, plan = seed(client)
    before = client.get("/api/state").json()
    with client.app.state.session_factory() as db:
        planner_before = task_library.planning_inputs(db, plan["date"], before["settings"], plan["blocks"])
    first, second = save(client, plan), save(client, plan)
    assert first["created"] and not second["created"] and first["id"] == second["id"]
    assert first["mode"] == "deep" and first["workload_level"] is None
    assert first["completed_minutes"] == 0 and first["total_minutes"] == 60
    assert completed(client)["items"] == []
    after = client.get("/api/state").json()
    for field in ("settings", "activities", "projects", "task_definitions", "tasks", "classes", "locations"):
        assert before[field] == after[field]
    assert before["schedules"][0]["blocks"] == after["schedules"][0]["blocks"]
    assert after["schedules"][0]["archive_id"] == first["id"]
    assert week(client)["summary"]["verified_completed_minutes"] == 0
    save(client, plan, True)
    assert client.delete(f"/api/schedule-archives/{first['id']}").status_code == 204
    with client.app.state.session_factory() as db:
        assert task_library.planning_inputs(db, plan["date"], before["settings"], plan["blocks"]) == planner_before


def test_concurrent_repeat_saves_share_one_revision(client):
    _, _, plan = seed(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post("/api/schedule-archives", json={"schedule_id": plan["id"]}), range(4)))
    assert [response.status_code for response in responses] == [200] * 4
    assert len({response.json()["id"] for response in responses}) == 1
    assert sum(response.json()["created"] for response in responses) == 1


def test_confirm_reverse_reconfirm_and_archived_versions(client):
    _, _, plan = seed(client)
    original = save(client, plan)
    assert confirm(client, plan).status_code == 200
    first = completed(client)
    assert first["total"] == 1 and first["summary"]["completed_minutes"] == 30
    assert not first["items"][0]["logical_session_complete"]
    assert first["items"][0]["archive_id"] == original["id"]
    attached = archived(client, original["id"])
    assert attached["completed_minutes"] == 30
    assert confirm(client, plan).status_code == 200
    assert completed(client)["items"][0]["confirmed_at"] == first["items"][0]["confirmed_at"]
    version = save(client, plan, True)
    assert version["id"] != original["id"] and version["attached"]
    assert original["version_number"] == 1 and version["version_number"] == 2
    frozen = archived(client, original["id"])
    assert not frozen["attached"]
    assert confirm(client, plan, 1).status_code == 200
    assert completed(client)["summary"]["logical_sessions_completed"] == 1
    assert all(item["logical_session_complete"] for item in completed(client)["items"])
    assert archived(client, original["id"]) == frozen
    assert archived(client, version["id"])["completed_minutes"] == 60
    assert confirm(client, plan, completed=False).status_code == 200
    result = completed(client)
    assert result["total"] == 1 and result["summary"]["completed_minutes"] == 30
    assert result["summary"]["logical_sessions_completed"] == 0
    assert archived(client, version["id"])["completed_minutes"] == 30
    assert archived(client, original["id"]) == frozen
    assert confirm(client, plan).status_code == 200
    assert completed(client)["total"] == 2
    with client.app.state.session_factory() as db:
        assert len(list(db.scalars(select(CompletedWork)))) == 2


def reverse(client, item):
    response = client.post(f"/api/completed-tasks/{item['id']}/reverse")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("assignment_source", ["manual", "recurring"])
def test_history_reversal_exact_chunk_idempotency_archives_and_planning(client, assignment_source):
    definition, assignment, plan = seed(client, status="in_progress")
    other = client.post("/api/task-weeks", json={"task_definition_id": definition["id"], "week_start": "2020-11-15"})
    assert other.status_code == 201
    assert confirm(client, plan).status_code == 200
    frozen = save(client, plan)
    attached = save(client, plan, True)
    assert confirm(client, plan, 1).status_code == 200
    item = next(item for item in completed(client)["items"] if item["source_block_id"] == plan["blocks"][0]["id"])
    settings = client.get("/api/state").json()["settings"]
    with client.app.state.session_factory() as db:
        source = db.get(TaskWeek, assignment["id"])
        source.payload = {**source.payload, "source": assignment_source}
        other_plan = {"id": "unrelated-next-week", "date": "2020-11-15", "status": "feasible", "blocks": [], "explanations": []}
        db.add(Schedule(id=other_plan["id"], date=other_plan["date"], payload=other_plan))
        db.commit()
    first = reverse(client, item)
    assert first["changed"] and first["reversed"]
    second = reverse(client, item)
    assert not second["changed"] and second["reopened_at"] == first["reopened_at"]
    assert completed(client)["total"] == 1
    assert week(client)["summary"]["verified_completed_minutes"] == 30
    assert week(client)["summary"]["completed_sessions"] == 0
    assert week(client, "2020-11-15")["summary"]["verified_completed_minutes"] == 0
    with client.app.state.session_factory() as db:
        saved = db.get(Schedule, plan["id"])
        assert db.get(Schedule, other_plan["id"]).payload == other_plan
        assert saved.payload["status"] == "stale" and saved.payload["tasks_dirty"]
        assert saved.payload["blocks"][0] == plan["blocks"][0]
        assert saved.payload["blocks"][1]["status"] == "completed"
        assert db.get(TaskDefinition, definition["id"]).payload["status"] == "active"
        logical = db.get(LogicalSession, plan["blocks"][0]["logical_session_id"])
        assert logical.completed_minutes == 30
        prepared = task_library.planning_inputs(db, plan["date"], settings, saved.payload["blocks"])
        assert next(session for session in prepared[2] if session["id"] == logical.id)["completed_minutes"] == 30
        assert next(chunk for chunk in prepared[3]["chunks"] if chunk["id"] == item["source_block_id"])["status"] == "in_progress"
        history.backfill_completions(db, settings)
        database_path = db.get_bind().url.database
        db.commit()
    assert completed(client)["total"] == 1
    assert archived(client, frozen["id"])["payload"] == frozen["payload"]
    assert archived(client, attached["id"])["completed_minutes"] == 30
    with TestClient(create_app(database_path)) as restarted:
        assert completed(restarted)["total"] == 1
        assert week(restarted)["summary"]["verified_completed_minutes"] == 30
        assert archived(restarted, frozen["id"])["payload"] == frozen["payload"]


def test_history_reversal_manual_and_undated_credit_do_not_return(client):
    _, assignment, plan = seed(client, status="completed", baseline=10)
    with client.app.state.session_factory() as db:
        history.backfill_completions(db, schemas.Settings().model_dump(mode="json"))
        db.commit()
    items = completed(client)["undated_items"]
    assert len(items) == 3
    for item in items:
        reverse(client, item)
    assert completed(client)["undated_items"] == []
    assert week(client)["summary"]["verified_completed_minutes"] == 0
    logged = client.post("/api/task-sessions", json={"assignment_id": assignment["id"], "completed_minutes": 20})
    assert logged.status_code == 201, logged.text
    item = completed(client)["items"][0]
    assert item["source_type"] == "manual_session"
    reverse(client, item)
    with client.app.state.session_factory() as db:
        history.backfill_completions(db, schemas.Settings().model_dump(mode="json"))
        db.commit()
    assert completed(client)["items"] == [] and completed(client)["undated_items"] == []
    assert week(client)["summary"]["verified_completed_minutes"] == 0
    assert client.post("/api/completed-tasks/missing/reverse").status_code == 404


@pytest.mark.parametrize("remove_source", [False, True])
def test_history_finite_reversal_restores_exact_delta_even_without_plan(client, remove_source):
    response = client.post("/api/tasks", json={"title": "Finite evidence", "duration_minutes": 60, "remaining_minutes": 10})
    assert response.status_code == 201
    task = response.json()
    plan = {"id": "finite-plan", "date": "2020-11-08", "blocks": [{"id": "finite-block", "kind": "task", "task_id": task["id"], "title": task["title"], "start": "2020-11-08T08:00:00-05:00", "end": "2020-11-08T08:30:00-05:00", "status": "todo"}]}
    with client.app.state.session_factory() as db:
        db.add(Schedule(id=plan["id"], date=plan["date"], payload=plan))
        db.commit()
    assert confirm(client, plan).status_code == 200
    item = completed(client)["items"][0]
    if remove_source:
        with client.app.state.session_factory() as db:
            db.delete(db.get(Schedule, plan["id"]))
            db.commit()
    reverse(client, item)
    reverse(client, item)
    with client.app.state.session_factory() as db:
        assert db.get(Entity, ("tasks", task["id"])).payload["remaining_minutes"] == 10
        assert db.get(TaskDefinition, task["id"]).payload["status"] == "active"


def test_archive_delete_keeps_active_completed_and_all_credit(client):
    _, _, plan = seed(client)
    archive = save(client, plan)
    assert confirm(client, plan).status_code == 200
    before = completed(client)["items"][0]
    assert client.delete(f"/api/schedule-archives/{archive['id']}").status_code == 204
    after = completed(client)["items"][0]
    assert {key: value for key, value in after.items() if key != "archive_id"} == {key: value for key, value in before.items() if key != "archive_id"}
    assert after["archive_id"] is None
    assert client.get("/api/schedules").json()[0]["archive_id"] is None
    assert week(client)["summary"]["verified_completed_minutes"] == 30
    assert client.get(f"/api/schedule-archives/{archive['id']}").status_code == 404
    replacement = save(client, plan)
    assert replacement["id"] != archive["id"] and replacement["version_number"] == 2


def test_definition_changes_and_deletion_do_not_rewrite_snapshots(client):
    definition, _, plan = seed(client)
    assert confirm(client, plan).status_code == 200
    archive = save(client, plan)
    before_archive, before_completed = deepcopy(archive["payload"]), deepcopy(completed(client)["items"])
    response = client.put(f"/api/task-definitions/{definition['id']}", json={**{key: definition[key] for key in ("title", "session_minutes", "allow_splitting", "min_chunk_minutes")}, "title": "Renamed later", "description": "New meaning"})
    assert response.status_code == 200, response.text
    assert archived(client, archive["id"])["payload"] == before_archive
    assert client.delete(f"/api/task-definitions/{definition['id']}?delete_assignments=true").status_code == 204
    assert archived(client, archive["id"])["payload"] == before_archive
    assert completed(client)["items"] == before_completed
    assert week(client)["history_assignments"][0]["verified_completed_minutes"] == 30


def test_background_pending_withdrawal_cannot_erase_archive_on_other_confirmation(client):
    _, _, plan = seed(client)
    future = client.post("/api/task-definitions", json={"title": "Future remembered", "session_minutes": 30}).json()
    with client.app.state.session_factory() as db:
        row = db.get(Schedule, plan["id"])
        row.payload = {**row.payload, "blocks": [*row.payload["blocks"], {"id": "future-remembered", "task_id": future["id"], "kind": "task", "title": future["title"], "start": "2090-11-12T10:00:00-05:00", "end": "2090-11-12T10:30:00-05:00", "status": "todo"}]}
        db.commit()
    archive = save(client, plan)
    assert client.delete(f"/api/task-definitions/{future['id']}?delete_assignments=true").status_code == 204
    assert "future-remembered" not in {item["id"] for item in client.get("/api/schedules").json()[0]["blocks"]}
    assert confirm(client, plan).status_code == 200
    assert "future-remembered" in {item["id"] for item in archived(client, archive["id"])["payload"]["blocks"]}


def test_explicit_manual_edit_syncs_only_changed_fields_and_freezes_definition_metadata(client):
    _, _, plan = seed(client)
    archive = save(client, plan)
    with client.app.state.session_factory() as db:
        row = db.get(Schedule, plan["id"])
        before = deepcopy(row.payload)
        after = deepcopy(before)
        after["blocks"][0].update(title="Explicit new title", description="User edit", locked=True)
        row.payload = after
        history.sync_schedule(db, row, schemas.Settings().model_dump(mode="json"), before)
        db.commit()
    value = archived(client, archive["id"])
    assert value["payload"]["blocks"][0]["title"] == "Explicit new title"
    assert value["payload"]["blocks"][0]["description"] == "User edit"
    assert value["payload"]["blocks"][0]["locked"]
    assert value["payload"]["blocks"][0]["task_snapshot"]["title"] == "QA persisted reading"


def test_preference_changes_do_not_rewrite_archive_and_future_confirmation_is_atomic(client):
    _, _, plan = seed(client, date="2090-11-12")
    archive = save(client, plan)
    before = archived(client, archive["id"])
    assert client.put("/api/day-preferences/2090-11-12", json={"workload_level": "very_low"}).status_code == 200
    assert archived(client, archive["id"]) == before
    assert confirm(client, plan).status_code == 409
    assert archived(client, archive["id"]) == before and completed(client)["total"] == 0


def test_bulk_confirmation_and_manual_actual_work(client):
    _, assignment, plan = seed(client)
    archive = save(client, plan)
    logical_id = plan["blocks"][0]["logical_session_id"]
    assert client.put(f"/api/task-sessions/{logical_id}", json={"status": "completed"}).status_code == 200
    assert archived(client, archive["id"])["completed_minutes"] == 60
    assert completed(client)["summary"]["completed_minutes"] == 60
    assert client.put(f"/api/task-sessions/{logical_id}", json={"status": "todo"}).status_code == 200
    assert archived(client, archive["id"])["completed_minutes"] == 0 and completed(client)["total"] == 0
    logged = client.post("/api/task-sessions", json={"assignment_id": assignment["id"], "completed_minutes": 25})
    assert logged.status_code == 201, logged.text
    result = completed(client)
    assert result["total"] == 1 and result["summary"]["completed_minutes"] == 25
    item = result["items"][0]
    assert item["source_type"] == "manual_session" and item["scheduled_start"] is None and item["confirmed_at"]
    assert item["week_start"] == "2020-11-08" and result["legacy_undated_count"] == 0
    assert client.put(f"/api/task-sessions/{logged.json()['id']}", json={"status": "todo"}).status_code == 200
    assert completed(client)["total"] == 0


def test_existing_undated_manual_baseline_is_not_dated_by_idempotent_confirmation(client):
    definition = client.post("/api/task-definitions", json={"title": "Undated manual", "session_minutes": 60}).json()
    assignment = client.post("/api/task-weeks", json={"task_definition_id": definition["id"], "week_start": "2020-11-08"}).json()
    with client.app.state.session_factory() as db:
        db.add(LogicalSession(id="undated-manual", assignment_id=assignment["id"], index=0, target_minutes=60, completed_minutes=60, baseline_completed_minutes=60, status="completed"))
        db.commit()
    assert client.put("/api/task-sessions/undated-manual", json={"status": "completed"}).status_code == 200
    assert completed(client)["total"] == 0
    assert completed(client)["summary"]["undated_completed_minutes"] == 60
    assert client.put("/api/task-sessions/undated-manual", json={"status": "todo"}).status_code == 200
    assert client.put("/api/task-sessions/undated-manual", json={"completed_minutes": 20}).status_code == 200
    result = completed(client)
    assert result["summary"]["completed_minutes"] == 20 and result["legacy_undated_count"] == 0


def test_new_progress_dates_only_delta_above_existing_undated_manual_baseline(client):
    definition = client.post("/api/task-definitions", json={"title": "Partly undated", "session_minutes": 60}).json()
    assignment = client.post("/api/task-weeks", json={"task_definition_id": definition["id"], "week_start": "2020-11-08"}).json()
    with client.app.state.session_factory() as db:
        db.add(LogicalSession(id="partly-undated", assignment_id=assignment["id"], index=0, target_minutes=60, completed_minutes=10, baseline_completed_minutes=10, status="in_progress"))
        db.commit()
    assert client.put("/api/task-sessions/partly-undated", json={"completed_minutes": 25}).status_code == 200
    result = completed(client)
    assert result["summary"]["completed_minutes"] == 15 and result["summary"]["undated_completed_minutes"] == 10
    assert client.put("/api/task-sessions/partly-undated", json={"completed_minutes": 5}).status_code == 200
    result = completed(client)
    assert result["total"] == 0 and result["summary"]["undated_completed_minutes"] == 5


def test_general_planner_edit_completion_and_room_changes_sync_archive(client):
    _, _, plan = seed(client)
    archive = save(client, plan)
    blocks = deepcopy(plan["blocks"])
    blocks[0].update(status="completed", title="Explicit changed title", description="Explicit changed description", room="411")
    response = client.put(f"/api/schedules/{plan['id']}", json={"blocks": blocks})
    assert response.status_code == 200, response.text
    saved = archived(client, archive["id"])["payload"]["blocks"][0]
    assert saved["status"] == "completed" and saved["title"] == "Explicit changed title"
    assert saved["description"] == "Explicit changed description" and saved["room"] == "411"
    assert completed(client)["summary"]["completed_minutes"] == 30


def test_location_project_and_related_activity_are_frozen_independently(client):
    definition, assignment, plan = seed(client)
    place = client.post("/api/locations", json={"name": "Original library", "lat": 43.47, "lon": -80.54, "room": "200"}).json()
    project = client.post("/api/projects", json={"name": "Original project", "description": "Original goal"}).json()
    activity_response = client.post("/api/activities", json={"title": "Original course", "category": "class", "subtype": "Lecture", "description": "Course context"})
    assert activity_response.status_code == 201, activity_response.text
    activity = activity_response.json()
    with client.app.state.session_factory() as db:
        task = db.get(TaskDefinition, definition["id"])
        task.project_id, task.related_activity_id = project["id"], activity["id"]
        task.payload = {**task.payload, "project_id": project["id"], "related_activity_id": activity["id"], "description": "Task meaning"}
        row = db.get(Schedule, plan["id"])
        row.payload = {**row.payload, "blocks": [{**block, "location_id": place["id"], "location_mode": "required", "room": "200"} for block in row.payload["blocks"]]}
        week_row = db.get(TaskWeek, assignment["id"])
        week_row.payload = {**week_row.payload, "source": "recurring"}
        db.commit()
    archive = save(client, plan)
    assert confirm(client, plan).status_code == 200
    item = completed(client)["items"][0]
    assert item["project_title"] == "Original project" and item["related_activity_title"] == "Original course"
    assert item["description"] == "Task meaning" and item["assignment_source"] == "recurring"
    assert "Original library" in item["location_label"] and "200" in item["location_label"]
    with client.app.state.session_factory() as db:
        db.get(Entity, ("locations", place["id"])).payload = {**place, "name": "Renamed place"}
        db.get(TaskDefinition, definition["id"]).payload = {**definition, "title": "New task name", "description": "New meaning"}
        db.commit()
    assert confirm(client, plan, 1).status_code == 200
    assert all("Original library" in block["location_label"] for block in archived(client, archive["id"])["payload"]["blocks"])
    assert all(value["project_title"] == "Original project" for value in completed(client)["items"])


def test_undated_historical_credit_remains_separate_without_inventing_dates(client):
    _, _, plan = seed(client, status="completed", baseline=10)
    with client.app.state.session_factory() as db:
        history.backfill_completions(db, schemas.Settings().model_dump(mode="json"))
        db.commit()
    result = completed(client)
    assert result["total"] == 0 and result["legacy_undated_count"] == 3
    assert result["summary"]["undated_completed_minutes"] == 70
    assert all(item["confirmed_at"] is None and item["completion_date"] is None for item in result["undated_items"])
    assert completed(client, date_from="2020-01-01")["undated_items"] == []
    assert confirm(client, plan).status_code == 200
    assert completed(client)["total"] == 0  # repeated historical completed state is not new evidence


def test_undated_snapshots_freeze_names_and_survive_source_ledger_deletion(client):
    definition, assignment, plan = seed(client, status="completed", baseline=10)
    with client.app.state.session_factory() as db:
        history.backfill_completions(db, schemas.Settings().model_dump(mode="json"))
        db.commit()
    original = completed(client)["undated_items"]
    with client.app.state.session_factory() as db:
        row = db.get(TaskDefinition, definition["id"])
        row.payload = {**row.payload, "title": "Renamed history", "description": "Replacement description"}
        history.sync_undated(db, schemas.Settings().model_dump(mode="json"))
        db.commit()
    assert completed(client)["undated_items"] == original
    with client.app.state.session_factory() as db:
        db.delete(db.get(Schedule, plan["id"]))
        db.flush()
        db.delete(db.get(LogicalSession, plan["blocks"][0]["logical_session_id"]))
        db.flush()
        db.delete(db.get(TaskWeek, assignment["id"]))
        db.flush()
        db.delete(db.get(TaskDefinition, definition["id"]))
        db.commit()
    assert completed(client)["undated_items"] == original


def test_paginated_summary_uses_all_filtered_rows_and_actual_completion_date(client):
    _, _, plan = seed(client)
    save(client, plan)
    assert confirm(client, plan).status_code == 200 and confirm(client, plan, 1).status_code == 200
    result = completed(client, limit=1)
    assert len(result["items"]) == 1 and result["total"] == 2 and result["summary"]["completed_minutes"] == 60
    assert result["items"][0]["scheduled_date"] == "2020-11-08"
    assert result["items"][0]["completion_date"] != "2020-11-08"
    assert completed(client, date_from="2020-11-08", date_to="2020-11-08")["total"] == 0
    assert completed(client, q="QA persisted reading")["total"] == 2
    assert completed(client, q="no such title")["total"] == 0
    unrelated = client.post("/api/task-definitions", json={"title": "Unrelated search phrase"})
    assert unrelated.status_code == 201
    assert client.get("/api/schedule-archives", params={"q": "Unrelated search phrase"}).json()["total"] == 0


def test_completion_order_compares_instants_across_offset_and_dst_stamps(client):
    _, _, plan = seed(client)
    assert confirm(client, plan).status_code == 200 and confirm(client, plan, 1).status_code == 200
    with client.app.state.session_factory() as db:
        rows = list(db.scalars(select(CompletedWork).order_by(CompletedWork.source_block_id)))
        # 01:30 EST is later than 01:50 EDT although its local wall time is less.
        rows[0].confirmed_at = "2026-11-01T01:30:00-05:00"
        rows[1].confirmed_at = "2026-11-01T01:50:00-04:00"
        later_id = rows[0].id
        db.commit()
    assert completed(client)["items"][0]["id"] == later_id


@pytest.mark.parametrize("body", [{"schedule_id": "missing"}, {"schedule_id": "anything", "unknown": 1}, {"schedule_id": "anything", "new_version": "true"}])
def test_missing_and_invalid_save_requests(client, body):
    assert client.post("/api/schedule-archives", json=body).status_code in {404, 422}


def test_generation_freezes_previous_archive_and_requires_explicit_new_save(client):
    settings = client.get("/api/state").json()["settings"]
    settings.update(meals=[], work_start="08:00", work_end="09:00")
    assert client.put("/api/settings", json=settings).status_code == 200
    generated = client.post("/api/schedules/generate", json={"date": "2090-11-12", "mode": "deadline"})
    assert generated.status_code == 200, generated.text
    plan = generated.json()
    first = save(client, plan)
    second = client.post("/api/schedules/generate", json={"date": plan["date"]})
    assert second.status_code == 200, second.text
    assert second.json()["id"] == plan["id"] and second.json()["archive_id"] is None
    assert second.json()["schedule_revision_id"] != plan["schedule_revision_id"]
    frozen = archived(client, first["id"])
    assert not frozen["attached"] and frozen["payload"] == first["payload"]
    second_archive = save(client, plan)
    assert second_archive["id"] != first["id"] and second_archive["version_number"] == 2


def test_startup_backfills_explicit_evidence_and_preserves_every_original_row(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    path = tmp_path / "upgrade.sqlite"
    engine, factory = build_database(path)
    config = Config()
    config.set_main_option("script_location", str(__import__("pathlib").Path(__file__).resolve().parents[1] / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0007_daily_session_limits")
    old = {"id": "old", "date": "2020-11-08", "blocks": [{"id": "old-block", "kind": "task", "task_id": "gone", "title": "Original title", "start": "2020-11-08T08:00:00-05:00", "end": "2020-11-08T08:30:00-05:00", "status": "completed", "completion_verified": True, "completion_confirmed_at": "2020-11-09T00:30:00+00:00"}]}
    with factory() as db:
        db.add(Schedule(id="old", date=old["date"], payload=old))
        db.add(Configuration(id="settings", payload=schemas.Settings().model_dump(mode="json")))
        db.add(Entity(collection="locations", id="original-place", payload={"name": "Untouched location"}))
        db.commit()
    with sqlite3.connect(path) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'")]
        before = {table: connection.execute(f'SELECT * FROM "{table}"').fetchall() for table in tables}
    migrate(engine)
    engine.dispose()
    with TestClient(create_app(path)) as restarted:
        response = completed(restarted)
        assert response["total"] == 1 and response["items"][0]["title"] == "Original title"
        assert response["items"][0]["completion_date"] == "2020-11-08"  # UTC stamp normalized to Toronto
        assert response["items"][0]["task_snapshot"] is None
    with sqlite3.connect(path) as connection:
        assert {table: connection.execute(f'SELECT * FROM "{table}"').fetchall() for table in tables} == before
        assert json.loads(connection.execute("SELECT payload FROM schedules WHERE id='old'").fetchone()[0]) == old
    with TestClient(create_app(path)) as restarted:
        assert completed(restarted)["total"] == 1


def test_history_survives_physical_source_removal_without_foreign_key_cascades(client):
    _, _, plan = seed(client)
    assert confirm(client, plan).status_code == 200
    archive = save(client, plan)
    with client.app.state.session_factory() as db:
        db.delete(db.get(Schedule, plan["id"]))
        db.commit()
    assert archived(client, archive["id"])["payload"]["blocks"][0]["title"] == "QA persisted reading"
    assert completed(client)["total"] == 1


def test_history_failure_rolls_back_confirmation_and_credit_atomically(client, monkeypatch):
    _, _, plan = seed(client)
    archive = save(client, plan)
    def broken(*args, **kwargs):
        raise RuntimeError("simulated persistence error")
    monkeypatch.setattr(history, "sync_schedule", broken)
    with pytest.raises(RuntimeError, match="simulated persistence error"):
        confirm(client, plan)
    assert week(client)["summary"]["verified_completed_minutes"] == 0
    assert archived(client, archive["id"])["completed_minutes"] == 0
    assert completed(client)["total"] == 0


def database_rows(client):
    """Compare durable rows, including records omitted from API projections."""
    with sqlite3.connect(client.app.state.engine.url.database) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {table: sorted(connection.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr) for table in tables}


def test_save_uses_latest_persisted_edits_and_stale_history_without_solving(client, monkeypatch):
    from backend.app import scheduler, weekly_scheduler

    _, _, plan = seed(client)
    place = client.post("/api/locations", json={"name": "Saved audit library", "lat": 43.47, "lon": -80.54}).json()
    with client.app.state.session_factory() as db:
        row = db.get(Schedule, plan["id"])
        row.payload = {**row.payload, "workload_level": "high", "generation_metadata": {"audit": "persisted"}}
        db.commit()
    blocks = deepcopy(plan["blocks"])
    blocks[0].update(title="Latest saved title", room="411", locked=True, location_id=place["id"], location_mode="required", location_override=True)
    response = client.put(f"/api/schedules/{plan['id']}", json={"blocks": blocks})
    assert response.status_code == 200, response.text
    assert confirm(client, plan).status_code == 200
    assert client.put(f"/api/day-preferences/{plan['date']}", json={"workload_level": "very_low"}).status_code == 200
    with client.app.state.session_factory() as db:
        persisted = deepcopy(db.get(Schedule, plan["id"]).payload)
    assert persisted["needs_regeneration"] and persisted["preferences_dirty"]

    def unexpected_solve(*args, **kwargs):
        pytest.fail("Saving historical work must not invoke schedule preparation or optimization")

    monkeypatch.setattr(scheduler, "generate_schedule", unexpected_solve)
    monkeypatch.setattr(weekly_scheduler, "prepare_weekly_tasks", unexpected_solve)
    first, repeated = save(client, plan), save(client, plan)
    assert first["id"] == repeated["id"] and not repeated["created"]
    assert first["payload"] == repeated["payload"]
    assert first["workload_level"] == "high" and first["mode"] == "deep"
    assert first["payload"]["generation_metadata"] == {"audit": "persisted"}
    assert first["payload"]["needs_regeneration"] and first["payload"]["preferences_dirty"]
    assert first["completed_minutes"] == 30
    for before, saved in zip(persisted["blocks"], first["payload"]["blocks"]):
        assert all(saved[key] == value for key, value in before.items())
    latest = first["payload"]["blocks"][0]
    assert latest["locked"] and latest["title"] == "Latest saved title" and latest["room"] == "411"
    assert latest["location_snapshot"]["id"] == place["id"]
    assert "Saved audit library" in latest["location_label"]
    assert completed(client)["summary"]["completed_minutes"] == 30


@pytest.mark.parametrize("delete_attached", [False, True])
def test_delete_changes_exactly_selected_archive_row_and_repeat_is_harmless(client, delete_attached):
    _, _, plan = seed(client)
    frozen = save(client, plan)
    assert confirm(client, plan).status_code == 200
    attached = save(client, plan, True)
    assert confirm(client, plan, 1).status_code == 200
    _, _, other = seed(client, date="2020-11-15")
    save(client, other)
    before = database_rows(client)
    chosen = attached if delete_attached else frozen
    expected = deepcopy(before)
    expected["schedule_archives"] = [row for row in expected["schedule_archives"] if row[0] != chosen["id"]]
    assert len(expected["schedule_archives"]) == len(before["schedule_archives"]) - 1
    assert client.delete(f"/api/schedule-archives/{chosen['id']}").status_code == 204
    assert database_rows(client) == expected
    # Missing IDs return 404; neither retries nor historical lookup mutate data.
    assert client.delete(f"/api/schedule-archives/{chosen['id']}").status_code == 404
    assert client.get(f"/api/schedule-archives/{chosen['id']}").status_code == 404
    assert database_rows(client) == expected
    remaining = frozen if delete_attached else attached
    assert archived(client, remaining["id"])["attached"] is not delete_attached
    assert completed(client)["summary"]["completed_minutes"] == 60


def test_failed_new_version_rolls_back_detachment_counter_and_all_rows(client, monkeypatch):
    _, _, plan = seed(client)
    original = save(client, plan)
    before = database_rows(client)

    def broken(*args, **kwargs):
        raise RuntimeError("simulated snapshot failure")

    with monkeypatch.context() as patch:
        patch.setattr(history, "snapshot", broken)
        with pytest.raises(RuntimeError, match="simulated snapshot failure"):
            save(client, plan, True)
    assert database_rows(client) == before
    assert archived(client, original["id"])["attached"]
    assert save(client, plan, True)["version_number"] == 2


def test_failed_delete_rolls_back_snapshot_and_preserves_all_other_rows(client):
    _, _, plan = seed(client)
    archive = save(client, plan)
    assert confirm(client, plan).status_code == 200
    before = database_rows(client)

    def broken(db, flush_context):
        if any(row.id == archive["id"] for row in db.deleted):
            raise RuntimeError("simulated delete commit failure")

    session_class = client.app.state.session_factory.class_
    event.listen(session_class, "after_flush", broken)
    try:
        with pytest.raises(RuntimeError, match="simulated delete commit failure"):
            client.delete(f"/api/schedule-archives/{archive['id']}")
    finally:
        event.remove(session_class, "after_flush", broken)
    assert database_rows(client) == before
    assert archived(client, archive["id"])["completed_minutes"] == 30
