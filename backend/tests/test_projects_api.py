"""Project CRUD, relationships, planning context and lossless migration."""
from copy import deepcopy
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from backend.app.database import Configuration, Entity, Project, Schedule, TaskProject, build_database
from backend.app.main import create_app
from backend.app.migrate import migrate
from backend.app.schemas import Settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with TestClient(create_app(tmp_path / "planner.db")) as value:
        yield value


def project(client, **values):
    response = client.post("/api/projects", json={"name": "Vector", **values})
    assert response.status_code == 201, response.text
    return response.json()


def task(client, **values):
    response = client.post("/api/tasks", json={"title": "Implement processor", "duration_minutes": 50, "remaining_minutes": 50, "min_session_minutes": 50, "max_session_minutes": 50, "splittable": False, **values})
    assert response.status_code == 201, response.text
    return response.json()


def settings(client):
    value = client.get("/api/state").json()["settings"]
    value.update(work_start="08:00", work_end="08:50", focus_minutes=50, break_minutes=0, meals=[], travel_buffer_minutes=0)
    assert client.put("/api/settings", json=value).status_code == 200


def generate(client, **values):
    response = client.post("/api/schedules/generate", json={"date": "2030-11-10", **values})
    assert response.status_code == 200, response.text
    return response.json()


def writable(value):
    return {key: item for key, item in value.items() if key != "legacy_task_id"}


def test_all_metadata_crud_and_project_without_tasks_consumes_no_time(client):
    settings(client)
    payload = dict(affiliations=["Waterloo Reality Labs", "University of Waterloo"], start_date="2030-10-01", end_date="2031-06-30", contributors=3, importance=8.5, difficulty=7.5, description="Purpose, technical challenges, responsibilities.", goals="Ship a useful processor.", links=["https://github.com/example/vector", "https://example.com/docs"], category="research", status="planning")
    created = project(client, **payload)
    assert all(created[key] == value for key, value in payload.items())
    assert created["legacy_task_id"] is None
    assert client.get(f"/api/projects/{created['id']}").json() == created
    assert client.get("/api/state").json()["projects"] == [created]
    result = generate(client)
    assert result["blocks"] == []
    assert result["project_context"]["projects"][0]["task_ids"] == []
    assert result["project_context"]["projects"][0]["goals"] == payload["goals"]
    updated = {**writable(created), "name": "Vector revised", "importance": 9, "difficulty": 0, "status": "active", "affiliations": ["Independent"]}
    response = client.put(f"/api/projects/{created['id']}", json=updated)
    assert response.status_code == 200, response.text
    assert response.json()["difficulty"] == 0
    assert response.json()["name"] == "Vector revised"
    assert client.delete(f"/api/projects/{created['id']}").status_code == 204
    assert client.get("/api/projects").json() == []


@pytest.mark.parametrize("invalid", [
    {"name": " "}, {"importance": 0.5}, {"importance": 10.5}, {"importance": 3.25},
    {"difficulty": -0.5}, {"difficulty": 10.5}, {"difficulty": 0.1}, {"importance": True}, {"difficulty": False},
    {"contributors": 0}, {"contributors": -1}, {"contributors": 1.5}, {"contributors": True},
    {"start_date": "2030-02-02", "end_date": "2030-02-01"},
    {"start_date": "bad-date"}, {"status": "unknown"}, {"category": "unknown"},
    {"links": ["javascript:alert(1)"]}, {"links": ["https://"]}, {"links": ["https://user:password@example.com"]},
    {"affiliations": [""]}, {"unknown": "must not be persisted"},
    {"duration_minutes": 100}, {"legacy_snapshot": {}}, {"legacy_task_id": "spoofed"},
])
def test_validation_rejects_invalid_and_work_specific_fields(client, invalid):
    response = client.post("/api/projects", json={"name": "Invalid", **invalid})
    assert response.status_code == 422, response.text
    assert client.get("/api/projects").json() == []


@pytest.mark.parametrize("importance,difficulty", [(1, 0), (1.5, 0.5), (9.5, 9.5), (10, 10)])
def test_valid_slider_edges_and_half_steps(client, importance, difficulty):
    created = project(client, importance=importance, difficulty=difficulty)
    assert (created["importance"], created["difficulty"], created["contributors"]) == (importance, difficulty, 1)


