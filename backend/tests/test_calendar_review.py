"""Independent adversarial calendar API tests; each test owns an isolated DB."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.database import Schedule


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.db"))
    with TestClient(create_app(tmp_path / "review.db")) as value:
        yield value


def activity(client, **changes):
    payload = {"title": "Review class", "category": "class", "subtype": "Lecture", "description": "Saved context", **changes}
    response = client.post("/api/activities", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def place(client, item, start="2026-11-10T10:00:00-05:00", end="2026-11-10T11:00:00-05:00"):
    response = client.post("/api/occurrences", json={"activity_id": item["id"], "start": start, "end": end})
    assert response.status_code == 201, response.text
    return response.json()


def calendar(client, week="2026-11-08"):
    response = client.get(f"/api/calendar?week_start={week}")
    assert response.status_code == 200, response.text
    return response.json()


def update_payload(item, **changes):
    return {key: value for key, value in {**item, **changes}.items() if key not in {"id", "legacy_class_id"}}


def test_review_unplaced_definition_has_no_calendar_or_optimization_time(client):
    item = activity(client)
    assert calendar(client)["occurrences"] == []
    result = client.post("/api/schedules/generate", json={"date": "2026-11-10", "mode": "balanced"})
    assert result.status_code == 200, result.text
    assert not any(block.get("activity_id") == item["id"] for block in result.json()["blocks"])


def test_review_adjacent_placements_allowed_but_actual_overlap_rejected_atomically(client):
    item = activity(client)
    original = place(client, item)
    place(client, item, "2026-11-10T11:00:00-05:00", "2026-11-10T12:00:00-05:00")
    response = client.put(f"/api/occurrences/{original['id']}", json={"activity_id": item["id"], "start": "2026-11-10T10:30:00-05:00", "end": "2026-11-10T11:30:00-05:00"})
    assert response.status_code == 409, response.text
    saved = next(x for x in calendar(client)["occurrences"] if x["id"] == original["id"])
    assert datetime.fromisoformat(saved["start"].replace("Z", "+00:00")) == datetime.fromisoformat(original["start"].replace("Z", "+00:00"))


def test_review_assessment_update_conflict_keeps_authoritative_times(client):
    assessment = activity(client, title="Midterm", category="assessment", subtype=None, assessment_start="2026-11-10T13:00:00-05:00", assessment_end="2026-11-10T14:00:00-05:00", course="CS135")
    other = activity(client, title="Meeting", category="commitment", subtype="Groupwork")
    place(client, other, "2026-11-10T15:00:00-05:00", "2026-11-10T16:00:00-05:00")
    before = next(x for x in calendar(client)["occurrences"] if x["activity_id"] == assessment["id"])
    response = client.put(f"/api/activities/{assessment['id']}", json=update_payload(assessment, assessment_start="2026-11-10T15:30:00-05:00", assessment_end="2026-11-10T16:30:00-05:00"))
    assert response.status_code == 409, response.text
    after = next(x for x in calendar(client)["occurrences"] if x["activity_id"] == assessment["id"])
    assert before == after
    saved = next(x for x in client.get("/api/activities").json() if x["id"] == assessment["id"])
    assert datetime.fromisoformat(saved["assessment_start"].replace("Z", "+00:00")) == datetime.fromisoformat(before["start"].replace("Z", "+00:00"))


def test_review_occurrence_cannot_be_reassociated_or_reference_missing_definition(client):
    first, second = activity(client), activity(client, title="Other")
    occurrence = place(client, first)
    response = client.put(f"/api/occurrences/{occurrence['id']}", json={"activity_id": second["id"], "start": occurrence["start"], "end": occurrence["end"]})
    assert response.status_code in (409, 422), response.text
    response = client.post("/api/occurrences", json={"activity_id": "missing", "start": occurrence["start"], "end": occurrence["end"]})
    assert response.status_code in (404, 422), response.text


def test_review_inclusive_bounds_and_subminute_precision(client):
    item = activity(client, start_date="2026-11-10", end_date="2026-11-10")
    place(client, item, "2026-11-10T23:00:00-05:00", "2026-11-11T00:00:00-05:00")
    for start, end in [("2026-11-11T00:00:00-05:00", "2026-11-11T01:00:00-05:00"), ("2026-11-10T10:00:00.001-05:00", "2026-11-10T11:00:00-05:00"), ("2026-11-10T10:01:00-05:00", "2026-11-10T11:00:00-05:00"), ("2026-11-10T10:00:00", "2026-11-10T11:00:00")]:
        response = client.post("/api/occurrences", json={"activity_id": item["id"], "start": start, "end": end})
        assert response.status_code in (409, 422), response.text


def test_review_copy_dst_keeps_local_clock_and_never_duplicates_assessments(client):
    item = activity(client, category="commitment", subtype="Personal")
    place(client, item, "2026-10-25T10:00:00-04:00", "2026-10-25T11:00:00-04:00")
    assessment = activity(client, title="Exam", category="assessment", subtype=None, assessment_start="2026-10-25T12:00:00-04:00", assessment_end="2026-10-25T13:00:00-04:00")
    first = client.post("/api/calendar/copy-previous-week", json={"week_start": "2026-11-01"})
    assert first.status_code == 200, first.text
    target = calendar(client, "2026-11-01")["occurrences"]
    assert len(target) == 1 and target[0]["activity_id"] == item["id"]
    assert datetime.fromisoformat(target[0]["start"].replace("Z", "+00:00")) == datetime(2026, 11, 1, 15, tzinfo=timezone.utc)
    assert not any(x["activity_id"] == assessment["id"] for x in target)
    second = client.post("/api/calendar/copy-previous-week", json={"week_start": "2026-11-01"}).json()
    assert second["created"] == 0 and second["duplicates"] >= 1


def test_review_definition_deletion_cascades_occurrences_but_keeps_other_definitions(client):
    removed, retained = activity(client), activity(client, title="Keep")
    place(client, removed)
    place(client, retained, "2026-11-10T14:00:00-05:00", "2026-11-10T15:00:00-05:00")
    assert client.delete(f"/api/activities/{removed['id']}").status_code == 204
    assert [x["activity_id"] for x in calendar(client)["occurrences"]] == [retained["id"]]


def test_review_new_calendar_change_marks_saved_plan_stale(client):
    item = activity(client)
    place(client, item)
    generated = client.post("/api/schedules/generate", json={"date": "2026-11-10", "mode": "balanced"}).json()
    assert generated["status"] in ("optimal", "feasible")
    place(client, item, "2026-11-10T14:00:00-05:00", "2026-11-10T15:00:00-05:00")
    saved = client.get("/api/schedules?date=2026-11-10").json()[0]
    assert saved["status"] == "stale"
    assert any("regenerat" in str(message).lower() for message in saved["conflicts"])


def test_review_legacy_individual_edits_preserve_remaining_series(client):
    response = client.post("/api/classes", json={"title": "Legacy tutorial", "class_type": "Tutorial", "weekdays": [0, 2], "start_time": "09:00", "end_time": "10:00", "start_date": "2026-11-09", "end_date": "2026-12-01", "exceptions": []})
    assert response.status_code == 201, response.text
    old = response.json()
    original = calendar(client)["occurrences"]
    assert len(original) == 2
    selected = original[0]
    response = client.put(f"/api/occurrences/{selected['id']}", json={"activity_id": selected["activity_id"], "start": "2026-11-09T10:05:00-05:00", "end": "2026-11-09T11:05:00-05:00"})
    assert response.status_code == 200, response.text
    moved = response.json()
    assert moved["source"] == "manual" and moved["activity_id"] == selected["activity_id"]
    current = calendar(client)["occurrences"]
    assert len(current) == 2 and selected["id"] not in {event["id"] for event in current}
    assert client.delete(f"/api/occurrences/{original[1]['id']}").status_code == 204
    assert calendar(client)["occurrences"] == [moved]
    saved_legacy = next(item for item in client.get("/api/classes").json() if item["id"] == old["id"])
    assert saved_legacy["exceptions"] == ["2026-11-09", "2026-11-11"]
    following = calendar(client, "2026-11-15")["occurrences"]
    assert len(following) == 2 and all(event["source"] == "legacy" for event in following)


def test_review_three_categories_and_occurrences_survive_application_recreation(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "cache.db"))
    path = tmp_path / "restart.db"
    with TestClient(create_app(path)) as first:
        cls = activity(first, description="Persistent lecture context")
        meeting = activity(first, title="Team review", category="commitment", subtype="Groupwork")
        exam = activity(first, title="Final", category="assessment", subtype=None, assessment_start="2026-11-10T15:00:00-05:00", assessment_end="2026-11-10T16:00:00-05:00")
        place(first, cls)
        place(first, meeting, "2026-11-10T13:00:00-05:00", "2026-11-10T14:00:00-05:00")
        before = calendar(first)
    with TestClient(create_app(path)) as restarted:
        after = calendar(restarted)
        assert after == before
        assert {item["id"] for item in after["activities"]} == {cls["id"], meeting["id"], exam["id"]}
        assert len(after["occurrences"]) == 3


def test_review_legacy_started_history_does_not_hide_additional_manual_meeting(client):
    legacy = client.post("/api/classes", json={"title": "Old course", "date": "2026-11-10", "start_time": "09:00", "end_time": "10:00"}).json()
    saved = client.post("/api/schedules/generate", json={"date": "2026-11-10", "mode": "balanced"}).json()
    old_block = next(item for item in saved["blocks"] if item["kind"] == "class")
    old_block.update(status="completed", class_id=legacy["id"])
    for field in ("activity_id", "occurrence_id", "category", "subtype", "description", "course", "building", "room", "actual_start", "actual_end", "calendar_source"):
        old_block.pop(field, None)
    with client.app.state.session_factory() as db:
        db.get(Schedule, saved["id"]).payload = saved
        db.commit()
    mirror = next(item for item in client.get("/api/activities").json() if item["legacy_class_id"] == legacy["id"])
    extra = place(client, mirror, "2026-11-10T14:00:00-05:00", "2026-11-10T15:00:00-05:00")
    regenerated = client.post("/api/schedules/generate", json={"date": "2026-11-10", "mode": "balanced"}).json()
    assert any(item.get("occurrence_id") == extra["id"] for item in regenerated["blocks"]), regenerated
    assert len([item for item in regenerated["blocks"] if item["kind"] == "class"]) == 2
