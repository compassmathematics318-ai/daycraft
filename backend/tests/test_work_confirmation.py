"""Real API and ledger verification using isolated persisted plans, without a solver."""
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app import schemas, task_library, work_confirmation
from backend.app.database import Configuration, Entity, LogicalSession, Schedule, TaskChunk, TaskDefinition, TaskWeek
from backend.app.main import account_progress, create_app, generation_mode, validate_manual


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "confirmation.sqlite")) as value:
        yield value


def seed(client, *, date="2020-11-08", status="todo", locked=False, baseline=0):
    response = client.post("/api/task-definitions", json={"title": "QA persisted reading", "session_minutes": 60, "allow_splitting": True, "min_chunk_minutes": 20})
    assert response.status_code == 201, response.text
    definition = response.json()
    response = client.post("/api/task-weeks", json={"task_definition_id": definition["id"], "week_start": date, "min_sessions_per_week": 1})
    assert response.status_code == 201, response.text
    assignment = response.json()
    sid, schedule_id = f"session:{assignment['id']}", f"plan:{date}"
    blocks = [{"id": f"chunk:{assignment['id']}:{index}", "kind": "task", "title": definition["title"], "task_id": definition["id"], "task_definition_id": definition["id"], "task_assignment_id": assignment["id"], "logical_session_id": sid, "chunk_index": 0, "start": f"{date}T{8 + index:02}:00:00-05:00", "end": f"{date}T{8 + index:02}:30:00-05:00", "status": status, "locked": locked} for index in range(2)]
    payload = {"id": schedule_id, "date": date, "mode": "deep", "status": "feasible", "blocks": blocks, "unallocated": [], "conflicts": [], "explanations": [], "stats": {"preserved": 1}}
    with client.app.state.session_factory() as db:
        db.add(LogicalSession(id=sid, assignment_id=assignment["id"], index=0, target_minutes=60, completed_minutes=baseline, baseline_completed_minutes=baseline, status="todo"))
        db.add(Schedule(id=schedule_id, date=date, payload=payload))
        db.flush()
        for block in blocks:
            db.add(TaskChunk(id=block["id"], logical_session_id=sid, schedule_id=schedule_id, start=block["start"], end=block["end"], status=status, credited_minutes=30 if status == "completed" else 0))
        db.flush()
        task_library.reconcile_session_credit(db, sid)
        db.commit()
    return definition, assignment, payload


def confirm(client, plan, index=0, completed=True, **extra):
    return client.post(f"/api/schedules/{plan['id']}/blocks/{plan['blocks'][index]['id']}/completion", json={"completed": completed, **extra})


def week(client, date="2020-11-08"):
    return client.get(f"/api/task-week?week_start={date}").json()


@pytest.mark.parametrize("status", ["todo", "in_progress", "skipped"])
def test_confirm_split_chunk_idempotence_undo_and_original_status(client, status):
    definition, assignment, plan = seed(client, status=status, locked=True)
    before = deepcopy(plan)
    response = confirm(client, plan)
    assert response.status_code == 200, response.text
    saved = response.json()
    block = saved["blocks"][0]
    assert block["status"] == "completed"
    assert block["completion_previous_status"] == status
    assert block["completion_verified"] is True
    stamp = datetime.fromisoformat(block["completion_confirmed_at"])
    assert stamp.tzinfo is not None
    assert stamp >= datetime.now(ZoneInfo("UTC")) - timedelta(seconds=10)
    assert {key: value for key, value in block.items() if key not in work_confirmation.EVIDENCE_FIELDS and key != "status"} == {key: value for key, value in before["blocks"][0].items() if key != "status"}
    assert saved["blocks"][1] == before["blocks"][1]
    assert saved["mode"] == "deep" and saved["stats"] == before["stats"]
    progress = week(client)
    assert progress["summary"]["verified_completed_minutes"] == 30
    assert progress["summary"]["completed_sessions"] == 0
    assert confirm(client, plan).json()["blocks"][0]["completion_confirmed_at"] == block["completion_confirmed_at"]
    assert week(client)["summary"]["verified_completed_minutes"] == 30
    assert confirm(client, plan, 1).status_code == 200
    assert week(client)["summary"]["verified_completed_minutes"] == 60
    assert week(client)["summary"]["completed_sessions"] == 1
    assert client.get("/api/task-definitions").json()[0]["status"] == "active"
    restored = confirm(client, plan, completed=False)
    assert restored.status_code == 200, restored.text
    assert restored.json()["blocks"][0] == before["blocks"][0]
    assert week(client)["summary"]["verified_completed_minutes"] == 30
    assert confirm(client, plan, completed=False).status_code == 200
    with client.app.state.session_factory() as db:
        assert len(list(db.scalars(select(TaskChunk)))) == 2
        assert db.get(TaskDefinition, definition["id"]).payload["status"] == "active"
        assert not db.get(TaskWeek, assignment["id"]).payload.get("removed_from_week")


