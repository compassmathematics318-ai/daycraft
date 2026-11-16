"""Evidence gates and untrusted manual payloads for flexible preferred venues."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from backend.app import suitability
from backend.app.database import Schedule
from backend.app.main import create_app


def test_activity_inference_never_infers_place_facts():
    places = {
        "selected": {"name": "PAC"},
        "named": {"name": "Perfect Gym", "notes": "fitness training", "access_confirmed": True},
        "no_access": {"verified_capabilities": ["fitness_training"]},
        "verified": {"verified_capabilities": ["fitness_training"], "access_confirmed": True},
    }
    task = {"title": "Gym", "location_mode": "preferred", "location_id": "selected"}
    result = suitability.enrich(task, places)
    assert suitability.candidate_ids(result) == ["selected", "verified"]
    evidence = result["location_suitability"]
    assert evidence["source"] == "inferred"
    assert evidence["requirements"] == ["fitness_training"]
    assert all(item["confidence"] == "high" and item["evidence"] for item in evidence["candidates"])
    assert suitability.candidate_ids(suitability.enrich({**task, "location_mode": "required"}, places)) == ["selected"]


@pytest.mark.parametrize("title,description,project", [
    ("Errands", "", {}),
    ("Gym", "Requires specific equipment", {}),
    ("Study", "No quiet space", {}),
    ("Study", "", {"description": "Laboratory equipment needed"}),
    ("Study and swimming", "", {}),
    ("Exercise 3", "Math problem set", {}),
    ("Plan gym membership", "", {}),
    ("Write gym workout plan", "", {}),
    ("Reading", "Use a microscope", {}),
    ("Studying", "", {"goals": "Experiments with laboratory instruments"}),
])
def test_ambiguous_specialized_and_conditional_context_stays_selected(title, description, project):
    places = {"a": {}, "b": {"verified_capabilities": list(suitability.CAPABILITIES), "access_confirmed": True}}
    task = {"title": title, "description": description, "project": project, "location_id": "a", "location_mode": "preferred"}
    result = suitability.enrich(task, places)
    assert suitability.candidate_ids(result) == ["a"]
    assert result["location_suitability"]["confidence"] == "unknown"
    assert result["location_suitability"]["limitation"]


def test_physical_exercise_context_and_online_study_needs():
    assert suitability.infer_requirements({"title": "Exercise", "task_type": "wellness"})[0] == ["fitness_training"]
    assert suitability.infer_requirements({"title": "Study online coursework"})[0] == ["quiet_workspace", "desk", "wifi"]


def test_complete_explicit_custom_requirements_and_conflicting_whitelist():
    places = {"a": {}, "b": {"verified_capabilities": ["desk"], "access_confirmed": True},
              "c": {"verified_capabilities": ["ceramics_wheel"], "access_confirmed": True}}
    task = {"title": "Special project", "location_mode": "preferred", "location_id": "a",
            "location_requirements": ["ceramics_wheel"], "allow_alternative_locations": True, "alternative_location_ids": ["b"]}
    result = suitability.enrich(task, places)
    assert suitability.candidate_ids(result) == ["a", "c"]
    assert result["location_suitability"]["source"] == "explicit"
    assert "confirmed alternative" in result["location_suitability"]["limitation"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.db"))
    with TestClient(create_app(tmp_path / "suitability.db")) as value:
        yield value


def post(client, collection, payload):
    result = client.post("/api/" + collection, json=payload)
    assert result.status_code in (200, 201), result.text
    return result.json()


def test_requirements_propagate_and_old_clients_preserve_verified_facts(client):
    place = post(client, "locations", {"name": "Room", "lat": 43.4, "lon": -80.5,
                 "verified_capabilities": ["Quiet Workspace", "desk"], "access_confirmed": True, "verification_notes": "Checked by me"})
    assert place["verified_capabilities"] == ["quiet_workspace", "desk"]
    older = {key: item for key, item in place.items() if key not in {"verified_capabilities", "access_confirmed", "verification_notes"}}
    response = client.put(f"/api/locations/{place['id']}", json=older)
    assert response.status_code == 200, response.text
    assert response.json()["access_confirmed"] is True
    assert response.json()["verified_capabilities"] == place["verified_capabilities"]
    legacy = post(client, "tasks", {"title": "Study", "location_id": place["id"], "location_mode": "preferred", "location_requirements": ["desk"]})
    definition = next(item for item in client.get("/api/task-definitions").json() if item["id"] == legacy["id"])
    assert definition["location_requirements"] == ["desk"]
    week = post(client, "task-weeks", {"task_definition_id": legacy["id"], "week_start": "2026-11-15", "overrides": {"location_requirements": ["printer"]}})
    assert week["effective_definition"]["location_requirements"] == ["printer"]
    overview = client.get("/api/location-overview?week_start=2026-11-15").json()
    task_ref = next(ref for saved_place in overview["locations"] for ref in saved_place["references"] if ref["entity_id"] == legacy["id"])
    assert task_ref["edit_target"]["assignment_id"] == week["id"]
    activity = post(client, "activities", {"title": "Research", "category": "commitment", "subtype": "Personal", "location_id": place["id"], "location_mode": "preferred", "location_requirements": ["desk"]})
    event = post(client, "occurrences", {"activity_id": activity["id"], "start": "2026-11-16T09:00:00-05:00", "end": "2026-11-16T10:00:00-05:00", "location_override": {"location_id": place["id"], "location_mode": "preferred", "location_requirements": ["printer"]}})
    assert event["location_override"]["location_requirements"] == ["printer"]
    assert client.post("/api/task-definitions", json={"title": "Forge", "location_suitability": {"candidates": []}}).status_code == 422
    assert client.post("/api/locations", json={"name": "Bad", "lat": 0, "lon": 0, "verified_capabilities": ["<script>"]}).status_code == 422


def test_forged_manual_candidate_evidence_is_rebuilt(client):
    selected, other = [post(client, "locations", {"name": name, "lat": 43.4, "lon": -80.5}) for name in ("PAC", "MC")]
    block = {"id": "session", "title": "Gym", "kind": "personal", "location_id": selected["id"], "location_mode": "preferred",
             "resolved_location_id": selected["id"], "start": "2026-11-16T10:00:00-05:00", "end": "2026-11-16T11:00:00-05:00"}
    with client.app.state.session_factory() as db:
        db.add(Schedule(id="manual", date="2026-11-16", payload={"id": "manual", "date": "2026-11-16", "status": "optimal", "location_intelligence_version": suitability.INTELLIGENCE_VERSION, "blocks": [block]}))
        db.commit()
    forged = deepcopy(block)
    forged["resolved_location_id"] = other["id"]
    forged["location_suitability"] = {"candidates": [{"location_id": other["id"], "source": "verified_capabilities"}]}
    response = client.put("/api/schedules/manual", json={"blocks": [forged]})
    assert response.status_code == 409, response.text
    assert client.get("/api/schedules?date=2026-11-16").json()[0]["blocks"][0]["resolved_location_id"] == selected["id"]


def test_generated_weekly_work_uses_verified_venue_and_revocation_requires_regeneration(client):
    selected, actual = [post(client, "locations", {"name": name, "lat": 43.4, "lon": -80.5}) for name in ("Preferred", "Confirmed facility")]
    confirmed = {**actual, "verified_capabilities": ["fitness_training"], "access_confirmed": True,
                 "verification_notes": "My normal workout is supported; I can enter."}
    assert client.put(f"/api/locations/{actual['id']}", json=confirmed).status_code == 200
    settings = client.get("/api/state").json()["settings"]
    settings.update(work_start="10:00", work_end="11:00", meals=[], focus_minutes=60, break_minutes=0)
    assert client.put("/api/settings", json=settings).status_code == 200
    post(client, "classes", {"title": "Prior appointment", "class_type": "Personal", "date": "2026-11-16",
         "start_time": "09:00", "end_time": "10:00", "location_id": actual["id"]})
    definition = post(client, "task-definitions", {"title": "Gym", "session_minutes": 60, "location_id": selected["id"], "location_mode": "preferred"})
    post(client, "task-weeks", {"task_definition_id": definition["id"], "week_start": "2026-11-15"})
    generated = post(client, "schedules/generate", {"date": "2026-11-16", "mode": "balanced"})
    work = [item for item in generated["blocks"] if item.get("task_definition_id") == definition["id"]]
    assert len(work) == 1, generated
    assert work[0]["location_id"] == selected["id"]
    assert work[0]["resolved_location_id"] == actual["id"]
    evidence = work[0]["location_suitability"]
    actual_evidence = next(item for item in evidence["candidates"] if item["location_id"] == actual["id"])
    assert actual_evidence["source"] == "verified_capabilities"
    assert "user confirmed access" in actual_evidence["evidence"]
    assert "Confirmed facility" in client.get(f"/api/schedules/{generated['id']}/export").text
    forged = deepcopy(work[0])
    forged["location_suitability"] = {"candidates": [{"location_id": "made-up"}]}
    roundtrip = client.put(f"/api/schedules/{generated['id']}", json={"blocks": [forged if item["id"] == forged["id"] else item for item in generated["blocks"]]})
    assert roundtrip.status_code == 200, roundtrip.text
    assert "made-up" not in str(roundtrip.json())
    assert client.put(f"/api/locations/{actual['id']}", json={**confirmed, "access_confirmed": False}).status_code == 200
    saved = client.get("/api/schedules?date=2026-11-16").json()[0]
    assert saved["status"] == "stale"
    assert saved["blocks"] == roundtrip.json()["blocks"]
    assert client.get(f"/api/schedules/{generated['id']}/export").status_code == 409


def test_obsolete_pending_preferred_plan_is_flagged_without_rewriting_history(client):
    place = post(client, "locations", {"name": "Home", "lat": 43.4, "lon": -80.5})
    block = {"id": "old", "title": "Gym", "kind": "personal", "location_id": place["id"], "location_mode": "preferred",
             "resolved_location_id": place["id"], "start": "2026-11-16T10:00:00-05:00", "end": "2026-11-16T11:00:00-05:00"}
    original = {"id": "old", "date": "2026-11-16", "status": "optimal", "blocks": [block]}
    with client.app.state.session_factory() as db:
        db.add(Schedule(id="old", date="2026-11-16", payload=deepcopy(original)))
        db.commit()
    viewed = client.get("/api/schedules?date=2026-11-16").json()[0]
    assert viewed["status"] == "stale" and viewed["needs_regeneration"]
    assert viewed["blocks"] == original["blocks"]
    with client.app.state.session_factory() as db:
        assert db.get(Schedule, "old").payload == original


@pytest.mark.parametrize("actual_details", [{"building": "Annex", "room": "101", "floor": "1", "entrance": "East"}, {}])
def test_actual_alternative_export_and_map_never_reuse_primary_room(client, actual_details):
    primary = post(client, "locations", {"name": "PAC", "lat": 43.4, "lon": -80.5, "building": "PAC", "room": "PAC-ONLY"})
    actual = post(client, "locations", {"name": "Fitness Annex", "lat": 43.4, "lon": -80.5, **actual_details})
    block = {"id": "actual-visit", "title": "Workout", "kind": "personal", "location_id": primary["id"], "location_mode": "preferred",
             "resolved_location_id": actual["id"], "room": "PAC-ONLY", "building": "PAC-BUILDING-ONLY", "locked": True,
             "start": "2026-11-16T10:00:00-05:00", "end": "2026-11-16T11:00:00-05:00"}
    original = {"id": "actual-visit", "date": "2026-11-16", "status": "optimal", "blocks": [block]}
    with client.app.state.session_factory() as db:
        db.add(Schedule(id="actual-visit", date="2026-11-16", payload=deepcopy(original)))
        db.commit()
    for fmt in ("ics", "csv"):
        response = client.get(f"/api/schedules/actual-visit/export?format={fmt}")
        assert response.status_code == 200, response.text
        assert "Fitness Annex" in response.text
        assert "PAC-ONLY" not in response.text
        assert "PAC-BUILDING-ONLY" not in response.text
        assert ("Room 101" in response.text) is bool(actual_details)
    overview = client.get("/api/location-overview?week_start=2026-11-15").json()
    actual_place = next(item for item in overview["locations"] if item["id"] == actual["id"])
    group = actual_place["references"][0]
    for displayed in [group, *group["placements"], *group["occurrences"]]:
        assert displayed["room"] == actual_details.get("room", "")
        assert displayed["building"] == actual_details.get("building", "")
        assert displayed["floor"] == actual_details.get("floor", "")
        assert displayed["entrance"] == actual_details.get("entrance", "")
    saved = client.get("/api/schedules?date=2026-11-16").json()[0]
    assert saved["blocks"][0]["room"] == "PAC-ONLY"
    with client.app.state.session_factory() as db:
        assert db.get(Schedule, "actual-visit").payload == original


@pytest.mark.parametrize("category,subtype", [("class", "Lecture"), ("commitment", "Personal"), ("assessment", None)])
def test_fixed_calendar_map_overlays_actual_saved_venue_once_and_ignores_stale_future_plan(client, category, subtype):
    pac = post(client, "locations", {"name": "PAC", "lat": 43.4, "lon": -80.5, "room": "PAC-ONLY"})
    annex = post(client, "locations", {"name": "Annex", "lat": 43.4, "lon": -80.5, "room": "101",
                 "verified_capabilities": ["fitness_training"], "access_confirmed": True})
    settings = client.get("/api/state").json()["settings"]
    settings.update(work_start="08:00", work_end="09:00", meals=[], break_minutes=0)
    assert client.put("/api/settings", json=settings).status_code == 200
    before = post(client, "activities", {"title": "Before", "category": "commitment", "subtype": "Personal", "location_id": annex["id"]})
    post(client, "occurrences", {"activity_id": before["id"], "start": "2026-11-16T08:00:00-05:00", "end": "2026-11-16T08:25:00-05:00"})
    times = {"start": "2026-11-16T08:30:00-05:00", "end": "2026-11-16T09:00:00-05:00"}
    assessment = {"assessment_start": times["start"], "assessment_end": times["end"]} if category == "assessment" else {}
    activity = post(client, "activities", {"title": "Fitness attendance", "category": category, "subtype": subtype,
                    "location_id": pac["id"], "location_mode": "preferred", "location_requirements": ["fitness_training"], "room": "PAC-ONLY", **assessment})
    if category != "assessment":
        event = post(client, "occurrences", {"activity_id": activity["id"], **times})
    else:
        event = next(item for item in client.get("/api/calendar?week_start=2026-11-15").json()["occurrences"] if item["activity_id"] == activity["id"])
    result = post(client, "schedules/generate", {"date": "2026-11-16", "mode": "balanced"})
    block = next(item for item in result["blocks"] if item.get("activity_id") == activity["id"])
    assert block["resolved_location_id"] == annex["id"], result
    assert block["location_id"] == pac["id"] and block["room"] == "PAC-ONLY"

    def dated_visits():
        overview = client.get("/api/location-overview?week_start=2026-11-15").json()
        return [(place, ref, visit) for place in overview["locations"] for ref in place["references"]
                for visit in ref["occurrences"] if visit["entity_id"] == event["id"]]

    visits = dated_visits()
    assert len(visits) == 1
    place, group, visit = visits[0]
    assert place["id"] == annex["id"] and group["room"] == "101" and visit["room"] == "101"
    assert visit["source"] == "occurrence"
    assert visit["edit_target"] == {"kind": "occurrence", "id": event["id"], "activity_id": activity["id"]}
    source = next(item for item in client.get("/api/activities").json() if item["id"] == activity["id"])
    assert source["location_id"] == pac["id"] and source["room"] == "PAC-ONLY"
    overview = client.get("/api/location-overview?week_start=2026-11-15").json()
    primary_place = next(item for item in overview["locations"] if item["id"] == pac["id"])
    assert any(ref["entity_id"] == activity["id"] and ref["occurrence_count"] == 0 for ref in primary_place["references"])
    authoritative = next(item for item in client.get("/api/calendar?week_start=2026-11-15").json()["occurrences"] if item["id"] == event["id"])
    assert authoritative["location_override"] is None
    with client.app.state.session_factory() as db:
        row = db.get(Schedule, result["id"])
        row.payload = {**row.payload, "status": "stale", "locations_dirty": True}
        db.commit()
    visits = dated_visits()
    assert len(visits) == 1 and visits[0][0]["id"] == pac["id"]
    with client.app.state.session_factory() as db:
        row = db.get(Schedule, result["id"])
        row.payload = {**row.payload, "blocks": [{**item, "status": "completed"} if item["id"] == block["id"] else item for item in row.payload["blocks"]]}
        db.commit()
    visits = dated_visits()
    assert len(visits) == 1 and visits[0][0]["id"] == annex["id"]