def test_task_link_unlink_legacy_client_and_explicit_project_delete(client):
    container = project(client)
    work = task(client, project_id=container["id"])
    assert work["project_id"] == container["id"]
    # An old client lacks the new optional field: ordinary edits preserve it.
    old_client = {key: value for key, value in work.items() if key != "project_id"}
    old_client["title"] = "Renamed work"
    response = client.put(f"/api/tasks/{work['id']}", json=old_client)
    assert response.status_code == 200, response.text
    assert response.json()["project_id"] == container["id"]
    assert client.post("/api/tasks", json={"title": "Missing project", "project_id": "missing"}).status_code == 422
    assert client.delete(f"/api/projects/{container['id']}").status_code == 409
    assert client.get("/api/tasks").json()[0]["project_id"] == container["id"]
    response = client.put(f"/api/tasks/{work['id']}", json={**old_client, "project_id": None})
    assert response.status_code == 200, response.text
    assert response.json()["project_id"] is None
    response = client.put(f"/api/tasks/{work['id']}", json={**response.json(), "project_id": container["id"]})
    assert response.status_code == 200, response.text
    before = response.json()
    assert client.delete(f"/api/projects/{container['id']}?detach_tasks=true").status_code == 204
    after = client.get("/api/tasks").json()[0]
    assert after == {**before, "project_id": None}
    assert client.get("/api/projects").json() == []


def test_project_and_association_persist_after_restart(tmp_path):
    path = tmp_path / "persistent.sqlite"
    with TestClient(create_app(path)) as client:
        container = project(client, importance=8.5, difficulty=6.5, affiliations=["Independent"], goals="Ship", description="Context", contributors=2)
        work = task(client, project_id=container["id"])
    with TestClient(create_app(path)) as client:
        assert client.get("/api/projects").json() == [container]
        assert client.get("/api/tasks").json() == [work]
        with client.app.state.session_factory() as db:
            foreign = inspect(db.bind).get_foreign_keys("task_projects")
            assert {item["referred_table"] for item in foreign} == {"projects", "entities"}
            assert db.get(TaskProject, ("tasks", work["id"])).project_id == container["id"]
            db.delete(db.get(Project, container["id"]))
            with pytest.raises(IntegrityError):
                db.commit()


def test_new_legacy_kind_task_does_not_fabricate_a_project(client):
    work = task(client, kind="project")
    assert work["project_id"] is None
    assert client.get("/api/projects").json() == []


def test_empty_project_association_is_rejected(client):
    response = client.post("/api/tasks", json={"title": "Invalid association", "project_id": ""})
    assert response.status_code == 422, response.text
    assert client.get("/api/tasks").json() == []


def test_deleting_linked_task_keeps_project_and_cascades_only_association(client):
    container = project(client)
    work = task(client, project_id=container["id"])
    assert client.delete(f"/api/tasks/{work['id']}").status_code == 204
    assert client.get("/api/projects").json() == [container]
    assert client.get("/api/tasks").json() == []
    with client.app.state.session_factory() as db:
        assert db.get(TaskProject, ("tasks", work["id"])) is None
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []


def test_project_importance_context_and_task_hard_constraints(client):
    settings(client)
    low = project(client, name="Low", importance=1)
    high = project(client, name="High", importance=10, difficulty=10, end_date="2020-01-01", goals="Future semantic context")
    low_work = task(client, title="Low task", project_id=low["id"])
    high_work = task(client, title="High task", project_id=high["id"], deadline="2030-11-11T12:00:00-05:00")
    result = generate(client)
    placed = [item for item in result["blocks"] if item.get("task_id")]
    assert [item["task_id"] for item in placed] == [high_work["id"]]
    assert placed[0]["project_id"] == high["id"] and placed[0]["kind"] == "project"
    assert (placed[0]["end"], placed[0]["start"]) == ("2030-11-10T08:50:00-05:00", "2030-11-10T08:00:00-05:00")
    contexts = {item["id"]: item for item in result["project_context"]["projects"]}
    assert contexts[high["id"]]["goals"] == high["goals"]
    assert contexts[low["id"]]["task_ids"] == [low_work["id"]]
    # End date remains context; a task's own hard deadline still controls it.
    high_work["deadline"] = "2030-11-10T08:25:00-05:00"
    assert client.put(f"/api/tasks/{high_work['id']}", json=high_work).status_code == 200
    constrained = generate(client)
    assert not any(item.get("task_id") == high_work["id"] for item in constrained["blocks"])