def test_manual_baseline_and_other_week_are_independent(client):
    _, assignment, plan = seed(client, baseline=20)
    other = client.post("/api/task-weeks", json={"task_definition_id": assignment["task_definition_id"], "week_start": "2020-11-15"})
    assert other.status_code == 201
    assert confirm(client, plan).status_code == 200
    assert week(client)["summary"]["verified_completed_minutes"] == 50
    assert week(client, "2020-11-15")["summary"]["verified_completed_minutes"] == 0
    assert confirm(client, plan, completed=False).status_code == 200
    assert week(client)["summary"]["verified_completed_minutes"] == 20


def test_future_rejection_and_general_edit_guard_without_solver(client):
    _, _, plan = seed(client, date="2090-11-12")
    response = confirm(client, plan)
    assert response.status_code == 409 and "end time" in response.text
    edited = deepcopy(plan["blocks"])
    edited[0]["status"] = "completed"
    response = client.put(f"/api/schedules/{plan['id']}", json={"blocks": edited})
    assert response.status_code == 409 and "end time" in response.text
    assert week(client, "2090-11-12")["summary"]["verified_completed_minutes"] == 0


@pytest.mark.parametrize("field,value", [("completion_confirmed_at", "2020-11-09T00:00:00Z"), ("completion_previous_status", "in_progress"), ("completion_verified", True), ("completion_remaining_minutes_delta", 20)])
def test_general_edit_rejects_forged_confirmation_metadata(client, field, value):
    _, _, plan = seed(client)
    edited = deepcopy(plan["blocks"])
    edited[0][field] = value
    response = client.put(f"/api/schedules/{plan['id']}", json={"blocks": edited})
    assert response.status_code == 422 and "server-owned" in response.text
    assert week(client)["summary"]["verified_completed_minutes"] == 0


@pytest.mark.parametrize("withdrawal", ["week", "definition"])
def test_withdrawn_elapsed_history_can_only_change_confirmation(client, withdrawal):
    definition, assignment, plan = seed(client)
    if withdrawal == "week":
        response = client.delete(f"/api/task-weeks/{assignment['id']}")
    else:
        response = client.delete(f"/api/task-definitions/{definition['id']}?delete_assignments=true")
    assert response.status_code == 204, response.text
    stored = client.get("/api/schedules").json()[0]
    response = confirm(client, plan)
    assert response.status_code == 200, response.text
    assert response.json()["tasks_dirty"]
    history = week(client)["history_assignments"][0]
    assert history["verified_completed_minutes"] == 30
    assert history["removed_from_week"] and history["status"] == "skipped"
    assert week(client)["assignments"] == []
    assert confirm(client, plan, completed=False).status_code == 200
    assert client.get("/api/schedules").json()[0]["blocks"] == stored["blocks"]
    assert week(client)["history_assignments"][0]["verified_completed_minutes"] == 0
    with client.app.state.session_factory() as db:
        row = db.get(TaskDefinition, definition["id"])
        assert bool(row.payload.get("deleted_at")) == (withdrawal == "definition")


def test_existing_completed_unknown_timestamp_is_not_fabricated(client):
    _, _, plan = seed(client, status="completed")
    response = confirm(client, plan)
    assert response.status_code == 200
    assert "completion_confirmed_at" not in response.json()["blocks"][0]
    assert week(client)["summary"]["verified_completed_minutes"] == 60
    assert confirm(client, plan, completed=False).json()["blocks"][0]["status"] == "todo"
    assert week(client)["summary"]["verified_completed_minutes"] == 30


