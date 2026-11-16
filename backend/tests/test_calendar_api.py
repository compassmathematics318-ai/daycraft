"""Real persisted activity/calendar workflows with isolated databases."""
from copy import deepcopy
from datetime import datetime

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import inspect, select

from backend.app.database import Configuration, Entity, Occurrence, Schedule, build_database
from backend.app.main import create_app
from backend.app.schemas import Settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "planner.db")) as client:
        yield client


def block(client, category="class", **values):
    payload = {"title": f"A {category}", "category": category, "subtype": "Lecture" if category == "class" else "Personal" if category == "commitment" else None, **values}
    if category == "assessment":
        payload = {"assessment_start": "2026-11-10T16:00:00-05:00", "assessment_end": "2026-11-10T17:00:00-05:00", **payload}
    response = client.post("/api/activities", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def occurrence(client, activity, date="2026-11-10", start="09:00", end="10:00"):
    response = client.post("/api/occurrences", json={"activity_id": activity["id"], "start": f"{date}T{start}:00-05:00", "end": f"{date}T{end}:00-05:00"})
    assert response.status_code == 201, response.text
    return response.json()


def events(client, week="2026-11-08"):
    response = client.get(f"/api/calendar?week_start={week}")
    assert response.status_code == 200, response.text
    return response.json()["occurrences"]


def empty_meals(client):
    settings = client.get("/api/state").json()["settings"]
    settings["meals"] = []
    assert client.put("/api/settings", json=settings).status_code == 200


@pytest.mark.parametrize("category", ["class", "commitment", "assessment"])
def test_all_definition_types_crud_and_cascade(client, category):
    activity = block(client, category, description="Context for future interpretation")
    assert client.get("/api/state").json()["activities"][0]["id"] == activity["id"]
    if category != "assessment":
        occurrence(client, activity)
    assert len(events(client)) == 1
    updated = {**activity, "title": "Renamed", "description": "Revised context"}
    assert client.put(f"/api/activities/{activity['id']}", json=updated).status_code == 200
    assert client.get("/api/activities").json()[0]["description"] == "Revised context"
    assert client.delete(f"/api/activities/{activity['id']}").status_code == 204
    assert events(client) == []
    assert client.get("/api/activities").json() == []


def test_definition_does_not_reserve_time_and_multiple_placements_share_identity(client):
    activity = block(client, start_date="2026-11-09", end_date="2026-12-10")
    assert events(client) == []
    empty_meals(client)
    generated = client.post("/api/schedules/generate", json={"date": "2026-11-10"}).json()
    assert generated["blocks"] == []
    first = occurrence(client, activity)
    second = occurrence(client, activity, "2026-11-12", "11:00", "12:30")
    assert first["id"] != second["id"]
    assert {event["activity_id"] for event in events(client)} == {activity["id"]}
    with client.app.state.session_factory() as db:
        foreign = inspect(db.bind).get_foreign_keys("occurrences")
        assert foreign[0]["referred_table"] == "activities"
        assert len(list(db.scalars(select(Occurrence)))) == 2


def test_occurrence_update_delete_and_overlap_precision_validation(client):
    activity = block(client)
    event = occurrence(client, activity)
    base = {"activity_id": activity["id"], "start": "2026-11-10T09:30:00-05:00", "end": "2026-11-10T10:30:00-05:00"}
    assert client.post("/api/occurrences", json=base).status_code == 409
    assert client.post("/api/occurrences", json={**base, "start": "2026-11-10T09:31:00-05:00"}).status_code == 422
    assert client.post("/api/occurrences", json={**base, "end": base["start"]}).status_code == 422
    assert client.post("/api/occurrences", json={**base, "start": "2026-11-10T09:30"}).status_code == 422
    moved = client.put(f"/api/occurrences/{event['id']}", json={"activity_id": activity["id"], "start": "2026-11-10T10:05:00-05:00", "end": "2026-11-10T11:10:00-05:00"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["id"] == event["id"]
    assert moved.json()["source"] == "manual"
    assert client.delete(f"/api/occurrences/{event['id']}").status_code == 204
    assert len(client.get("/api/activities").json()) == 1
    assert events(client) == []


def test_assessment_validation_and_explicit_atomic_rescheduling(client):
    assert client.post("/api/activities", json={"category": "assessment", "title": "No times"}).status_code == 422
    assert client.post("/api/activities", json={"category": "class", "title": "Wrong subtype", "subtype": "Personal"}).status_code == 422
    activity = block(client, "assessment")
    event = events(client)[0]
    assert event["source"] == "assessment"
    payload = {"activity_id": activity["id"], "start": event["start"], "end": event["end"]}
    assert client.post("/api/occurrences", json=payload).status_code == 409
    assert client.put(f"/api/occurrences/{event['id']}", json=payload).status_code == 409
    assert client.delete(f"/api/occurrences/{event['id']}").status_code == 409
    activity.update(assessment_start="2026-11-11T19:00:00-05:00", assessment_end="2026-11-11T21:00:00-05:00")
    assert client.put(f"/api/activities/{activity['id']}", json=activity).status_code == 200
    assert len(events(client)) == 1
    assert events(client)[0]["start"] == "2026-11-12T00:00:00Z"
    assert client.post("/api/calendar/copy-previous-week", json={"week_start": "2026-11-15"}).json()["created"] == 0


def test_bounds_include_end_date_but_reject_invalid_existing_placement_update(client):
    activity = block(client, start_date="2026-11-10", end_date="2026-11-10")
    event = occurrence(client, activity, start="23:00", end="23:55")
    value = {**activity, "end_date": "2026-11-09"}
    assert client.put(f"/api/activities/{activity['id']}", json=value).status_code == 422
    value = {**activity, "start_date": "2026-11-11", "end_date": "2026-11-12"}
    assert client.put(f"/api/activities/{activity['id']}", json=value).status_code == 409
    assert client.get("/api/activities").json()[0]["start_date"] == "2026-11-10"
    value = {"activity_id": activity["id"], "start": event["start"], "end": "2026-11-11T00:00:00-05:00"}
    assert client.put(f"/api/occurrences/{event['id']}", json=value).status_code == 200


def test_copy_previous_week_is_partial_idempotent_and_respects_bounds(client):
    regular = block(client, title="Regular")
    limited = block(client, title="Expired", end_date="2026-11-15")
    conflicting = block(client, title="Conflict")
    occurrence(client, regular)
    occurrence(client, limited, "2026-11-11")
    occurrence(client, conflicting, "2026-11-12")
    obstacle = block(client, title="Existing next week")
    occurrence(client, obstacle, "2026-11-19")
    result = client.post("/api/calendar/copy-previous-week", json={"week_start": "2026-11-15"}).json()
    assert result["created"] == 1
    assert len(result["skipped"]) == 2
    second = client.post("/api/calendar/copy-previous-week", json={"week_start": "2026-11-15"}).json()
    assert second["created"] == 0 and second["duplicates"] == 1
    assert len(events(client, "2026-11-15")) == 2
    assert client.get("/api/calendar?week_start=2026-11-10").json()["week_start"] == "2026-11-08"


def test_copy_uses_local_wall_times_across_dst_and_skips_nonexistent_times(client):
    activity = block(client)
    payload = {"activity_id": activity["id"], "start": "2026-03-01T09:00:00-05:00", "end": "2026-03-01T10:00:00-05:00"}
    assert client.post("/api/occurrences", json=payload).status_code == 201
    gap = block(client, title="Spring gap")
    payload = {"activity_id": gap["id"], "start": "2026-03-01T02:30:00-05:00", "end": "2026-03-01T03:30:00-05:00"}
    assert client.post("/api/occurrences", json=payload).status_code == 201
    result = client.post("/api/calendar/copy-previous-week", json={"week_start": "2026-03-08"}).json()
    assert result["created"] == 1 and len(result["skipped"]) == 1
    assert result["occurrences"][0]["start"] == "2026-03-08T13:00:00Z"
    assert "does not exist" in result["skipped"][0]["reason"]


def test_calendar_changes_invalidate_plan_and_cannot_be_cleared_by_task_edits(client):
    empty_meals(client)
    work = client.post("/api/tasks", json={"title": "Work", "duration_minutes": 60}).json()
    activity = block(client)
    event = occurrence(client, activity)
    original = client.post("/api/schedules/generate", json={"date": "2026-11-10"}).json()
    assert any(item.get("occurrence_id") == event["id"] for item in original["blocks"])
    assert client.put(f"/api/occurrences/{event['id']}", json={"activity_id": activity["id"], "start": "2026-11-10T14:00:00-05:00", "end": "2026-11-10T15:00:00-05:00"}).status_code == 200
    stale = client.get("/api/schedules").json()[0]
    assert stale["status"] == "stale" and stale["calendar_dirty"]
    assert client.put(f"/api/schedules/{stale['id']}", json={"blocks": stale["blocks"]}).status_code == 409
    work["status"] = "completed"
    assert client.put(f"/api/tasks/{work['id']}", json=work).status_code == 200
    assert client.get("/api/schedules").json()[0]["status"] == "stale"
    updated = client.post("/api/schedules/generate", json={"date": "2026-11-10"}).json()
    fixed = next(item for item in updated["blocks"] if item.get("occurrence_id") == event["id"])
    assert datetime.fromisoformat(fixed["start"]).hour == 14
    assert not updated.get("calendar_dirty") and not updated["conflicts"]


def test_description_metadata_reaches_real_optimizer_fixed_blocks(client):
    empty_meals(client)
    activity = block(client, "commitment", description="Hardware prototyping group", course="ECE 198", building="Engineering", room="204")
    event = occurrence(client, activity)
    generated = client.post("/api/schedules/generate", json={"date": "2026-11-10"}).json()
    item = next(item for item in generated["blocks"] if item.get("occurrence_id") == event["id"])
    assert item["description"] == activity["description"]
    assert item["category"] == "commitment" and item["course"] == "ECE 198"
    assert item["building"] == "Engineering" and item["room"] == "204"
    assert item["locked"] and item["kind"] == "class"


def test_restart_preserves_definitions_occurrences_and_migrations(tmp_path):
    path = tmp_path / "restart.db"
    with TestClient(create_app(path)) as first:
        activity = block(first)
        event = occurrence(first, activity)
    with TestClient(create_app(path)) as second:
        assert second.get("/api/activities").json()[0]["id"] == activity["id"]
        assert events(second)[0]["id"] == event["id"]


def old_database(path, originals, snapshot=None):
    engine, sessions = build_database(path)
    config = Config()
    config.set_main_option("script_location", "backend/migrations")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001_initial")
    with sessions() as db:
        db.add(Configuration(id="settings", payload={**Settings().model_dump(mode="json"), "meals": []}))
        for original in originals:
            db.add(Entity(collection="classes", id=original["id"], payload=deepcopy(original)))
        if snapshot:
            db.add(Schedule(id=snapshot["id"], date=snapshot["date"], payload=deepcopy(snapshot)))
        db.commit()
    engine.dispose()


def legacy(**values):
    return {"id": "old", "title": "Preserved class", "class_type": "Lecture", "date": None, "weekdays": [0, 2], "start_time": "09:00", "end_time": "10:00", "start_date": "2026-11-01", "end_date": "2026-12-31", "exceptions": ["2026-11-11"], "location_id": None, "building": "MC", "room": "4020", **values}


def test_migration_retains_raw_classes_recurrence_and_completed_history(tmp_path):
    original = legacy()
    completed = {"id": "historical-class", "title": original["title"], "kind": "class", "start": "2026-11-09T09:00:00-05:00", "end": "2026-11-09T10:00:00-05:00", "class_id": original["id"], "locked": True, "status": "completed", "location_id": None, "task_id": None, "rationale": "Original historical proof", "estimated": False}
    snapshot = {"id": "old-plan", "date": "2026-11-09", "mode": "balanced", "status": "optimal", "solver_status": "OPTIMAL", "blocks": [completed], "unallocated": [], "conflicts": [], "explanations": [], "stats": {}}
    path = tmp_path / "migrate.db"
    old_database(path, [original], snapshot)
    with TestClient(create_app(path)) as client:
        state = client.get("/api/state").json()
        assert state["classes"] == [original]
        projected = state["schedules"][0]
        assert projected["archive_id"] is None and projected["archive_updated_at"] is None
        assert projected["schedule_revision_id"] == "legacy:old-plan"
        assert {key: value for key, value in projected.items() if key not in {"archive_id", "archive_updated_at", "schedule_revision_id"}} == snapshot
        with client.app.state.session_factory() as db:
            assert db.get(Schedule, snapshot["id"]).payload == snapshot
        assert state["activities"][0]["legacy_class_id"] == original["id"]
        assert [item["id"] for item in events(client)] == ["legacy:old:2026-11-09"]
        regenerated = client.post("/api/schedules/generate", json={"date": "2026-11-09"}).json()
        assert len([item for item in regenerated["blocks"] if item["kind"] == "class"]) == 1
        assert regenerated["blocks"][0] == completed


def test_legacy_virtual_move_and_delete_affect_only_selected_occurrence(client):
    original = legacy(exceptions=[])
    original.pop("id")
    saved = client.post("/api/classes", json=original).json()
    library = client.get("/api/activities").json()[0]
    before = events(client)
    assert len(before) == 2
    moved = client.put(f"/api/occurrences/{before[0]['id']}", json={"activity_id": library["id"], "start": "2026-11-09T11:00:00-05:00", "end": "2026-11-09T12:00:00-05:00"})
    assert moved.status_code == 200, moved.text
    assert len(events(client)) == 2
    old = client.get("/api/classes").json()[0]
    assert "2026-11-09" in old["exceptions"]
    remaining = next(item for item in events(client) if item["source"] == "legacy")
    assert client.delete(f"/api/occurrences/{remaining['id']}").status_code == 204
    assert len(events(client)) == 1
    assert len(events(client, "2026-11-15")) == 2
    assert client.get("/api/classes").json()[0]["id"] == saved["id"]


@pytest.mark.parametrize("class_type,date", [("Exam", "2026-11-10"), ("Exam", None), ("Custom seminar", None)])
def test_legacy_exam_and_custom_types_survive_migration(tmp_path, class_type, date):
    original = legacy(class_type=class_type, date=date, exceptions=[])
    path = tmp_path / "legacy.db"
    old_database(path, [original])
    with TestClient(create_app(path)) as client:
        assert client.get("/api/classes").json() == [original]
        activity = client.get("/api/activities").json()[0]
        assert activity["category"] == ("assessment" if date else "commitment")
        assert len(events(client)) == (1 if date else 2)


def test_excluded_legacy_assessment_stays_excluded_on_metadata_edit(tmp_path):
    original = legacy(class_type="Exam", date="2026-11-10", exceptions=["2026-11-10"])
    path = tmp_path / "excluded.db"
    old_database(path, [original])
    with TestClient(create_app(path)) as client:
        assert events(client) == []
        value = client.get("/api/activities").json()[0]
        value["description"] = "Useful preserved description"
        assert client.put(f"/api/activities/{value['id']}", json=value).status_code == 200
        assert events(client) == []
        value.update(assessment_start="2026-11-10T14:00:00-05:00", assessment_end="2026-11-10T15:00:00-05:00")
        assert client.put(f"/api/activities/{value['id']}", json=value).status_code == 200
        assert len(events(client)) == 1


def test_copy_does_not_copy_prior_weeks_overnight_intersection(client):
    activity = block(client)
    value = {"activity_id": activity["id"], "start": "2026-11-07T23:00:00-05:00", "end": "2026-11-08T01:00:00-05:00"}
    assert client.post("/api/occurrences", json=value).status_code == 201
    assert len(events(client)) == 1
    assert client.post("/api/calendar/copy-previous-week", json={"week_start": "2026-11-15"}).json()["created"] == 0


def test_legacy_repeat_edit_preserves_groupwork_description_and_course(client):
    original = legacy(class_type="Commitment", exceptions=[])
    original.pop("id")
    raw = client.post("/api/classes", json=original).json()
    activity = client.get("/api/activities").json()[0]
    activity.update(subtype="Groupwork", description="Team prototype meeting", course="ECE 198")
    assert client.put(f"/api/activities/{activity['id']}", json=activity).status_code == 200
    raw.update(room="502", weekdays=[1, 3])
    assert client.put(f"/api/classes/{raw['id']}", json=raw).status_code == 200
    saved = client.get("/api/activities").json()[0]
    assert saved["subtype"] == "Groupwork" and saved["course"] == "ECE 198"
    assert saved["description"] == "Team prototype meeting" and saved["room"] == "502"


def test_calendar_rejects_offsets_that_disguise_off_grid_instants(client):
    activity = block(client)
    payload = {"activity_id": activity["id"], "start": "2026-11-10T10:00:00+05:37", "end": "2026-11-10T11:00:00+05:37"}
    assert client.post("/api/occurrences", json=payload).status_code == 422


@pytest.mark.parametrize("date", ["2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14"])
def test_calendar_normalizes_every_day_to_containing_sunday(client, date):
    response = client.get(f"/api/calendar?week_start={date}")
    assert response.status_code == 200, response.text
    assert response.json()["week_start"] == "2026-11-08"
    assert response.json()["week_end"] == "2026-11-14"


@pytest.mark.parametrize("date,start,end", [
    ("2026-11-07", "2026-11-01", "2026-11-07"),
    ("2026-11-15", "2026-11-15", "2026-11-21"),
    ("2027-01-01", "2026-12-27", "2027-01-02"),
])
def test_sunday_calendar_boundaries_across_adjacent_weeks_and_year(client, date, start, end):
    result = client.get(f"/api/calendar?week_start={date}").json()
    assert (result["week_start"], result["week_end"]) == (start, end)


def test_sunday_week_uses_local_midnight_without_changing_persisted_occurrences(client):
    activity = block(client)
    bounds = [
        ("2026-11-07T23:55:00-05:00", "2026-11-08T00:00:00-05:00"),
        ("2026-11-08T00:00:00-05:00", "2026-11-08T00:05:00-05:00"),
        ("2026-11-11T10:30:00-05:00", "2026-11-11T11:30:00-05:00"),
        ("2026-11-14T23:55:00-05:00", "2026-11-15T00:00:00-05:00"),
        ("2026-11-15T00:00:00-05:00", "2026-11-15T00:05:00-05:00"),
    ]
    saved = []
    for start, end in bounds:
        response = client.post("/api/occurrences", json={"activity_id": activity["id"], "start": start, "end": end})
        assert response.status_code == 201, response.text
        saved.append(response.json())
    assessment = block(client, "assessment", assessment_start="2026-11-14T20:00:00-05:00", assessment_end="2026-11-14T21:00:00-05:00")
    before = client.get("/api/activities").json()
    result = client.get("/api/calendar?week_start=2026-11-11").json()
    assert {event["id"] for event in result["occurrences"]} == {event["id"] for event in saved[1:4]} | {f"assessment:{assessment['id']}"}
    assert events(client, "2026-11-01") == saved[:1]
    assert events(client, "2026-11-15") == saved[4:]
    assert client.get("/api/activities").json() == before
    with client.app.state.session_factory() as db:
        stored = {row.id: (row.start, row.end) for row in db.scalars(select(Occurrence))}
        assert all(stored[event["id"]] == (event["start"], event["end"]) for event in saved)


def test_copy_normalizes_midweek_target_and_copies_sunday_through_saturday_only(client):
    activity = block(client)
    preceding = occurrence(client, activity, "2026-10-31")
    sunday = occurrence(client, activity, "2026-11-01")
    saturday = occurrence(client, activity, "2026-11-07")
    assessment = block(client, "assessment", assessment_start="2026-11-07T15:00:00-05:00", assessment_end="2026-11-07T16:00:00-05:00")
    original = events(client, "2026-11-01")
    result = client.post("/api/calendar/copy-previous-week", json={"week_start": "2026-11-11"})
    assert result.status_code == 200, result.text
    assert result.json()["created"] == 2
    assert {event["start"] for event in result.json()["occurrences"]} == {"2026-11-08T14:00:00Z", "2026-11-14T14:00:00Z"}
    assert all(event["activity_id"] != assessment["id"] for event in result.json()["occurrences"])
    assert {event["id"] for event in original} >= {sunday["id"], saturday["id"]}
    assert events(client, "2026-11-01") == original
    assert events(client, "2026-10-25") == [preceding]
    repeated = client.post("/api/calendar/copy-previous-week", json={"week_start": "2026-11-08"}).json()
    assert repeated["created"] == 0 and repeated["duplicates"] == 2


def test_sunday_grouping_preserves_legacy_weekday_numbers_and_sunday_occurrences(client):
    original = legacy(weekdays=[6, 0, 5], exceptions=[])
    original.pop("id")
    response = client.post("/api/classes", json=original)
    assert response.status_code == 201, response.text
    saved = response.json()
    result = events(client)
    assert [event["start"] for event in result] == ["2026-11-08T14:00:00Z", "2026-11-09T14:00:00Z", "2026-11-14T14:00:00Z"]
    assert client.get("/api/classes").json() == [saved]
