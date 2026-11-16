"""Cross-week completion evidence using isolated, explicitly seeded saved plans."""
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app import history, task_library, task_recurrence, work_confirmation
from backend.app.database import CompletedWork, LogicalSession, Schedule, TaskChunk, TaskWeek
from backend.app.main import create_app
from backend.tests.test_history import archived, completed, reverse, save
from backend.tests.test_work_confirmation import confirm, week


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "weekly-history.sqlite")) as value:
        yield value


def freeze_clock(monkeypatch, instant):
    fixed = datetime.fromisoformat(instant)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    for module in (history, task_library, task_recurrence, work_confirmation):
        monkeypatch.setattr(module, "datetime", Clock)


def definition(client, recurring):
    response = client.post("/api/task-definitions", json={
        "title": "Original weekly reading", "description": "Original context",
        "session_minutes": 60, "allow_splitting": True, "min_chunk_minutes": 20,
        "recurrence": {"start_week": "2020-12-27"} if recurring else None,
    })
    assert response.status_code == 201, response.text
    return response.json()


def saved_week(client, task, date, first_start):
    response = client.post("/api/task-weeks", json={"task_definition_id": task["id"], "week_start": date})
    assert response.status_code == 201, response.text
    assignment = response.json()
    session_id, plan_id = "session:" + assignment["id"], "plan:" + date
    start = datetime.fromisoformat(first_start)
    blocks = []
    for index in range(2):
        chunk_start = start + timedelta(minutes=30 * index)
        blocks.append({"id": f"{plan_id}:chunk:{index}", "kind": "task", "title": task["title"],
                       "task_id": task["id"], "task_definition_id": task["id"],
                       "task_assignment_id": assignment["id"], "logical_session_id": session_id,
                       "chunk_index": index, "start": chunk_start.isoformat(),
                       "end": (chunk_start + timedelta(minutes=30)).isoformat(), "status": "todo"})
    plan = {"id": plan_id, "date": date, "mode": "balanced", "status": "feasible",
            "blocks": blocks, "explanations": ["SEEDED_QA_FIXTURE_NOT_GENERATED"]}
    with client.app.state.session_factory() as db:
        db.add(LogicalSession(id=session_id, assignment_id=assignment["id"], index=0,
                             target_minutes=60, completed_minutes=0, baseline_completed_minutes=0, status="todo"))
        db.add(Schedule(id=plan_id, date=date, payload=plan))
        db.flush()
        task_library.persist_chunks(db, db.get(Schedule, plan_id))
        db.commit()
    return assignment, plan