@pytest.mark.parametrize("corruption", ["missing_ledger", "wrong_schedule", "wrong_session", "wrong_time", "nonwork", "naive"])
def test_invalid_saved_work_is_rejected_without_credit(client, corruption):
    _, _, plan = seed(client)
    with client.app.state.session_factory() as db:
        schedule = db.get(Schedule, plan["id"])
        block_id = plan["blocks"][0]["id"]
        chunk = db.get(TaskChunk, block_id)
        payload = deepcopy(schedule.payload)
        if corruption == "missing_ledger":
            db.delete(chunk)
        elif corruption == "wrong_schedule":
            db.add(Schedule(id="other-plan", date="2020-11-09", payload={"blocks": []}))
            db.flush()
            chunk.schedule_id = "other-plan"
        elif corruption == "wrong_session":
            payload["blocks"][0]["logical_session_id"] = "forged"
        elif corruption == "wrong_time":
            chunk.end = "2020-11-08T08:25:00-05:00"
        elif corruption == "nonwork":
            payload["blocks"][0]["kind"] = "meal"
        else:
            payload["blocks"][0]["end"] = "2020-11-08T08:30:00"
        schedule.payload = payload
        db.commit()
    response = confirm(client, plan)
    assert response.status_code in (409, 422), response.text
    with client.app.state.session_factory() as db:
        assert db.get(LogicalSession, plan["blocks"][0]["logical_session_id"]).completed_minutes == 0


def test_confirmation_uses_absolute_end_instants_and_exact_end_boundary(client):
    _, _, plan = seed(client)
    with client.app.state.session_factory() as db:
        row = db.get(Schedule, plan["id"])
        end = datetime.fromisoformat(plan["blocks"][0]["end"]).astimezone(ZoneInfo("UTC"))
        with pytest.raises(HTTPException, match="409"):
            work_confirmation.confirm_block(db, row, plan["blocks"][0]["id"], True, schemas.Settings().model_dump(), now=end - timedelta(microseconds=1))
        work_confirmation.confirm_block(db, row, plan["blocks"][0]["id"], True, schemas.Settings().model_dump(), now=end)
        db.commit()
    assert week(client)["summary"]["verified_completed_minutes"] == 30


def test_validate_manual_preserves_trusted_timestamp_roundtrip(client):
    _, _, plan = seed(client)
    saved = confirm(client, plan).json()
    normalized = [schemas.Block.model_validate(item).model_dump(mode="json", exclude_none=True) for item in saved["blocks"]]
    validate_manual(saved, normalized, schemas.Settings().model_dump(), [{"id": plan["blocks"][0]["task_id"]}])
    assert normalized[0]["completion_confirmed_at"]


def test_workload_levels_persist_per_date_before_generation_without_changing_strategy(client):
    default = client.get("/api/day-preferences/2030-11-10")
    assert default.status_code == 200
    assert default.json() == {"date": "2030-11-10", "workload_level": "medium"}
    for level in ("very_low", "low", "medium", "high", "very_high"):
        response = client.put("/api/day-preferences/2030-11-10", json={"workload_level": level})
        assert response.status_code == 200, response.text
        assert response.json()["workload_level"] == level
        assert client.get("/api/day-preferences/2030-11-10").json() == response.json()
    assert client.get("/api/day-preferences/2030-11-11").json()["workload_level"] == "medium"
    assert client.get("/api/schedules").json() == []
    _, _, plan = seed(client)
    response = client.put(f"/api/day-preferences/{plan['date']}", json={"workload_level": "low"})
    assert response.status_code == 200
    saved = client.get("/api/schedules").json()[0]
    assert saved["blocks"] == plan["blocks"]
    assert saved["mode"] == plan["mode"]
    assert saved["preferences_dirty"] and saved["needs_regeneration"]
    with client.app.state.session_factory() as db:
        assert db.get(Configuration, "day:2030-11-10").payload == {"workload_level": "very_high"}


