"""Calendar occurrences exercise the real existing CP-SAT scheduling engine."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from backend.app.calendar_scheduler import fixed_blocks_for_day
from backend.app.scheduler import generate_schedule, validate_blocks

DAY = "2026-11-10"
SETTINGS = {"timezone": "America/Toronto", "wake_time": "07:00", "sleep_time": "23:00",
            "work_start": "08:00", "work_end": "22:00", "break_minutes": 10,
            "travel_buffer_minutes": 5, "focus_minutes": 50, "default_location_id": "home",
            "meals": [], "solver_seconds": 2}


def activity(id="math", **extra):
    return {"id": id, "title": "MATH147", "category": "class", "subtype": "Lecture",
            "description": "Sequences and proofs; bring lecture notes.", "location_id": "home",
            "building": "MC", "room": "2066", "course": "MATH147", **extra}


def occurrence(id="lecture", activity_id="math", start="09:00", end="10:00", day=DAY, **extra):
    return {"id": id, "activity_id": activity_id, "start": f"{day}T{start}:00-05:00",
            "end": f"{day}T{end}:00-05:00", "source": "manual", **extra}


def task(**extra):
    return {"id": "assignment", "title": "Problem set", "kind": "academic", "duration_minutes": 120,
            "remaining_minutes": 120, "priority": 5, "splittable": True, "min_session_minutes": 25,
            "max_session_minutes": 60, "dependencies": [], "status": "todo", "location_id": "home", **extra}


def elapsed(block):
    return round((datetime.fromisoformat(block["end"]).astimezone(timezone.utc) - datetime.fromisoformat(block["start"]).astimezone(timezone.utc)).total_seconds() / 60)


def generate(activities, occurrences, tasks=None, day=DAY, settings=None):
    preferences = settings or SETTINGS
    fixed = fixed_blocks_for_day(day, preferences, activities, occurrences)
    return generate_schedule(day, preferences, [], tasks or [], fixed, lambda a, b: 15)


def test_definition_without_placement_does_not_reserve_time():
    assert fixed_blocks_for_day(DAY, SETTINGS, [activity()], []) == []


def test_linked_project_context_is_metadata_not_an_additional_calendar_event():
    relation = {"kind": "project", "id": "vector"}
    context = {**relation, "title": "Vector", "importance": 9, "status": "active",
               "description": "Build the prototype", "deadline": "2026-11-20"}
    meeting = activity(category="commitment", subtype="Groupwork", related_entity=relation,
                       related_entity_context=context)
    assert fixed_blocks_for_day(DAY, SETTINGS, [meeting], []) == []
    fixed = fixed_blocks_for_day(DAY, SETTINGS, [meeting], [occurrence()])
    assert len(fixed) == 1
    assert fixed[0]["related_entity_context"] == context
    result = generate([meeting], [occurrence()])
    linked = [block for block in result["blocks"] if block.get("activity_id")]
    assert len(linked) == 1 and linked[0]["related_entity"] == relation
    assert linked[0]["start"] == f"{DAY}T09:00:00-05:00"
    assert linked[0]["end"] == f"{DAY}T10:00:00-05:00"
    fixed[0]["related_entity_context"]["title"] = "Changed output"
    assert context["title"] == "Vector"
    result = generate([activity()], [], [task()])
    assert result["status"] == "optimal"
    assert sum(elapsed(b) for b in result["blocks"] if b.get("task_id")) == 120
    assert not any(b["kind"] == "class" for b in result["blocks"])


def test_calendar_suitability_reaches_fixed_interval_and_actual_rationale():
    suitability = {"requirements": ["quiet"], "source": "explicit", "confidence": "high",
                   "candidates": [{"location_id": "library", "source": "selected", "confidence": "high", "evidence": "Selected venue"},
                                  {"location_id": "other-library", "source": "verified_capabilities", "confidence": "high", "evidence": "Verified quiet space"}],
                   "limitation": ""}
    source = activity(location_id="library", location_mode="preferred", location_requirements=["quiet"],
                      location_suitability=suitability)
    fixed = fixed_blocks_for_day(DAY, SETTINGS, [source], [occurrence()])
    assert fixed[0]["location_suitability"] == suitability
    assert fixed[0]["location_requirements"] == ["quiet"]
    fixed[0]["location_suitability"]["limitation"] = "Copied independently"
    assert source["location_suitability"]["limitation"] == ""


def test_calendar_adapter_retains_permission_and_occurrence_override_is_authoritative():
    source = activity(location_id="PAC", location_mode="preferred", allow_alternative_locations=True,
                      alternative_location_ids=["other-gym"])
    fixed = fixed_blocks_for_day(DAY, SETTINGS, [source], [occurrence()])
    assert fixed[0]["allow_alternative_locations"]
    assert fixed[0]["alternative_location_ids"] == ["other-gym"]
    override = {"location_id": "MC", "location_mode": "required"}
    overridden = fixed_blocks_for_day(DAY, SETTINGS, [source], [occurrence(location_override=override)])
    assert overridden[0]["location_id"] == "MC"
    assert not overridden[0]["allow_alternative_locations"]
    assert overridden[0]["alternative_location_ids"] == []


def test_multiple_occurrences_keep_their_identity_and_metadata():
    definitions = [activity()]
    events = [occurrence(), occurrence("tutorial", start="14:00", end="15:00")]
    original = deepcopy((definitions, events))
    fixed = fixed_blocks_for_day(DAY, SETTINGS, definitions, events)
    assert [b["occurrence_id"] for b in fixed] == ["lecture", "tutorial"]
    assert len({b["id"] for b in fixed}) == 2
    assert all(b["locked"] and b["kind"] == "class" and b["class_id"].startswith("occurrence:") for b in fixed)
    assert fixed[0]["description"] == definitions[0]["description"]
    assert fixed[0]["course"] == "MATH147" and fixed[0]["room"] == "2066"
    assert (definitions, events) == original
    assert fixed_blocks_for_day(DAY, SETTINGS, definitions, events) == fixed


def test_all_categories_are_fixed_constraints_for_real_optimizer():
    definitions = [activity(), activity("exam", title="CS135 Midterm", category="assessment", subtype=None),
                   activity("lab", title="Reality Labs", category="commitment", subtype="Groupwork")]
    events = [occurrence(), occurrence("midterm", "exam", "11:00", "12:30", source="assessment"),
              occurrence("session", "lab", "15:00", "16:00")]
    work = [task()]
    result = generate(definitions, events, work)
    assert result["status"] == "optimal", result["conflicts"]
    assert {b.get("category") for b in result["blocks"] if b["kind"] == "class"} == {"class", "assessment", "commitment"}
    assert len([b for b in result["blocks"] if b["kind"] == "class"]) == 3
    assert sum(elapsed(b) for b in result["blocks"] if b.get("task_id")) == 120
    assert not validate_blocks(result["blocks"], SETTINGS, lambda a, b: 15, work)


def test_calendar_locations_keep_travel_hard_constraint():
    definitions = [activity(location_id="A"), activity("exam", title="Midterm", category="assessment", location_id="B")]
    events = [occurrence(), occurrence("exam", "exam", "10:05", "11:00", source="assessment")]
    result = generate(definitions, events, [task()])
    assert result["status"] == "infeasible"
    assert result["solver_status"] == "INFEASIBLE"


def test_calendar_leaves_best_feasible_partial_task_work():
    preferences = {**SETTINGS, "work_start": "08:00", "work_end": "10:00"}
    result = generate([activity()], [occurrence()], [task()], settings=preferences)
    assert result["status"] == "partial"
    assert sum(elapsed(b) for b in result["blocks"] if b.get("task_id")) == 50
    assert result["unallocated"][0]["minutes"] == 70
    assert not result["conflicts"]


def test_new_fixed_metadata_survives_solver_and_started_work_preservation():
    definitions, events = [activity(category="assessment", subtype=None)], [occurrence(source="assessment")]
    first = generate(definitions, events, [task()])
    protected = next(b for b in first["blocks"] if b["kind"] == "class")
    protected["status"] = "completed"
    # Backend removes the corresponding new fixed block when preserving history.
    second = generate_schedule(DAY, SETTINGS, [], [task()], [protected], lambda a, b: 15)
    preserved = [b for b in second["blocks"] if b.get("occurrence_id") == "lecture"]
    assert len(preserved) == 1 and preserved[0]["status"] == "completed"
    assert preserved[0]["description"] == definitions[0]["description"]
    assert preserved[0]["actual_start"] == events[0]["start"]


def test_only_selected_date_is_consumed_even_with_same_definition():
    events = [occurrence(), occurrence("wed", day="2026-11-11")]
    assert [b["occurrence_id"] for b in fixed_blocks_for_day(DAY, SETTINGS, [activity()], events)] == ["lecture"]
    assert [b["occurrence_id"] for b in fixed_blocks_for_day("2026-11-11", SETTINGS, [activity()], events)] == ["wed"]


def test_cross_midnight_assessment_is_not_lost_on_either_day():
    event = occurrence(start="22:00", end="02:00")
    event["end"] = "2026-11-11T02:00:00-05:00"
    first = fixed_blocks_for_day(DAY, SETTINGS, [activity(category="assessment")], [event])
    second = fixed_blocks_for_day("2026-11-11", SETTINGS, [activity(category="assessment")], [event])
    assert elapsed(first[0]) == elapsed(second[0]) == 120
    assert first[0]["end"].startswith("2026-11-11T00:00")
    assert second[0]["start"].startswith("2026-11-11T00:00")
    assert first[0]["actual_end"] == second[0]["actual_end"] == event["end"]
    result = generate([activity(category="assessment")], [event], [task()])
    assert result["status"] == "infeasible"
    assert any("outside waking hours" in message for message in result["conflicts"])


@pytest.mark.parametrize("day,start,end,minutes", [
    ("2027-03-14", "2027-03-14T00:00:00-05:00", "2027-03-15T00:00:00-04:00", 23 * 60),
    ("2026-11-01", "2026-11-01T00:00:00-04:00", "2026-11-02T00:00:00-05:00", 25 * 60),
])
def test_day_clipping_uses_real_dst_day_length(day, start, end, minutes):
    event = {"id": "overnight", "activity_id": "math", "start": start, "end": end, "source": "assessment"}
    blocks = fixed_blocks_for_day(day, SETTINGS, [activity(category="assessment")], [event])
    assert len(blocks) == 1 and elapsed(blocks[0]) == minutes


def test_duplicate_occurrence_identity_does_not_duplicate_fixed_time():
    event = occurrence()
    assert len(fixed_blocks_for_day(DAY, SETTINGS, [activity()], [event, dict(event)])) == 1
    with pytest.raises(ValueError, match="share an ID"):
        fixed_blocks_for_day(DAY, SETTINGS, [activity()], [event, occurrence(end="11:00")])


@pytest.mark.parametrize("event,message", [
    (occurrence(start="10:00", end="09:00"), "end must follow"),
    ({**occurrence(), "start": "2026-11-10T09:00:00"}, "timezone offset"),
    ({**occurrence(), "start": "2026-11-10T09:03:00-05:00"}, "five-minute"),
    (occurrence(activity_id="missing"), "missing activity"),
])
def test_bad_calendar_data_cannot_silently_free_time(event, message):
    with pytest.raises(ValueError, match=message):
        fixed_blocks_for_day(DAY, SETTINGS, [activity()], [event])


def test_unassigned_occurrence_remains_unknown_without_default_fallback():
    blocks = fixed_blocks_for_day(DAY, SETTINGS, [activity(location_id=None)], [occurrence()])
    assert blocks[0]["location_id"] is None
    assert blocks[0]["location_mode"] == "unspecified"


@pytest.mark.parametrize("override", [None, {"location_mode": "remote", "location_id": None}, {"location_mode": "required", "location_id": "B", "room": "510"}])
def test_occurrence_location_override_is_effective_without_changing_definition(override):
    definition = activity(location_mode="required", location_id="A")
    events = [occurrence(location_override=override)]
    fixed = fixed_blocks_for_day(DAY, SETTINGS, [definition], events)
    effective = override or definition
    assert fixed[0]["location_mode"] == effective["location_mode"]
    assert fixed[0]["location_id"] == effective["location_id"]
    assert fixed[0]["room"] == effective.get("room", "")
    assert fixed[0]["location_override"] == bool(override)
    assert definition["location_id"] == "A"
    result = generate([definition], events)
    assert result["status"] == "optimal", result["conflicts"]
    assert next(b for b in result["blocks"] if b["kind"] == "class")["location_mode"] == effective["location_mode"]
    assert next(b for b in result["blocks"] if b["kind"] == "class")["room"] == effective.get("room", "")