@pytest.mark.parametrize("status", ["paused", "archived"])
def test_inactive_project_default_exclusion_explicit_inclusion_and_manual_summary(client, status):
    settings(client)
    container = project(client, status=status)
    work = task(client, project_id=container["id"])
    result = generate(client)
    assert result["blocks"] == [] and result["unallocated"] == []
    assert result["excluded_tasks"][0]["task_id"] == work["id"]
    assert result["status"] in ("optimal", "feasible")
    saved = client.put(f"/api/schedules/{result['id']}", json={"blocks": result["blocks"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["unallocated"] == []
    included = generate(client, include_inactive_projects=True)
    assert any(item.get("task_id") == work["id"] for item in included["blocks"])
    assert included["include_inactive_projects"] is True


def test_project_edit_and_link_changes_invalidate_saved_plan_preserve_blocks(client):
    settings(client)
    container = project(client)
    work = task(client, project_id=container["id"])
    result = generate(client)
    edited = {**writable(container), "status": "paused", "importance": 9.5}
    assert client.put(f"/api/projects/{container['id']}", json=edited).status_code == 200
    saved = client.get("/api/schedules").json()[0]
    assert saved["projects_dirty"] and saved["status"] == "stale"
    assert saved["blocks"] == result["blocks"]
    assert client.put(f"/api/schedules/{saved['id']}", json={"blocks": saved["blocks"]}).status_code == 409
    fresh = generate(client)
    assert not fresh.get("projects_dirty")
    assert not any(item.get("task_id") == work["id"] for item in fresh["blocks"])
    assert client.put(f"/api/tasks/{work['id']}", json={**work, "project_id": None}).status_code == 200
    assert client.get("/api/schedules").json()[0]["projects_dirty"]


def test_legacy_migration_preserves_work_original_snapshot_and_schedule(tmp_path):
    path = tmp_path / "legacy.sqlite"
    engine, factory = build_database(path)
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0002_activity_calendar")
    original = {"id": "old-project", "title": "Vector legacy", "kind": "project", "duration_minutes": 180, "remaining_minutes": 125, "priority": 4, "deadline": "2030-12-01T12:00:00-05:00", "hard_deadline": True, "splittable": True, "min_session_minutes": 25, "max_session_minutes": 60, "dependencies": ["old-academic"], "location_id": None, "status": "in_progress", "preferred_start": "09:00", "preferred_end": "19:00", "notes": "All original details", "future_legacy_field": {"do_not_lose": True}}
    academic = {"id": "old-academic", "title": "Prerequisite", "kind": "academic", "duration_minutes": 30, "remaining_minutes": 0, "status": "completed"}
    old_schedule = {"id": "saved", "date": "2030-11-10", "status": "feasible", "blocks": [{"id": "historical", "kind": "project", "task_id": "old-project", "status": "completed", "start": "2030-11-10T08:00:00-05:00", "end": "2030-11-10T08:55:00-05:00"}]}
    with factory() as db:
        db.add(Configuration(id="settings", payload=Settings().model_dump(mode="json")))
        db.add(Entity(collection="tasks", id=original["id"], payload=original))
        db.add(Entity(collection="tasks", id=academic["id"], payload=academic))
        db.add(Schedule(id="saved", date="2030-11-10", payload=deepcopy(old_schedule)))
        db.commit()
    migrate(engine)
    migrate(engine)
    with factory() as db:
        assert db.get(Entity, ("tasks", original["id"])).payload == {**original, "project_id": original["id"]}
        assert db.get(Entity, ("tasks", academic["id"])).payload == academic
        container = db.get(Project, original["id"])
        assert container.legacy_snapshot == original
        assert container.payload["description"] == original["notes"]
        assert container.payload["importance"] == 8
        assert container.payload["difficulty"] == 5 and container.payload["contributors"] == 1
        assert db.get(TaskProject, ("tasks", original["id"])).project_id == original["id"]
        assert db.get(Schedule, "saved").payload == old_schedule
        assert len(list(db.scalars(select(Project)))) == 1
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()