@pytest.mark.parametrize("payload", [{"workload_level": "deep"}, {"workload_level": "balanced"}, {"workload_level": "very_high", "mode": "deep"}, {"workload_level": None}])
def test_workload_rejects_unknown_fields_and_optimizer_modes(client, payload):
    assert client.put("/api/day-preferences/2030-11-10", json=payload).status_code == 422
    assert client.get("/api/day-preferences/2030-11-10").json()["workload_level"] == "medium"


def test_completion_requires_existing_plan_block_and_strict_boolean(client):
    _, _, plan = seed(client)
    assert client.post("/api/schedules/missing/blocks/missing/completion", json={"completed": True}).status_code == 404
    assert client.post(f"/api/schedules/{plan['id']}/blocks/missing/completion", json={"completed": True}).status_code == 404
    assert confirm(client, plan, completed="true").status_code == 422
    assert confirm(client, plan, client_timestamp="2020-01-01").status_code == 422


def test_future_historical_completion_can_be_undone_without_asserting_work(client):
    _, _, plan = seed(client, date="2090-11-12", status="completed")
    assert week(client, "2090-11-12")["summary"]["verified_completed_minutes"] == 60
    response = confirm(client, plan, completed=False)
    assert response.status_code == 200, response.text
    assert response.json()["blocks"][0]["status"] == "todo"
    assert week(client, "2090-11-12")["summary"]["verified_completed_minutes"] == 30


def test_bulk_session_completion_rejects_future_chunk_atomically(client):
    _, _, plan = seed(client)
    sid = plan["blocks"][0]["logical_session_id"]
    with client.app.state.session_factory() as db:
        row = db.get(Schedule, plan["id"])
        payload = deepcopy(row.payload)
        payload["blocks"][1].update(start="2090-11-12T09:00:00-05:00", end="2090-11-12T09:30:00-05:00")
        chunk = db.get(TaskChunk, payload["blocks"][1]["id"])
        chunk.start, chunk.end = payload["blocks"][1]["start"], payload["blocks"][1]["end"]
        row.payload = payload
        db.commit()
    before = client.get("/api/schedules").json()[0]
    response = client.put(f"/api/task-sessions/{sid}", json={"status": "completed"})
    assert response.status_code == 422 and "future" in response.text
    assert week(client)["summary"]["verified_completed_minutes"] == 0
    assert client.get("/api/schedules").json()[0] == before
    with client.app.state.session_factory() as db:
        assert all(chunk.credited_minutes == 0 for chunk in db.scalars(select(TaskChunk)))


def test_bulk_past_session_confirmation_stamps_chunks_and_undo_preserves_ledger(client):
    _, _, plan = seed(client)
    sid = plan["blocks"][0]["logical_session_id"]
    response = client.put(f"/api/task-sessions/{sid}", json={"status": "completed"})
    assert response.status_code == 200, response.text
    stored = client.get("/api/schedules").json()[0]
    assert all(block["completion_confirmed_at"] and block["completion_verified"] for block in stored["blocks"])
    assert week(client)["summary"]["verified_completed_minutes"] == 60
    assert confirm(client, plan).json()["blocks"][0]["completion_confirmed_at"] == stored["blocks"][0]["completion_confirmed_at"]
    assert confirm(client, plan, completed=False).status_code == 200
    assert week(client)["summary"]["verified_completed_minutes"] == 30
    assert client.put(f"/api/task-sessions/{sid}", json={"status": "todo"}).status_code == 200
    assert week(client)["summary"]["verified_completed_minutes"] == 0
    assert all(not block.get("completion_confirmed_at") for block in client.get("/api/schedules").json()[0]["blocks"])


def test_elapsed_pending_work_survives_regeneration_selection_and_reserves_its_identity(client):
    _, _, plan = seed(client)
    with client.app.state.session_factory() as db:
        row = db.get(Schedule, plan["id"])
        original = deepcopy(row.payload)
        settings = schemas.Settings().model_dump(mode="json")
        preserved = task_library.regeneration_blocks(db, row.payload["blocks"], settings)
        assert len(preserved) == 2
        assert all(block["_elapsed_work_history"] for block in preserved)
        assert all(block["status"] == "todo" for block in preserved)
        _, _, sessions, context = task_library.planning_inputs(db, plan["date"], settings, preserved)
        assert all(chunk["preserve"] for chunk in context["chunks"])
        assert len(sessions) == 1 and sessions[0]["completed_minutes"] == 0
        assert row.payload == original
        assert all(chunk.credited_minutes == 0 for chunk in db.scalars(select(TaskChunk)))
        assert task_library.regeneration_blocks(db, [{**plan["blocks"][0], "start": "2090-11-12T09:00:00-05:00", "end": "2090-11-12T09:30:00-05:00"}], settings) == []