@pytest.mark.parametrize("recurring", [False, True], ids=["week-specific", "every-week"])
def test_late_year_boundary_confirmation_and_old_week_reversal_are_isolated(client, monkeypatch, recurring):
    freeze_clock(monkeypatch, "2021-01-04T00:30:00+00:00")  # Sunday evening in Toronto
    task = definition(client, recurring)
    original, old_plan = saved_week(client, task, "2021-01-02", "2021-01-03T04:00:00+00:00")
    assert original["week_start"] == "2020-12-27"
    assert confirm(client, old_plan).status_code == 200
    assert confirm(client, old_plan, 1).status_code == 200
    old_archive = save(client, old_plan)
    entries = completed(client)["items"]
    assert len(entries) == 2
    assert all(item["completion_date"] == "2021-01-03" for item in entries)
    assert all(item["scheduled_date"] == "2021-01-02" and item["week_start"] == "2020-12-27" for item in entries)
    assert week(client, "2021-01-02")["summary"]["completed_sessions"] == 1
    new_week = week(client, "2021-01-03")
    assert new_week["summary"]["verified_completed_minutes"] == 0
    assert new_week["sessions"] == []
    assert len(new_week["assignments"]) == int(recurring)
    with client.app.state.session_factory() as db:
        assert len(list(db.scalars(select(TaskWeek)))) == 1  # recurrence read is lazy

    current, new_plan = saved_week(client, task, "2021-01-03", "2021-01-03T13:00:00+00:00")
    assert current["id"] != original["id"]
    assert confirm(client, new_plan).status_code == 200
    current_archive = save(client, new_plan)
    current_before = deepcopy(week(client, "2021-01-03"))
    settings = client.get("/api/state").json()["settings"]
    with client.app.state.session_factory() as db:
        current_plan_before = deepcopy(db.get(Schedule, new_plan["id"]).payload)
        current_inputs = task_library.planning_inputs(db, new_plan["date"], settings, current_plan_before["blocks"])
    item = next(item for item in entries if item["source_block_id"] == old_plan["blocks"][0]["id"])
    first = reverse(client, item)
    assert first["changed"]
    assert reverse(client, item) == {**first, "changed": False}
    assert week(client, "2021-01-03") == current_before
    assert week(client, "2021-01-02")["summary"]["verified_completed_minutes"] == 30
    assert week(client, "2021-01-02")["summary"]["completed_sessions"] == 0
    assert week(client, "2021-01-02")["summary"]["scheduled_sessions"] == 1
    assert week(client, "2021-01-02")["summary"]["allocated_sessions"] == 1
    assert archived(client, old_archive["id"])["completed_minutes"] == 30
    assert archived(client, current_archive["id"]) == {key: value for key, value in current_archive.items() if key != "created"}
    with client.app.state.session_factory() as db:
        assert db.get(Schedule, new_plan["id"]).payload == current_plan_before
        corrected = db.get(Schedule, old_plan["id"]).payload
        assert corrected["status"] == "stale"
        assert task_library.planning_inputs(db, new_plan["date"], settings, current_plan_before["blocks"]) == current_inputs
        old_inputs = task_library.planning_inputs(db, old_plan["date"], settings, corrected["blocks"])
        assert len(old_inputs[2]) == 1 and old_inputs[2][0]["completed_minutes"] == 30
        assert old_inputs[2][0]["assignment_id"] == original["id"]
        chunks = {chunk["id"]: chunk for chunk in old_inputs[3]["chunks"]}
        assert chunks[old_plan["blocks"][0]["id"]]["status"] == "todo"
        assert chunks[old_plan["blocks"][1]["id"]]["status"] == "completed"
        assert not any(chunk["schedule_id"] == new_plan["id"] for chunk in chunks.values())
        assert db.get(TaskChunk, old_plan["blocks"][1]["id"]).credited_minutes == 30
        row = db.get(CompletedWork, item["id"])
        assert row.confirmed_at == item["confirmed_at"] and row.reopened_at
        history.backfill_completions(db, settings)
        db.commit()
    assert completed(client)["summary"]["completed_minutes"] == 60
    assert client.get("/api/task-definitions").json()[0]["status"] == "active"


@pytest.mark.parametrize("status", ["paused", "archived"])
def test_historical_credit_and_reversal_survive_definition_metadata_and_lifecycle_edits(client, monkeypatch, status):
    freeze_clock(monkeypatch, "2021-01-04T12:00:00+00:00")
    task = definition(client, True)
    assignment, plan = saved_week(client, task, "2021-01-02", "2021-01-02T13:00:00+00:00")
    assert confirm(client, plan).status_code == 200
    archive = save(client, plan)
    entry = completed(client)["items"][0]
    response = client.put(f"/api/task-definitions/{task['id']}", json={
        "title": "New library title", "description": "New meaning", "session_minutes": 90,
        "min_sessions_per_week": 3, "status": status, "recurrence": task["recurrence"],
    })
    assert response.status_code == 200, response.text
    historical = week(client, "2020-12-27")["assignments"][0]
    assert historical["session_minutes"] == 60 and historical["min_sessions_per_week"] == 1
    assert historical["effective_definition"]["title"] == task["title"]
    assert historical["effective_definition"]["status"] == status
    assert historical["verified_completed_minutes"] == 30
    assert completed(client)["items"][0] == entry
    assert archived(client, archive["id"])["payload"] == archive["payload"]
    assert client.delete(f"/api/schedule-archives/{archive['id']}").status_code == 204
    assert reverse(client, entry)["changed"]
    assert week(client, "2020-12-27")["summary"]["verified_completed_minutes"] == 0
    assert client.get("/api/task-definitions").json()[0]["status"] == status
    with client.app.state.session_factory() as db:
        session = db.get(LogicalSession, plan["blocks"][0]["logical_session_id"])
        assert session.assignment_id == assignment["id"] and session.target_minutes == 60


