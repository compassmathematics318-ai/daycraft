"""Task removal preserves identity and evidence while canceling live demand."""
import asyncio
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app import locations, schemas, task_library
from backend.app.database import LogicalSession, Schedule, TaskChunk, TaskDefinition, TaskWeek
from backend.app.main import create_app, routes_for
from backend.app.main import validate_manual


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "lifecycle.sqlite")) as value:
        yield value


def create_task(client, **fields):
    response = client.post("/api/task-definitions", json={"title": "hi", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def assign(client, task, week):
    response = client.post("/api/task-weeks", json={"task_definition_id": task["id"], "week_start": week})
    assert response.status_code == 201, response.text
    return response.json()


def test_remove_one_week_hides_demand_preserves_history_and_reuses_id(client):
    task = create_task(client)
    first = assign(client, task, "2030-11-10")
    second = assign(client, task, "2030-11-17")
    session = client.post("/api/task-sessions", json={"assignment_id": first["id"], "completed_minutes": 20})
    assert session.status_code == 201
    assert client.delete(f"/api/task-weeks/{first['id']}").status_code == 204
    week = client.get("/api/task-week?week_start=2030-11-10").json()
    assert week["assignments"] == []
    assert week["summary"]["target_minutes"] == 0
    assert week["history_assignments"][0]["completed_minutes"] == 20
    assert week["sessions"][0]["id"] == session.json()["id"]
    summary = client.get("/api/task-definitions").json()[0]["association_summary"]
    assert summary["assigned_week_starts"] == [second["week_start"]]
    restored = assign(client, task, first["week_start"])
    assert restored["id"] == first["id"]
    assert restored["completed_minutes"] == 20


def test_delete_everywhere_preserves_completed_blocks_and_shared_place(client):
    location = client.post("/api/locations", json={"name": "Shared place", "lat": 43.47, "lon": -80.54}).json()
    task = create_task(client, location_id=location["id"])
    other = create_task(client, location_id=location["id"])
    past, future = assign(client, task, "2020-11-08"), assign(client, task, "2030-11-10")
    done = {"id": "done", "kind": "task", "title": "hi", "task_id": task["id"], "task_definition_id": task["id"], "task_assignment_id": past["id"], "logical_session_id": "done-session", "start": "2020-11-08T08:00:00-05:00", "end": "2020-11-08T09:00:00-05:00", "status": "completed", "locked": True, "location_id": location["id"], "location_mode": "required"}
    pending = {**done, "id": "pending", "logical_session_id": "future-session", "task_assignment_id": future["id"], "start": "2030-11-10T08:00:00-05:00", "end": "2030-11-10T09:00:00-05:00", "status": "todo"}
    with client.app.state.session_factory() as db:
        for sid, assignment, status, credit in (("done-session", past, "completed", 60), ("future-session", future, "todo", 0)):
            db.add(LogicalSession(id=sid, assignment_id=assignment["id"], index=0, target_minutes=60, completed_minutes=credit, baseline_completed_minutes=credit, status=status))
        for block, day in ((done, "2020-11-08"), (pending, "2030-11-10")):
            db.add(Schedule(id=day, date=day, payload={"id": day, "date": day, "status": "optimal", "blocks": [deepcopy(block)]}))
        db.flush()
        for block, day in ((done, "2020-11-08"), (pending, "2030-11-10")):
            db.add(TaskChunk(id=block["id"], logical_session_id=block["logical_session_id"], schedule_id=day, start=block["start"], end=block["end"], status=block["status"], credited_minutes=60 if block["id"] == "done" else 0))
        db.commit()
    assert client.delete(f"/api/task-definitions/{task['id']}?delete_assignments=true").status_code == 204
    assert [item["id"] for item in client.get("/api/task-definitions").json()] == [other["id"]]
    with client.app.state.session_factory() as db:
        assert db.get(TaskDefinition, task["id"]).payload["deleted_at"]
        assert db.get(Schedule, "2020-11-08").payload["blocks"] == [done]
        assert db.get(Schedule, "2030-11-10").payload["blocks"] == []
        assert db.get(TaskChunk, "done") is not None
        assert db.get(TaskChunk, "pending") is None
        assert db.get(LogicalSession, "done-session").completed_minutes == 60
    overview = client.get("/api/location-overview?week_start=2020-11-08").json()
    references = [item for place in overview["locations"] for item in place["references"]]
    assert all(item["entity_id"] != task["id"] for item in references)
    assert client.get("/api/locations").json()[0]["id"] == location["id"]


def test_stop_repeating_suppresses_lazy_and_materialized_future_only(client):
    task = create_task(client, recurrence={"start_week": "2020-11-08"})
    past, future = assign(client, task, "2020-11-08"), assign(client, task, "2030-11-10")
    logged = client.post("/api/task-sessions", json={"assignment_id": past["id"], "completed_minutes": 60})
    assert logged.status_code == 201
    response = client.post(f"/api/task-definitions/{task['id']}/stop-repeating", json={"from_week": "2030-11-10"})
    assert response.status_code == 200, response.text
    assert client.get("/api/task-week?week_start=2030-11-10").json()["assignments"] == []
    assert client.get("/api/task-week?week_start=2030-11-17").json()["assignments"] == []
    assert client.get("/api/task-week?week_start=2020-11-08").json()["assignments"][0]["completed_minutes"] == 60
    with client.app.state.session_factory() as db:
        assert db.get(TaskWeek, future["id"]).payload["removed_from_week"]


def test_stopped_task_explicit_weeks_are_copyable_without_duplicate_recurrence(client):
    task = create_task(client, recurrence={"start_week": "2030-11-03"})
    historical = assign(client, task, "2030-11-03")
    assert historical["source"] == "recurring"
    assert client.post(f"/api/task-definitions/{task['id']}/stop-repeating", json={"from_week": "2030-11-10"}).status_code == 200
    explicit = assign(client, task, "2030-11-10")
    assert explicit["source"] == "explicit"
    assert client.get("/api/task-week?week_start=2030-11-10").json()["assignments"][0]["source"] == "explicit"
    copied = client.post("/api/task-weeks/copy", json={"source_week": "2030-11-10", "target_week": "2030-11-17", "deadline_policy": "preserve"})
    assert copied.status_code == 200, copied.text
    assert copied.json()["copied"][0]["source"] == "copy"
    assert copied.json()["week"]["assignments"][0]["source"] == "copy"
    again = client.post("/api/task-weeks/copy", json={"source_week": "2030-11-10", "target_week": "2030-11-17", "deadline_policy": "preserve"}).json()
    assert again["copied"] == []
    assert len(again["week"]["assignments"]) == 1
    history = client.post("/api/task-weeks/copy", json={"source_week": "2030-11-03", "target_week": "2030-11-24", "deadline_policy": "preserve"}).json()
    assert history["copied"] == []
    assert "excluded" in history["skipped"][0]["reason"]
    automatic_destination = client.post("/api/task-weeks/copy", json={"source_week": "2030-11-10", "target_week": "2030-11-03", "deadline_policy": "preserve"}).json()
    assert automatic_destination["copied"] == []
    assert "repeats automatically" in automatic_destination["skipped"][0]["reason"]
    assert client.delete(f"/api/task-weeks/{historical['id']}").status_code == 204
    removed_automatic = client.post("/api/task-weeks/copy", json={"source_week": "2030-11-10", "target_week": "2030-11-03", "deadline_policy": "preserve"}).json()
    assert removed_automatic["copied"] == []
    with client.app.state.session_factory() as db:
        assert len(list(db.scalars(select(TaskWeek).where(TaskWeek.task_definition_id == task["id"], TaskWeek.week_start == "2030-11-03")))) == 1


def test_withdrawn_elapsed_unlocked_work_retains_manual_walking_route(client):
    destination = client.post("/api/locations", json={"name": "Current venue", "lat": 43.471, "lon": -80.541}).json()
    origin = client.post("/api/locations", json={"name": "Historical venue", "lat": 43.470, "lon": -80.540, "travel_overrides": {destination["id"]: 47}}).json()
    task = create_task(client, location_id=origin["id"])
    create_task(client, title="Current work", location_id=destination["id"])
    with client.app.state.session_factory() as db:
        db.add(Schedule(id="history-route", date="2020-11-08", payload={"id": "history-route", "date": "2020-11-08", "status": "optimal", "blocks": [{"id": "elapsed", "task_id": task["id"], "title": "hi", "kind": "task", "status": "todo", "locked": False, "location_id": origin["id"], "location_mode": "required", "start": "2020-11-08T08:00:00-05:00", "end": "2020-11-08T09:00:00-05:00"}]}))
        db.commit()
    assert client.delete(f"/api/task-definitions/{task['id']}?delete_assignments=true").status_code == 204
    with client.app.state.session_factory() as db:
        settings = client.get("/api/state").json()["settings"]
        callback, matrix = asyncio.run(routes_for(db, settings))
        assert callback(origin["id"], destination["id"]) == 47
        assert matrix[(origin["id"], destination["id"])]["minutes"] == 47
        assert matrix[(origin["id"], destination["id"])]["source"] == "Manual override"
        assert matrix[(origin["id"], destination["id"])]["estimated"] is False


def test_commitment_relationships_validate_cycles_and_cleanup(client):
    def activity(title, **fields):
        response = client.post("/api/activities", json={"title": title, "category": "commitment", "subtype": "Groupwork", **fields})
        assert response.status_code == 201, response.text
        return response.json()
    first = activity("First")
    second = activity("Second", related_entity={"kind": "activity", "id": first["id"]})
    assert client.put(f"/api/activities/{first['id']}", json={**first, "related_entity": {"kind": "activity", "id": first["id"]}}).status_code == 422
    assert client.put(f"/api/activities/{first['id']}", json={**first, "related_entity": {"kind": "activity", "id": second["id"]}}).status_code == 422
    assert client.put(f"/api/activities/{first['id']}", json={**first, "related_entity": {"kind": "project", "id": "missing"}}).status_code == 422
    assert client.delete(f"/api/activities/{first['id']}").status_code == 204
    assert client.get("/api/activities").json()[0]["related_entity"] is None
    project = client.post("/api/projects", json={"name": "Project"}).json()
    response = client.put(f"/api/activities/{second['id']}", json={**second, "related_entity": {"kind": "project", "id": project["id"]}})
    assert response.status_code == 200, response.text
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get("/api/activities").json()[0]["related_entity"] is None
    with client.app.state.session_factory() as db:
        assert db.scalar(select(TaskDefinition)) is None


@pytest.mark.parametrize("kind", ["activity", "project"])
def test_related_target_rename_invalidates_saved_commitment_context(client, kind):
    if kind == "activity":
        source = client.post("/api/activities", json={"title": "Source", "category": "class", "subtype": "Lecture"}).json()
    else:
        source = client.post("/api/projects", json={"name": "Source"}).json()
    commitment = client.post("/api/activities", json={"title": "Study group", "category": "commitment", "subtype": "Groupwork", "related_entity": {"kind": kind, "id": source["id"]}}).json()
    with client.app.state.session_factory() as db:
        db.add(Schedule(id="plan", date="2030-11-10", payload={"id": "plan", "date": "2030-11-10", "status": "optimal", "blocks": [{"id": "meeting", "activity_id": commitment["id"]}]}))
        db.commit()
    route = "activities" if kind == "activity" else "projects"
    payload = {**source, "title" if kind == "activity" else "name": "Changed"}
    if kind == "project":
        payload.pop("legacy_task_id", None)
    response = client.put(f"/api/{route}/{source['id']}", json=payload)
    assert response.status_code == 200, response.text
    with client.app.state.session_factory() as db:
        assert db.get(Schedule, "plan").payload["status"] == "stale"


def test_global_delete_filters_distinct_legacy_alias_and_its_history_map_reference(client):
    location = client.post("/api/locations", json={"name": "Saved", "lat": 43.47, "lon": -80.54}).json()
    response = client.post("/api/tasks", json={"title": "Legacy", "duration_minutes": 60, "location_id": location["id"]})
    assert response.status_code == 201, response.text
    alias = response.json()["id"]
    with client.app.state.session_factory() as db:
        row = db.get(TaskDefinition, alias)
        row.id = "canonical-alias-test"
        db.add(Schedule(id="old", date="2020-11-08", payload={"id": "old", "date": "2020-11-08", "status": "optimal", "blocks": [{"id": "legacy-done", "task_id": alias, "kind": "task", "title": "Legacy", "location_id": location["id"], "location_mode": "required", "status": "completed", "locked": True, "start": "2020-11-08T08:00:00-05:00", "end": "2020-11-08T09:00:00-05:00"}]}))
        db.commit()
    assert client.delete(f"/api/tasks/{alias}").status_code == 204
    assert client.get("/api/tasks").json() == []
    overview = client.get("/api/location-overview?week_start=2020-11-08").json()
    assert all(place["references"] == [] for place in overview["locations"])
    with client.app.state.session_factory() as db:
        assert db.get(Schedule, "old").payload["blocks"][0]["task_id"] == alias
        stored = db.get(Schedule, "old").payload["blocks"]
        prepared = {"tasks": []}
        legacy = task_library.withdrawn_history_units(db, prepared, stored)
        assert prepared["tasks"] == []
        assert len(legacy) == 1
        assert legacy[0]["id"] == alias
        assert legacy[0]["status"] == "skipped"
        assert legacy[0]["location_id"] == location["id"]


@pytest.mark.parametrize("delete", [True, False])
@pytest.mark.parametrize("status", ["todo", "in_progress", "completed"])
def test_withdrawn_history_selection_and_units_keep_original_venue_without_new_work(client, delete, status):
    place = client.post("/api/locations", json={"name": "Original venue", "lat": 43.47, "lon": -80.54}).json()
    task = create_task(client, location_id=place["id"], location_mode="preferred", allow_splitting=False)
    week = assign(client, task, "2020-11-08")
    block = {"id": "recorded", "kind": "task", "title": "hi", "task_id": task["id"], "task_definition_id": task["id"], "task_assignment_id": week["id"], "logical_session_id": "recorded-session", "chunk_index": 0, "start": "2020-11-08T08:00:00-05:00", "end": "2020-11-08T09:00:00-05:00", "status": status, "locked": False, "location_id": place["id"], "location_mode": "preferred", "rationale": "Original saved evidence", "location_suitability": {"historical": "retained"}}
    with client.app.state.session_factory() as db:
        db.add(LogicalSession(id="recorded-session", assignment_id=week["id"], index=0, target_minutes=60, completed_minutes=60 if status == "completed" else 0, baseline_completed_minutes=60 if status == "completed" else 0, status=status))
        db.add(Schedule(id="recorded-plan", date="2020-11-08", payload={"id": "recorded-plan", "date": "2020-11-08", "status": "optimal", "blocks": [deepcopy(block)]}))
        db.commit()
    url = f"/api/task-definitions/{task['id']}?delete_assignments=true" if delete else f"/api/task-weeks/{week['id']}"
    assert client.delete(url).status_code == 204
    with client.app.state.session_factory() as db:
        stored = db.get(Schedule, "recorded-plan").payload["blocks"]
        settings = client.get("/api/state").json()["settings"]
        preserved = task_library.regeneration_blocks(db, stored, settings)
        assert len(preserved) == 1
        assert preserved[0]["_withdrawn_history"] is True
        assert {key: value for key, value in preserved[0].items() if key != "_withdrawn_history"} == block
        prepared = {"tasks": [], "date": "2020-11-08"}
        assert task_library.withdrawn_history_units(db, prepared, preserved) == []
        unit = prepared["tasks"][0]
        assert unit["id"] == "session:recorded-session"
        assert unit["status"] == "skipped"
        assert unit["history_only"] is True
        assert unit["location_id"] == place["id"]
        assert unit["location_mode"] == "preferred"
        assert unit["remaining_minutes"] == 60
        assert unit["logical_session_id"] == "recorded-session"
        assert unit["task_assignment_id"] == week["id"]
        task_library.validation_units(db, prepared, stored, [], {"chunks": [], "timezone": "America/Toronto"})
        assert prepared["tasks"][0] == unit
        normalized = [schemas.Block.model_validate(block).model_dump(mode="json", exclude_none=True)]
        task_library.validate_chunk_identity(db, normalized, stored, "2020-11-08")
        restored = task_library.restore_history_snapshots(db, normalized, stored)
        assert restored == preserved
        located = locations.resolve_manual_locations(deepcopy(restored), stored)
        assert located[0].get("resolved_location_id") is None
        enriched = locations.enrich_blocks(db, located, stored)
        assert enriched[0]["location_suitability"] == block["location_suitability"]
        validate_manual({"date": "2020-11-08", "blocks": stored}, restored, settings, [])
        forged = [{**normalized[0], "location_mode": "remote", "location_id": None, "location_override": True}]
        with pytest.raises(Exception) as error:
            task_library.validate_chunk_identity(db, forged, stored, "2020-11-08")
        assert error.value.status_code == 422