def test_general_completion_cannot_rewrite_future_saved_interval(client):
    _, _, plan = seed(client, date="2090-11-12")
    blocks = deepcopy(plan["blocks"])
    blocks[0].update(start="2020-11-08T08:00:00-05:00", end="2020-11-08T08:30:00-05:00", status="completed")
    response = client.put(f"/api/schedules/{plan['id']}", json={"blocks": blocks})
    assert response.status_code == 422
    assert client.get("/api/schedules").json()[0]["blocks"] == plan["blocks"]
    assert week(client, "2090-11-12")["summary"]["verified_completed_minutes"] == 0


def test_confirmation_refreshes_weekly_and_daily_projection_snapshots_without_solving(client):
    _, assignment, plan = seed(client, status="skipped")
    with client.app.state.session_factory() as db:
        row = db.get(Schedule, plan["id"])
        row.payload = {**row.payload,
                       "daily_progress": [{"task_definition_id": assignment["task_definition_id"], "title": "Recorded title", "date": plan["date"], "minimum_sessions": 3, "maximum_sessions": 5, "scheduled_sessions": 7, "expected_shortfall": 0}],
                       "weekly_progress": [{"assignment_id": assignment["id"], "task_definition_id": assignment["task_definition_id"], "minimum_sessions": 1, "completed_sessions": 99, "expected_sessions": 99, "expected_shortfall": 0, "planned_today_minutes": 99, "forecast": True, "solver_status": "OPTIMAL"}]}
        db.commit()
    response = confirm(client, plan)
    assert response.status_code == 200, response.text
    stored = response.json()
    assert stored["daily_progress"][0]["scheduled_sessions"] == 1
    assert stored["daily_progress"][0]["expected_shortfall"] == 2
    assert stored["daily_progress"][0]["title"] == "Recorded title"
    assert stored["daily_progress"][0]["maximum_sessions"] == 5
    assert stored["weekly_progress"][0]["completed_sessions"] == 0
    assert stored["weekly_progress"][0]["expected_sessions"] == 0
    assert stored["weekly_progress"][0]["expected_shortfall"] == 1
    assert stored["weekly_progress"][0]["forecast"] is False
    assert stored["weekly_progress"][0]["solver_status"] == "not_run"
    assert confirm(client, plan, 1).json()["weekly_progress"][0]["completed_sessions"] == 1
    restored = confirm(client, plan, completed=False).json()
    assert restored["daily_progress"][0]["scheduled_sessions"] == 1
    assert restored["weekly_progress"][0]["completed_sessions"] == 0


@pytest.mark.parametrize("saved", ["balanced", "deadline", "deep"])
def test_generation_omission_preserves_existing_strategy_and_explicit_mode_wins(saved):
    assert generation_mode(schemas.Generate(date="2030-11-10"), {"mode": saved}) == saved
    assert generation_mode(schemas.Generate(date="2030-11-10", mode="balanced"), {"mode": saved}) == "balanced"
    assert generation_mode(schemas.Generate(date="2030-11-10")) == "balanced"
    assert generation_mode(schemas.Generate(date="2030-11-10"), {"mode": "very_high"}) == "balanced"