@pytest.mark.parametrize("recurring", [False, True], ids=["week-specific", "every-week"])
def test_november_2026_four_session_target_rolls_from_three_to_zero(client, monkeypatch, recurring):
    freeze_clock(monkeypatch, "2026-11-15T04:59:00+00:00")  # Saturday Nov 14, 23:59 Toronto
    response = client.post("/api/task-definitions", json={
        "title": "Four weekly sessions", "session_minutes": 30, "min_sessions_per_week": 4,
        "recurrence": {"start_week": "2026-11-08"} if recurring else None,
    })
    assert response.status_code == 201, response.text
    task = response.json()
    response = client.post("/api/task-weeks", json={"task_definition_id": task["id"], "week_start": "2026-11-08"})
    assert response.status_code == 201, response.text
    original = response.json()
    for _ in range(3):
        response = client.post("/api/task-sessions", json={"assignment_id": original["id"]})
        assert response.status_code == 201, response.text
    old_week = week(client, "2026-11-14")
    assert (old_week["week_start"], old_week["week_end"]) == ("2026-11-08", "2026-11-14")
    assert old_week["summary"]["target_sessions"] == 4
    assert old_week["summary"]["completed_sessions"] == 3
    history_before = completed(client)["items"]
    assert len(history_before) == 3
    assert all(item["completion_date"] == "2026-11-14" for item in history_before)

    freeze_clock(monkeypatch, "2026-11-15T05:00:00+00:00")  # Sunday Nov 15, 00:00 Toronto
    assert task_library.current_week({"timezone": "America/Toronto"}) == "2026-11-15"
    new_week = week(client, "2026-11-15")
    assert (new_week["week_start"], new_week["week_end"]) == ("2026-11-15", "2026-11-21")
    assert new_week["summary"]["completed_sessions"] == 0
    assert new_week["sessions"] == []
    if recurring:
        assert new_week["assignments"][0]["target_sessions"] == 4
        assert new_week["assignments"][0]["is_virtual"]
    else:
        assert new_week["assignments"] == []
        response = client.post("/api/task-weeks", json={"task_definition_id": task["id"], "week_start": "2026-11-15"})
        assert response.status_code == 201, response.text
        assert response.json()["completed_sessions"] == 0 and response.json()["target_sessions"] == 4
        assert response.json()["id"] != original["id"]
    assert week(client, "2026-11-08")["summary"]["completed_sessions"] == 3
    assert completed(client)["items"] == history_before
    assert client.get("/api/task-definitions").json()[0]["status"] == "active"


@pytest.mark.parametrize("zone,instant,expected", [
    ("America/Toronto", "2021-01-03T04:59:00+00:00", "2020-12-27"),
    ("America/Toronto", "2021-01-03T05:00:00+00:00", "2021-01-03"),
    ("Asia/Kathmandu", "2021-01-02T18:14:00+00:00", "2020-12-27"),
    ("Asia/Kathmandu", "2021-01-02T18:15:00+00:00", "2021-01-03"),
    ("America/Toronto", "2026-03-08T06:59:00+00:00", "2026-03-08"),
    ("America/Toronto", "2026-03-08T07:00:00+00:00", "2026-03-08"),
    ("America/Toronto", "2026-11-01T05:30:00+00:00", "2026-11-01"),
    ("America/Toronto", "2026-11-01T06:30:00+00:00", "2026-11-01"),
])
def test_implicit_recurrence_start_uses_configured_local_week(client, monkeypatch, zone, instant, expected):
    freeze_clock(monkeypatch, instant)
    settings = client.get("/api/state").json()["settings"]
    settings["timezone"] = zone
    assert client.put("/api/settings", json=settings).status_code == 200
    response = client.post("/api/task-definitions", json={"title": "Local week boundary", "recurrence": {"kind": "weekly"}})
    assert response.status_code == 201, response.text
    assert response.json()["recurrence"]["start_week"] == expected
    assert task_library.current_week(settings) == expected
    assert datetime.fromisoformat(instant).astimezone(ZoneInfo(zone)).date().isoformat() >= expected
    with client.app.state.session_factory() as db:
        assert not list(db.scalars(select(TaskWeek)))
        assert not list(db.scalars(select(LogicalSession)))
