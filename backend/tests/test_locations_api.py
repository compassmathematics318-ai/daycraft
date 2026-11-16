"""Location policy integrity, historical preservation and truthful map references."""
from copy import deepcopy

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from backend.app.database import Schedule, build_database
from backend.app.main import create_app, routes_for
from backend.app.migrate import migrate


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.db"))
    with TestClient(create_app(tmp_path / "planner.db")) as client:
        yield client


def place(client, name="Mathematics and Computer", **extra):
    response = client.post("/api/locations", json={"name": name, "lat": 43.472, "lon": -80.544, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def activity(client, **extra):
    response = client.post("/api/activities", json={"title": "Study group", "category": "commitment", "subtype": "Groupwork", **extra})
    assert response.status_code == 201, response.text
    return response.json()


def occurrence(client, value, **extra):
    response = client.post("/api/occurrences", json={"activity_id": value["id"], "start": "2026-11-10T09:00:00-05:00", "end": "2026-11-10T10:00:00-05:00", **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_saved_place_details_search_and_unknown_field_rejection(client):
    item = place(client, address="200 University Avenue W", building="MC", room="4020", floor="4", entrance="South accessible entrance", aliases=["MC", "Math building"])
    assert client.get("/api/location-search", params={"query": "mc 4020"}).json()["results"] == [item]
    assert client.get("/api/location-search", params={"query": "accessible"}).json()["results"] == [item]
    assert client.post("/api/locations", json={"name": "Bad", "lat": 0, "lon": 0, "unexpected": True}).status_code == 422
    assert client.post("/api/locations", json={"name": "   ", "lat": 0, "lon": 0}).status_code == 422


def test_location_policies_are_explicit_and_optional(client):
    item = place(client)
    inferred = activity(client, location_id=item["id"])
    assert inferred["location_mode"] == "required"
    assert activity(client)["location_mode"] == "unspecified"
    assert activity(client, location_mode="remote")["location_id"] is None
    for mode, key in [("required", None), ("preferred", None), ("remote", item["id"]), ("unspecified", item["id"])]:
        response = client.post("/api/activities", json={"title": "Invalid", "category": "commitment", "subtype": "Personal", "location_mode": mode, "location_id": key})
        assert response.status_code == 422
    assert client.post("/api/task-definitions", json={"title": "Invalid", "location_mode": "required", "location_id": "missing"}).status_code == 422


def test_occurrence_override_inheritance_copy_and_delete_guard(client):
    first = place(client)
    second = place(client, "Library")
    definition = activity(client, location_id=first["id"])
    event = occurrence(client, definition, location_override={"location_mode": "preferred", "location_id": second["id"]})
    assert client.delete(f"/api/locations/{second['id']}").status_code == 409
    # Time-only updates from older clients retain the user's venue override.
    updated = client.put(f"/api/occurrences/{event['id']}", json={"activity_id": definition["id"], "start": event["start"], "end": event["end"]})
    assert updated.status_code == 200
    assert updated.json()["location_override"] == event["location_override"]
    copied = client.post("/api/calendar/copy-previous-week", json={"week_start": "2026-11-15"}).json()
    assert copied["created"] == 1
    assert copied["occurrences"][0]["location_override"] == event["location_override"]
    updated = client.put(f"/api/occurrences/{event['id']}", json={"activity_id": definition["id"], "start": event["start"], "end": event["end"], "location_override": None})
    assert updated.json()["location_override"] is None
    occurrence_payload = {"activity_id": definition["id"], "start": "2026-11-11T09:00:00-05:00", "end": "2026-11-11T10:00:00-05:00", "location_override": {"location_mode": "required", "location_id": "missing"}}
    assert client.post("/api/occurrences", json=occurrence_payload).status_code == 422


def test_overview_groups_actual_events_and_untimed_week_overrides(client):
    first, second = place(client), place(client, "Library")
    definition = activity(client, location_id=first["id"], building="MC", room="4020")
    occurrence(client, definition, location_override={"location_mode": "remote"})
    task = client.post("/api/task-definitions", json={"title": "Write paper", "location_mode": "preferred", "location_id": first["id"]}).json()
    assignment = client.post("/api/task-weeks", json={"task_definition_id": task["id"], "week_start": "2026-11-08", "overrides": {"location_mode": "required", "location_id": second["id"]}})
    assert assignment.status_code == 201, assignment.text
    overview = client.get("/api/location-overview?week_start=2026-11-11").json()
    assert overview["week_start"] == "2026-11-08"
    refs = next(item for item in overview["locations"] if item["id"] == second["id"])["references"]
    assert len(refs) == 1 and refs[0]["source"] == "task_definition" and refs[0]["start"] is None
    remote = next(item for item in overview["unlocated"] if item["entity_id"] == definition["id"] and item["location_mode"] == "remote")
    assert remote["source"] == "activity" and remote["location_mode"] == "remote"
    assert remote["room"] == "" and remote["category"] == "commitment"
    assert client.delete(f"/api/locations/{second['id']}").status_code == 409


def test_home_is_optional_validated_and_does_not_implicitly_route(client, monkeypatch):
    home = place(client, "Home")
    office = place(client, "Office")
    activity(client, location_id=office["id"])
    settings = client.get("/api/state").json()["settings"]
    settings.update(home_location_id=home["id"], start_at_home=False, end_at_home=False)
    response = client.put("/api/settings", json=settings)
    assert response.status_code == 200
    assert client.delete(f"/api/locations/{home['id']}").status_code == 409
    from backend.app import travel
    async def forbidden(*args):
        raise AssertionError("Inactive home coordinates must not be sent to routing")
    monkeypatch.setattr(travel, "get_route", forbidden)
    import asyncio
    with client.app.state.session_factory() as db:
        route, matrix = asyncio.run(routes_for(db, response.json()))
    assert matrix == {} and route(None, None) == 0
    settings.update(home_location_id=None, start_at_home=True)
    assert client.put("/api/settings", json=settings).status_code == 422


def test_place_edits_invalidate_plans_without_rewriting_historical_blocks(client):
    item = place(client)
    block = {"id": "historic", "title": "Worked here", "kind": "personal", "start": "2026-11-10T09:00:00-05:00", "end": "2026-11-10T10:00:00-05:00", "location_id": item["id"], "status": "completed"}
    with client.app.state.session_factory() as db:
        db.add(Schedule(id="old", date="2026-11-10", payload={"id": "old", "date": "2026-11-10", "blocks": [block], "status": "optimal"}))
        db.commit()
    response = client.put(f"/api/locations/{item['id']}", json={**item, "lat": 43.5})
    assert response.status_code == 200
    saved = client.get("/api/schedules?date=2026-11-10").json()[0]
    assert saved["locations_dirty"] and saved["status"] == "stale"
    assert saved["blocks"] == [block]
    assert client.delete(f"/api/locations/{item['id']}").status_code == 409


def test_additive_migration_preserves_original_occurrence_and_all_json(tmp_path):
    engine, _ = build_database(tmp_path / "migration.db")
    config = Config()
    config.set_main_option("script_location", "backend/migrations")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0005_task_recurrence")
        connection.execute(text("INSERT INTO activities(id,payload) VALUES ('activity', :payload)"), {"payload": '{"title":"Preserve original","location_id":null}'})
        connection.execute(text("INSERT INTO occurrences(id,activity_id,start,end,source) VALUES ('event','activity','2026-11-10T14:00:00Z','2026-11-10T15:00:00Z','manual')"))
        before = deepcopy(connection.execute(text("SELECT id,activity_id,start,end,source FROM occurrences")).all())
        payload = connection.execute(text("SELECT payload FROM activities")).scalar_one()
    migrate(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id,activity_id,start,end,source FROM occurrences")).all() == before
        assert connection.execute(text("SELECT payload FROM activities")).scalar_one() == payload
        assert connection.execute(text("SELECT location_override FROM occurrences")).scalar_one() is None
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()