@pytest.mark.parametrize("remaining", [0, 20, 60])
def test_finite_legacy_confirmation_tracks_exact_existing_counter_delta_and_undo(client, remaining):
    response = client.post("/api/tasks", json={"title": "Finite QA source", "duration_minutes": 60, "remaining_minutes": remaining})
    assert response.status_code == 201, response.text
    task = response.json()
    plan = {"id": "finite-plan", "date": "2020-11-08", "mode": "deadline", "status": "feasible", "blocks": [{"id": f"finite-{index}", "kind": "task", "task_id": task["id"], "title": task["title"], "start": f"2020-11-08T{8 + index:02}:00:00-05:00", "end": f"2020-11-08T{8 + index:02}:30:00-05:00", "status": "todo"} for index in range(2)]}
    with client.app.state.session_factory() as db:
        db.add(Schedule(id=plan["id"], date=plan["date"], payload=plan))
        db.commit()
    saved = confirm(client, plan)
    assert saved.status_code == 200, saved.text
    delta = min(30, remaining)
    assert saved.json()["blocks"][0]["completion_remaining_minutes_delta"] == delta
    assert confirm(client, plan).status_code == 200
    with client.app.state.session_factory() as db:
        assert db.get(Entity, ("tasks", task["id"])).payload["remaining_minutes"] == remaining - delta
        assert db.get(TaskDefinition, task["id"]).payload["status"] == "active"
        assert list(db.scalars(select(LogicalSession))) == []
        assert list(db.scalars(select(TaskChunk))) == []
    assert confirm(client, plan, 1).status_code == 200
    assert confirm(client, plan, 1, completed=False).status_code == 200
    assert confirm(client, plan, completed=False).json()["blocks"][0] == plan["blocks"][0]
    with client.app.state.session_factory() as db:
        assert db.get(Entity, ("tasks", task["id"])).payload["remaining_minutes"] == remaining


def test_general_finite_accounting_roundtrips_confirmation_delta_without_double_credit():
    task = {"id": "finite", "duration_minutes": 60, "remaining_minutes": 20, "status": "todo"}
    pending = {"id": "block", "task_id": "finite", "start": "2020-11-08T08:00:00-05:00", "end": "2020-11-08T08:30:00-05:00", "status": "todo"}
    completed = {**pending, "status": "completed"}
    updated = account_progress([task], [pending], [completed])[0]
    assert updated["remaining_minutes"] == 0 and updated["status"] == "in_progress"
    assert completed["completion_remaining_minutes_delta"] == 20
    assert account_progress([updated], [completed], [completed])[0] == updated
    assert account_progress([updated], [completed], [pending])[0]["remaining_minutes"] == 20


def test_migrated_legacy_json_without_session_metadata_uses_existing_ledger(client):
    _, _, plan = seed(client)
    with client.app.state.session_factory() as db:
        row = db.get(Schedule, plan["id"])
        payload = deepcopy(row.payload)
        for block in payload["blocks"]:
            for key in ("logical_session_id", "task_assignment_id", "task_definition_id", "chunk_index"):
                block.pop(key)
        row.payload = payload
        db.commit()
    response = confirm(client, plan)
    assert response.status_code == 200, response.text
    assert "logical_session_id" not in response.json()["blocks"][0]
    assert week(client)["summary"]["verified_completed_minutes"] == 30
    assert confirm(client, plan, completed=False).status_code == 200
    assert week(client)["summary"]["verified_completed_minutes"] == 0


def test_explicit_null_legacy_delta_undo_uses_compatible_duration_fallback(client):
    response = client.post("/api/tasks", json={"title": "Historical finite work", "duration_minutes": 60, "remaining_minutes": 30})
    assert response.status_code == 201, response.text
    task = response.json()
    block = {"id": "old-completed", "kind": "task", "task_id": task["id"], "title": task["title"], "start": "2020-11-08T08:00:00-05:00", "end": "2020-11-08T08:30:00-05:00", "status": "completed", "completion_remaining_minutes_delta": None}
    plan = {"id": "old-finite-plan", "date": "2020-11-08", "mode": "balanced", "status": "feasible", "blocks": [block]}
    with client.app.state.session_factory() as db:
        db.add(Schedule(id=plan["id"], date=plan["date"], payload=plan))
        db.commit()
    response = confirm(client, plan, completed=False)
    assert response.status_code == 200, response.text
    assert response.json()["blocks"][0]["status"] == "todo"
    with client.app.state.session_factory() as db:
        assert db.get(Entity, ("tasks", task["id"])).payload["remaining_minutes"] == 60
    pending = {**block, "status": "todo"}
    assert account_progress([task], [block], [pending])[0]["remaining_minutes"] == 60
