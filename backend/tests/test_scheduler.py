"""Scenario tests exercising the real CP-SAT model, not a schedule mock."""
from copy import deepcopy
from datetime import datetime

import pytest

from backend.app.scheduler import generate_schedule, validate_blocks

DATE = "2026-11-10"
SETTINGS = {"timezone": "America/Toronto", "wake_time": "07:00", "sleep_time": "23:00",
            "work_start": "08:00", "work_end": "22:00", "break_minutes": 10,
            "travel_buffer_minutes": 5, "focus_minutes": 50, "default_location_id": "home",
            "meals": [], "solver_seconds": 2}


def task(id="t", **overrides):
    return {"id": id, "title": id, "kind": "academic", "remaining_minutes": 60,
            "duration_minutes": 60, "priority": 3, "splittable": True,
            "min_session_minutes": 25, "max_session_minutes": 90,
            "dependencies": [], "status": "todo", "location_id": "home", **overrides}


def cls(id="c", start="09:00", end="10:00", **overrides):
    return {"id": id, "title": id, "date": DATE, "start_time": start,
            "end_time": end, "location_id": "home", **overrides}


def block(id="b", start="09:00", end="10:00", **overrides):
    return {"id": id, "title": id, "kind": "personal", "start": f"{DATE}T{start}:00-05:00",
            "end": f"{DATE}T{end}:00-05:00", "location_id": "home", "locked": True, **overrides}


def generate(tasks=None, classes=None, blocks=None, settings=None, route=None, **kw):
    return generate_schedule(DATE, settings or deepcopy(SETTINGS), classes or [], tasks or [], blocks or [], route or (lambda a, b: 10), **kw)


def minutes(b):
    return int((datetime.fromisoformat(b["end"]) - datetime.fromisoformat(b["start"])).total_seconds() / 60)


def test_final_sustained_work_has_no_automatic_terminal_recovery():
    result = generate(tasks=[task(splittable=False)])
    assert result["conflicts"] == []
    assert sum(minutes(item) for item in result["blocks"] if item.get("task_id")) == 60
    assert not [item for item in result["blocks"] if item["kind"] == "break"]


def test_final_sustained_work_keeps_recovery_before_home_walk():
    settings = {**SETTINGS, "home_location_id": "home", "end_at_home": True,
                "travel_buffer_minutes": 0}
    source = task(splittable=False, location_id="campus", location_mode="required")
    result = generate(tasks=[source], settings=settings, route=lambda a, b: 15 if a != b else 0)
    assert result["conflicts"] == []
    kinds = [item["kind"] for item in result["blocks"]]
    assert kinds == ["task", "break", "travel"]
    assert minutes(result["blocks"][1]) == settings["break_minutes"]


def test_locked_terminal_break_is_preserved():
    protected = block("intentional-rest", "09:00", "09:15", kind="break")
    result = generate(tasks=[task(splittable=False)], blocks=[protected])
    assert result["conflicts"] == []
    preserved = next(item for item in result["blocks"] if item["id"] == protected["id"])
    assert preserved["start"] == protected["start"]
    assert preserved["end"] == protected["end"]


def test_compactness_ignores_distant_terminal_anchor_and_exposes_solver_evidence():
    result = generate(tasks=[task(splittable=False)], blocks=[block("late-anchor", "20:00", "21:00")])
    assert result["conflicts"] == []
    work = next(item for item in result["blocks"] if item.get("task_id"))
    assert work["start"].endswith("08:00:00-05:00")
    stats = result["stats"]
    assert stats["optional_work_extent_minutes"] == 60
    assert stats["discretionary_work_idle_minutes"] == 0
    assert stats["candidate_minutes"] == 60
    assert stats["objective_absolute_gap"] >= 0
    assert stats["objective_relative_gap"] >= 0
    assert any("finite candidate supply" in line for line in result["explanations"])


def test_empty_candidate_supply_has_zero_work_extent():
    result = generate(blocks=[block()])
    assert result["conflicts"] == []
    assert result["stats"]["optional_work_extent_minutes"] == 0
    assert result["stats"]["optional_completion_extent_minutes"] == 0


def test_deleted_task_does_not_generate_work_even_with_active_legacy_status():
    result = generate(tasks=[task(deleted_at="2026-11-12T12:00:00Z", priority=5)])
    assert not [block for block in result["blocks"] if block.get("task_id")]


@pytest.mark.parametrize("history_marker", ["_withdrawn_history", "_elapsed_work_history"])
def test_preferred_history_cannot_relocate_to_avoid_impossible_travel(history_marker):
    history = block(id="old", start="08:00", end="09:00", kind="task", task_id="t", locked=False,
                    location_mode="preferred", allow_alternative_locations=True,
                    alternative_location_ids=["campus"], **{history_marker: True})
    history_unit = task(status="skipped", location_mode="preferred", allow_alternative_locations=True,
                        alternative_location_ids=["campus"], history_only=True)
    result = generate(tasks=[history_unit], blocks=[history], classes=[cls(location_id="campus")],
                      settings={**SETTINGS, "break_minutes": 0, "travel_buffer_minutes": 0},
                      route=lambda a, b: 15 if a != b else 0)
    assert result["status"] == "infeasible"


def test_linked_assessment_adds_bounded_soft_value_without_a_hard_date():
    context = {"category": "assessment", "title": "Physics exam",
               "assessment_start": f"{DATE}T08:00:00-05:00"}
    tasks = [task("unlinked", splittable=False), task("linked", splittable=False, related_activity=context)]
    original = deepcopy(tasks)
    result = generate(tasks=tasks, settings={**SETTINGS, "work_end": "09:00", "break_minutes": 0})
    assert [block["task_id"] for block in result["blocks"] if block.get("task_id")] == ["linked"]
    assert "related assessment: Physics exam" in result["blocks"][0]["rationale"]
    assert not validate_blocks(result["blocks"], {**SETTINGS, "work_end": "09:00", "break_minutes": 0}, lambda a, b: 10, tasks)
    assert tasks == original


def test_linked_assessment_context_does_not_outweigh_explicit_deadline_urgency():
    context = {"category": "assessment", "title": "Exam", "assessment_start": f"{DATE}T08:00:00-05:00"}
    tasks = [task("linked", splittable=False, related_activity=context),
             task("deadline", splittable=False, deadline=f"{DATE}T09:00:00-05:00")]
    result = generate(tasks=tasks, settings={**SETTINGS, "work_end": "09:00", "break_minutes": 0})
    assert [block["task_id"] for block in result["blocks"] if block.get("task_id")] == ["deadline"]


def test_linked_context_never_replaces_task_hard_deadline():
    context = {"category": "assessment", "title": "Exam", "assessment_start": f"{DATE}T12:00:00-05:00"}
    result = generate(tasks=[task(splittable=False, deadline=f"{DATE}T07:30:00-05:00", related_activity=context)])
    assert not any(block.get("task_id") for block in result["blocks"])
    assert result["unallocated"]


@pytest.mark.parametrize("mode", ["balanced", "deadline", "deep"])
def test_daily_soft_minimum_prefers_actual_chunks_when_work_is_chosen(mode):
    result = generate(tasks=[task(remaining_minutes=60, min_session_minutes=20,
                                  max_session_minutes=60, min_sessions_per_day=3)], mode=mode)
    chunks = [item for item in result["blocks"] if item.get("task_id") == "t"]
    assert len(chunks) == 3
    assert sum(minutes(item) for item in chunks) == 60
    assert result["daily_progress"][0]["expected_shortfall"] == 0
    assert result["conflicts"] == []


def test_daily_zero_minimum_allows_one_block_and_does_not_force_splitting():
    result = generate(tasks=[task(min_sessions_per_day=0)])
    assert len([item for item in result["blocks"] if item.get("task_id") == "t"]) == 1
    assert result["daily_progress"][0]["minimum_sessions"] == 0


def test_daily_soft_minimum_never_requires_work_or_overrides_urgent_work():
    settings = {**SETTINGS, "work_end": "09:00", "break_minutes": 0}
    routine = task("routine", priority=1, min_session_minutes=10, min_sessions_per_day=6)
    urgent = task("urgent", priority=5, min_session_minutes=60,
                  deadline=f"{DATE}T09:00:00-05:00")
    result = generate(tasks=[routine, urgent], settings=settings)
    assert {item["task_id"] for item in result["blocks"] if item.get("task_id")} == {"urgent"}
    assert result["status"] == "partial"
    assert not any(item["task_definition_id"] == "routine" for item in result["daily_progress"])


def test_daily_minimum_shortfall_is_reported_without_invalidating_one_useful_block():
    result = generate(tasks=[task(splittable=False, min_sessions_per_day=3)])
    assert result["status"] in {"optimal", "feasible"}
    assert result["daily_progress"][0]["scheduled_sessions"] == 1
    assert result["daily_progress"][0]["expected_shortfall"] == 2


def test_daily_maximum_counts_each_split_chunk():
    task_value = task(remaining_minutes=120, duration_minutes=120, min_session_minutes=30,
                      max_session_minutes=30, max_sessions_per_day=2)
    result = generate(tasks=[task_value])
    assert len([item for item in result["blocks"] if item.get("task_id")]) == 2
    assert result["unallocated"][0]["minutes"] == 60
    assert result["daily_progress"][0]["scheduled_sessions"] == 2


def test_daily_maximum_is_shared_by_multiple_logical_session_units():
    tasks = [task(id, task_definition_id="definition", splittable=False,
                  max_sessions_per_day=1, logical_session_id=id) for id in ("one", "two")]
    result = generate(tasks=tasks)
    assert len([item for item in result["blocks"] if item.get("task_id")]) == 1
    assert result["unallocated"][0]["minutes"] == 60
    assert not validate_blocks(result["blocks"], SETTINGS, lambda a, b: 10, tasks)


@pytest.mark.parametrize("status", ["todo", "completed", "in_progress"])
def test_daily_maximum_includes_preserved_work_and_keeps_its_history(status):
    preserved = block("saved", "09:00", "09:30", kind="task", task_id="t", status=status)
    task_value = task(remaining_minutes=90, max_sessions_per_day=1)
    result = generate(tasks=[task_value], blocks=[preserved])
    chunks = [item for item in result["blocks"] if item.get("task_id")]
    assert len(chunks) == 1
    assert chunks[0]["id"] == "saved"
    if status != "todo":
        assert chunks[0] == preserved


def test_daily_maximum_excludes_skipped_blocks():
    skipped = block("missed", "09:00", "09:30", kind="task", task_id="t", status="skipped")
    result = generate(tasks=[task(max_sessions_per_day=1)], blocks=[skipped])
    assert len([item for item in result["blocks"] if item.get("task_id") and item.get("status") != "skipped"]) == 1
    assert result["daily_progress"][0]["scheduled_sessions"] == 1


def test_daily_maximum_reports_preserved_over_limit_without_deleting_blocks():
    blocks = [block("old", "08:00", "08:30", kind="task", task_id="old-unit", task_definition_id="d", status="completed"),
              block("started", "09:00", "09:30", kind="task", task_id="started-unit", task_definition_id="d", status="in_progress")]
    metadata = task("definition:d", task_definition_id="d", status="completed", remaining_minutes=0,
                    max_sessions_per_day=1)
    result = generate(tasks=[metadata], blocks=blocks)
    assert result["status"] == "infeasible"
    assert any("daily maximum" in message for message in result["conflicts"])
    assert result["blocks"] == blocks


def test_manual_daily_maximum_counts_completed_and_distinct_units_on_local_dates():
    settings = {**SETTINGS, "break_minutes": 0}
    tasks = [task(id, task_definition_id="d", max_sessions_per_day=1) for id in ("one", "two")]
    blocks = [block("done", "08:00", "08:30", kind="task", task_id="one", status="completed"),
              block("new", "09:00", "09:30", kind="task", task_id="two")]
    assert any("daily maximum" in error for error in validate_blocks(blocks, settings, lambda a, b: 0, tasks))
    blocks[0]["status"] = "skipped"
    assert not validate_blocks(blocks, settings, lambda a, b: 0, tasks)
    blocks[0].update(status="completed", start="2026-11-09T08:00:00-05:00", end="2026-11-09T08:30:00-05:00")
    assert not validate_blocks(blocks, settings, lambda a, b: 0, tasks)


def test_daily_huge_minimum_remains_bounded_and_reports_actual_shortfall():
    result = generate(tasks=[task(splittable=False, min_sessions_per_day=9007199254740991)])
    assert result["status"] in {"optimal", "feasible"}
    assert result["daily_progress"][0]["expected_shortfall"] == 9007199254740990


def test_legacy_class_room_is_retained_as_attendance_context():
    result = generate(classes=[cls(room="2066")])
    assert next(item for item in result["blocks"] if item["kind"] == "class")["room"] == "2066"


def test_real_solver_schedules_and_validates():
    tasks = [task()]
    result = generate(tasks=tasks, classes=[cls()])
    assert result["solver_status"] == "OPTIMAL"
    assert result["status"] == "optimal"
    assert sum(minutes(b) for b in result["blocks"] if b.get("task_id") == "t") == 60
    assert not validate_blocks(result["blocks"], SETTINGS, lambda a, b: 10, tasks)
    assert tasks[0]["remaining_minutes"] == 60


def test_overlapping_fixed_classes_are_explicitly_infeasible():
    result = generate(classes=[cls(), cls("b", "09:30", "10:30")])
    assert result["status"] == "infeasible"
    assert any("Overlap" in c for c in result["conflicts"])
    assert len(result["blocks"]) == 2


def test_unassigned_work_cannot_teleport_between_buildings():
    settings = {**SETTINGS, "default_location_id": None, "break_minutes": 0, "travel_buffer_minutes": 0}
    result = generate(settings=settings, classes=[cls(location_id="A"), cls("b", "10:30", "11:00", location_id="B")], tasks=[task(location_id=None, remaining_minutes=30, duration_minutes=30)], route=lambda a, b: 60)
    assert result["status"] == "infeasible"
    assert result["solver_status"] == "INFEASIBLE"
    edits = [block(location_id="A"), block("remote", "10:00", "10:30", location_id=None), block("b", "10:30", "11:00", location_id="B")]
    assert any("Insufficient travel" in message for message in validate_blocks(edits, settings, lambda a, b: 60))


def test_fully_remote_workspace_needs_no_default_location():
    settings = {**SETTINGS, "default_location_id": None}
    result = generate(settings=settings, tasks=[task(location_id=None)])
    assert result["status"] == "optimal"


def test_travel_is_optimization_constraint():
    result = generate(classes=[cls(location_id="campus"), cls("b", "10:10", "11:00", location_id="library")], route=lambda a, b: 20)
    assert result["status"] == "infeasible"
    assert result["solver_status"] == "INFEASIBLE"


def test_travel_blocks_include_buffer_and_do_not_overlap():
    settings = {**SETTINGS, "home_location_id": "home", "start_at_home": True, "end_at_home": True}
    result = generate(settings=settings, classes=[cls(location_id="campus"), cls("b", "11:00", "12:00", location_id="library")])
    assert result["status"] == "optimal"
    routes = [b for b in result["blocks"] if b["kind"] == "travel"]
    assert len(routes) == 3
    assert all(minutes(b) == 15 for b in routes)
    assert not validate_blocks(result["blocks"], settings, lambda a, b: 10)


def test_impossible_workload_returns_feasible_partial():
    settings = {**SETTINGS, "work_start": "08:00", "work_end": "09:00"}
    result = generate(tasks=[task(remaining_minutes=600)], settings=settings)
    assert result["status"] == "partial"
    assert result["unallocated"][0]["minutes"] >= 540
    assert result["conflicts"] == []


def test_hard_deadline_is_never_exceeded():
    result = generate(tasks=[task(deadline=f"{DATE}T08:30:00-05:00")])
    assert result["status"] == "partial"
    sessions = [b for b in result["blocks"] if b.get("task_id")]
    assert sum(minutes(b) for b in sessions) == 30
    assert all(datetime.fromisoformat(b["end"]).hour == 8 for b in sessions)


def test_urgent_task_beats_less_urgent_when_only_one_fits():
    settings = {**SETTINGS, "work_start": "08:00", "work_end": "09:00"}
    result = generate(tasks=[task("low", priority=1, splittable=False), task("urgent", priority=5, splittable=False, deadline=f"{DATE}T09:00:00-05:00")], settings=settings, mode="deadline")
    assert [b["task_id"] for b in result["blocks"] if b.get("task_id")] == ["urgent"]


def test_splitting_obeys_session_limits_and_breaks():
    tasks = [task(remaining_minutes=180, max_session_minutes=60)]
    result = generate(tasks=tasks)
    sessions = [b for b in result["blocks"] if b.get("task_id")]
    assert sum(minutes(b) for b in sessions) == 180
    assert all(25 <= minutes(b) <= 60 for b in sessions)
    assert len([b for b in result["blocks"] if b["kind"] == "break"]) == len(sessions) - 1
    assert result["conflicts"] == []


def test_unsplittable_task_cannot_be_partially_allocated():
    result = generate(tasks=[task(remaining_minutes=120, splittable=False)], settings={**SETTINGS, "work_end": "09:00"})
    assert result["unallocated"][0]["minutes"] == 120
    assert not any(b.get("task_id") for b in result["blocks"])


def test_dependency_requires_full_completion_and_precedence():
    tasks = [task("pre"), task("post", dependencies=["pre"])]
    result = generate(tasks=tasks)
    pre = [b for b in result["blocks"] if b.get("task_id") == "pre"]
    post = [b for b in result["blocks"] if b.get("task_id") == "post"]
    assert pre and post
    assert max(b["end"] for b in pre) <= min(b["start"] for b in post)
    assert result["conflicts"] == []


@pytest.mark.parametrize("dependencies", [["missing"], ["t"]])
def test_missing_or_cyclic_dependency_not_scheduled(dependencies):
    result = generate(tasks=[task(dependencies=dependencies)])
    assert result["status"] == "partial"
    assert result["unallocated"][0]["minutes"] == 60


def test_completed_prerequisite_allows_work():
    result = generate(tasks=[task("pre", status="completed", remaining_minutes=0), task("post", dependencies=["pre"])])
    assert result["status"] == "optimal"


def test_locked_task_reduces_new_allocation_and_survives():
    locked = block(kind="task", task_id="t", start="10:00", end="10:30")
    result = generate(tasks=[task()], blocks=[locked])
    assert any(b["id"] == "b" and b["start"] == locked["start"] for b in result["blocks"])
    assert sum(minutes(b) for b in result["blocks"] if b.get("task_id") == "t") == 60
    assert result["status"] == "optimal"


def test_completed_work_is_preserved_without_double_counting():
    done = block(kind="task", task_id="t", start="08:00", end="08:30", status="completed",
                 completion_confirmed_at=f"{DATE}T08:35:00-05:00", completion_previous_status="todo",
                 completion_verified=True, rationale="Original work record")
    result = generate(tasks=[task(remaining_minutes=30)], blocks=[done], now=f"{DATE}T10:00:00-05:00")
    assert next(b for b in result["blocks"] if b["id"] == "b") == done
    future = [b for b in result["blocks"] if b.get("task_id") and b.get("status") != "completed"]
    assert sum(minutes(b) for b in future) == 30
    assert all(b["start"] >= f"{DATE}T10:00:00-05:00" for b in future)


def test_elapsed_unconfirmed_work_reserves_minutes_without_credit_or_metadata_changes():
    elapsed = block(kind="task", task_id="t", start="08:00", end="08:30", status="todo", locked=False,
                    location_mode="remote", location_id=None, rationale="Saved pending work",
                    _elapsed_work_history=True)
    original = deepcopy(elapsed)
    result = generate(tasks=[task(remaining_minutes=60, location_mode="remote", location_id=None)],
                      blocks=[elapsed], now=f"{DATE}T10:00:00-05:00")
    assert result["status"] in {"optimal", "feasible"}
    assert next(b for b in result["blocks"] if b["id"] == "b") == original
    future = [b for b in result["blocks"] if b.get("task_id") and b["id"] != "b"]
    assert sum(minutes(b) for b in future) == 30
    assert all(b["start"] >= f"{DATE}T10:00:00-05:00" for b in future)
    assert not any(b.get("completion_verified") or b.get("status") == "completed" for b in result["blocks"])
    assert elapsed == original


def test_meals_reserved_and_legacy_time_moves_around_class():
    settings = {**SETTINGS, "meals": [{"name": "Lunch", "time": "12:00", "duration_minutes": 30}]}
    result = generate(tasks=[task()], settings=settings)
    assert any(b["kind"] == "meal" for b in result["blocks"])
    collision = generate(classes=[cls(start="12:00", end="13:00")], settings=settings)
    assert collision["status"] == "optimal"
    assert not validate_blocks(collision["blocks"], settings, lambda a, b: 10)
    meal = next(block for block in collision["blocks"] if block["kind"] == "meal")
    assert meal["end"] <= f"{DATE}T12:00:00-05:00" or meal["start"] >= f"{DATE}T13:00:00-05:00"


def test_recurrence_and_exceptions():
    c = cls(date=None, weekdays=[1], exceptions=[DATE])
    assert not generate(classes=[c])["blocks"]
    c["exceptions"] = []
    assert any(b["class_id"] == "c" for b in generate(classes=[c])["blocks"])


def test_midnight_deadline_on_next_day_allows_today():
    result = generate(tasks=[task(deadline="2026-11-11T00:00:00-05:00")])
    assert result["status"] == "optimal"


@pytest.mark.parametrize("day", ["2026-03-08", "2026-11-01"])
def test_dst_real_elapsed_duration(day):
    settings = {**SETTINGS, "wake_time": "00:00", "work_start": "00:00", "work_end": "06:00", "sleep_time": "07:00"}
    result = generate_schedule(day, settings, [], [task(remaining_minutes=120)], [], lambda a, b: 0)
    assert result["status"] == "optimal"
    assert sum(minutes(b) for b in result["blocks"] if b.get("task_id")) == 120


def test_solver_timeout_distinct_from_infeasible():
    result = generate(tasks=[task()], settings={**SETTINGS, "solver_seconds": 0})
    assert result["status"] == "timeout"
    assert result["solver_status"] == "UNKNOWN"
    assert result["unallocated"][0]["minutes"] == 60


def test_manual_edit_detects_deadline_overlap_travel_and_duration():
    tasks = [task(deadline=f"{DATE}T09:00:00-05:00")]
    blocks = [block(kind="task", task_id="t", start="09:00", end="09:10", location_id="campus"), block("b2", "09:05", "10:00")]
    errors = validate_blocks(blocks, SETTINGS, lambda a, b: 20, tasks)
    assert any("Overlap" in e for e in errors)
    assert any("hard deadline" in e for e in errors)
    assert any("session duration" in e for e in errors)


def test_manual_edit_rejects_incomplete_dependency():
    errors = validate_blocks([block(kind="task", task_id="post")], SETTINGS, lambda a, b: 0, [task("pre"), task("post", dependencies=["pre"])])
    assert any("prerequisite" in e for e in errors)


def test_tiny_remaining_minutes_are_explicit_not_silently_lost():
    result = generate(tasks=[task(remaining_minutes=10)])
    assert result["unallocated"][0]["minutes"] == 10
    assert "minimum session" in result["unallocated"][0]["reason"]


def test_overloaded_task_list_starts_with_meaningful_feasible_progress():
    tasks = [task(str(i), remaining_minutes=120) for i in range(12)]
    # This capacity/performance scenario asks for maximal sustainable output;
    # Medium now deliberately values free time above some optional minutes.
    result = generate(tasks=tasks, settings={**SETTINGS, "solver_seconds": 3, "workload_level": "very_high"})
    assert result["status"] == "partial"
    assert result["stats"]["allocated_minutes"] >= 600
    assert result["conflicts"] == []


@pytest.mark.parametrize("preference,hour", [("morning", 8), ("afternoon", 12), ("evening", 17)])
def test_energy_window_is_a_soft_work_preference(preference, hour):
    result = generate(tasks=[task()], settings={**SETTINGS, "energy_preference": preference})
    sessions = [b for b in result["blocks"] if b.get("task_id")]
    assert datetime.fromisoformat(sessions[0]["start"]).hour == hour
    assert result["status"] == "optimal"


def test_energy_preference_never_overrides_hard_deadline():
    result = generate(tasks=[task(deadline=f"{DATE}T09:00:00-05:00")], settings={**SETTINGS, "energy_preference": "evening"})
    assert result["status"] == "optimal"
    assert max(b["end"] for b in result["blocks"] if b.get("task_id")) <= f"{DATE}T09:00:00-05:00"


def project(**overrides):
    return {"id": "project-context", "name": "Vector", "importance": 5.5,
            "difficulty": 8.5, "status": "active", "contributors": 4,
            "affiliations": ["Waterloo Reality Labs", "Independent"],
            "category": "software", "description": "Semantic processor research",
            "goals": "Evaluate context finder results", "links": ["https://example.com"],
            "start_date": "2026-01-01", "end_date": "2026-12-31", **overrides}


@pytest.mark.parametrize("mode", ["balanced", "deadline", "deep"])
def test_project_importance_prioritizes_equal_tasks_in_every_mode(mode):
    tasks = [task("lower", splittable=False, project=project(id="low", importance=1)),
             task("higher", splittable=False, project=project(id="high", importance=10))]
    result = generate(tasks=tasks, settings={**SETTINGS, "work_end": "09:00", "break_minutes": 0}, mode=mode)
    sessions = [b for b in result["blocks"] if b.get("task_id")]
    assert [b["task_id"] for b in sessions] == ["higher"]
    assert sessions[0]["project_id"] == "high"
    assert "project importance 10/10" in sessions[0]["rationale"]
    assert result["unallocated"][0]["task_id"] == "lower"


@pytest.mark.parametrize("mode", ["balanced", "deadline", "deep"])
def test_project_importance_never_overrides_one_task_priority_step(mode):
    tasks = [task("important-project", priority=3, splittable=False, project=project(importance=10)),
             task("higher-task-priority", priority=4, splittable=False)]
    result = generate(tasks=tasks, settings={**SETTINGS, "work_end": "09:00", "break_minutes": 0}, mode=mode)
    assert [b["task_id"] for b in result["blocks"] if b.get("task_id")] == ["higher-task-priority"]


@pytest.mark.parametrize("importance,points", [(1, 0), (1.5, 5), (5.5, 45), (9.5, 85), (10, 90)])
def test_project_importance_half_steps_have_exact_documented_weight(importance, points):
    from backend.app.scheduler import _project_priority_bonus

    assert _project_priority_bonus(task(project=project(importance=importance))) == points


@pytest.mark.parametrize("mode", ["balanced", "deadline", "deep"])
def test_actual_task_urgency_outweighs_project_importance(mode):
    tasks = [task("important-project", splittable=False, project=project(importance=10)),
             task("urgent", splittable=False, deadline=f"{DATE}T09:00:00-05:00")]
    result = generate(tasks=tasks, settings={**SETTINGS, "work_end": "09:00", "break_minutes": 0}, mode=mode)
    assert [b["task_id"] for b in result["blocks"] if b.get("task_id")] == ["urgent"]


@pytest.mark.parametrize("status", ["paused", "archived"])
def test_inactive_project_tasks_are_reported_as_excluded_not_unallocated(status):
    result = generate(tasks=[task(project=project(status=status))])
    assert result["status"] == "optimal"
    assert not result["blocks"]
    assert result["unallocated"] == []
    assert result["excluded_tasks"][0]["task_id"] == "t"
    assert result["excluded_tasks"][0]["minutes"] == 60
    assert status in result["excluded_tasks"][0]["reason"]


@pytest.mark.parametrize("status", ["paused", "archived"])
def test_explicit_request_can_schedule_inactive_project_tasks(status):
    result = generate(tasks=[task(project=project(status=status), schedule_inactive_project=True)])
    assert result["status"] == "optimal"
    assert result["excluded_tasks"] == []
    assert sum(minutes(b) for b in result["blocks"] if b.get("task_id")) == 60


@pytest.mark.parametrize("status", ["planning", "active", "completed"])
def test_other_project_statuses_leave_remaining_task_eligibility_intact(status):
    result = generate(tasks=[task(project=project(status=status))])
    assert result["status"] == "optimal"
    assert result["excluded_tasks"] == []
    assert sum(minutes(b) for b in result["blocks"] if b.get("task_id")) == 60


@pytest.mark.parametrize("status", ["todo", "in_progress"])
def test_paused_project_keeps_preserved_commitments_without_new_work(status):
    locked = block(kind="project", task_id="t", start="10:00", end="10:30", status=status)
    result = generate(tasks=[task(project=project(status="paused"))], blocks=[locked])
    sessions = [b for b in result["blocks"] if b.get("task_id")]
    assert len(sessions) == 1
    assert sessions[0]["id"] == locked["id"]
    assert minutes(sessions[0]) == 30
    assert result["excluded_tasks"][0]["minutes"] == 30
    assert result["status"] == "optimal"


def test_paused_project_prerequisite_does_not_release_dependent_work():
    tasks = [task("pre", project=project(status="paused")), task("post", dependencies=["pre"])]
    result = generate(tasks=tasks)
    assert not any(b.get("task_id") for b in result["blocks"])
    assert result["unallocated"][0]["task_id"] == "post"
    assert "prerequisite" in result["unallocated"][0]["reason"]
    assert result["excluded_tasks"][0]["task_id"] == "pre"


def test_fully_preserved_paused_prerequisite_releases_work_after_its_session():
    tasks = [task("pre", project=project(status="paused")), task("post", dependencies=["pre"])]
    locked = block(kind="project", task_id="pre", start="10:00", end="11:00")
    result = generate(tasks=tasks, blocks=[locked])
    post = [b for b in result["blocks"] if b.get("task_id") == "post"]
    assert post
    assert all(b["start"] >= locked["end"] for b in post)
    assert result["excluded_tasks"][0]["minutes"] == 0
    assert result["status"] == "optimal"


def test_soft_task_deadline_keeps_urgency_without_becoming_hard_constraint():
    tasks = [task("past-soft-deadline", splittable=False, hard_deadline=False,
                  deadline="2026-11-09T17:00:00-05:00"),
             task("important-project", splittable=False, project=project(importance=10))]
    result = generate(tasks=tasks, settings={**SETTINGS, "work_end": "09:00", "break_minutes": 0})
    assert [b["task_id"] for b in result["blocks"] if b.get("task_id")] == ["past-soft-deadline"]
    assert not validate_blocks(result["blocks"], SETTINGS, lambda a, b: 10, tasks)


@pytest.mark.parametrize("difficulty", [0, 10])
def test_project_context_does_not_create_duration_or_deadline_constraints(difficulty):
    tasks = [task(project=project(importance=10, difficulty=difficulty, start_date="2027-01-01", end_date="2027-02-01"))]
    original = deepcopy(tasks)
    result = generate(tasks=tasks)
    assert result["status"] == "optimal"
    assert sum(minutes(b) for b in result["blocks"] if b.get("task_id")) == 60
    assert tasks == original
    # A past project end date is also context, not a task hard deadline.
    tasks[0]["project"]["start_date"] = "2025-01-01"
    tasks[0]["project"]["end_date"] = "2025-02-01"
    assert generate(tasks=tasks)["status"] == "optimal"


def test_project_importance_and_difficulty_cannot_override_hard_task_deadline():
    tasks = [task(project=project(importance=10, difficulty=10), deadline=f"{DATE}T08:30:00-05:00")]
    result = generate(tasks=tasks)
    assert result["status"] == "partial"
    sessions = [b for b in result["blocks"] if b.get("task_id")]
    assert sum(minutes(b) for b in sessions) == 30
    assert all(b["end"] <= f"{DATE}T08:30:00-05:00" for b in sessions)
    assert not validate_blocks(result["blocks"], SETTINGS, lambda a, b: 10, tasks)


def test_empty_task_list_never_generates_project_work():
    result = generate(tasks=[])
    assert result["status"] == "optimal"
    assert result["blocks"] == []
    assert result["stats"]["allocated_minutes"] == 0


@pytest.mark.parametrize("policy", ["remote", "unspecified"])
def test_flexible_event_keeps_physical_position_and_does_not_teleport(policy):
    fixed = [block("a", "09:00", "10:00", location_id="A"),
             block("flex", "10:00", "10:30", location_id=None, location_mode=policy),
             block("b", "10:45", "11:00", location_id="B")]
    settings = {**SETTINGS, "break_minutes": 0, "travel_buffer_minutes": 5}
    result = generate(blocks=fixed, settings=settings, route=lambda a, b: 10)
    assert result["status"] == "optimal", result["conflicts"]
    flexible = next(b for b in result["blocks"] if b["id"] == "flex")
    assert flexible["location_id"] is None
    assert flexible["location_mode"] == policy
    assert flexible["resolved_location_id"] == "A"
    walks = [b for b in result["blocks"] if b["kind"] == "travel"]
    assert len(walks) == 1 and walks[0]["origin_id"] == "A" and walks[0]["destination_id"] == "B"
    assert minutes(walks[0]) == 15
    assert not validate_blocks(result["blocks"], settings, lambda a, b: 10)
    if policy == "unspecified":
        assert any("unknown" in explanation for explanation in result["explanations"])
    # The event's time cannot double as productive work and a walk.
    fixed[-1]["start"] = f"{DATE}T10:30:00-05:00"
    assert generate(blocks=fixed, settings=settings, route=lambda a, b: 10)["status"] == "infeasible"
    assert any("Insufficient travel" in error for error in validate_blocks(fixed, settings, lambda a, b: 10))


@pytest.mark.parametrize("mode", ["balanced", "deadline", "deep"])
@pytest.mark.parametrize("kind,policy", [("meal", "unspecified"), ("class", "remote"), ("class", "unspecified")])
def test_idle_gap_before_flexible_event_allows_real_travel_and_morning_work(mode, kind, policy):
    # Lunch directly before MC class used to inherit RCH forever, making the
    # morning falsely unavailable despite nearly three hours to walk to MC.
    fixed = [block("lunch", "12:00", "12:30", kind=kind, location_id=None, location_mode=policy),
             block("lecture", "12:30", "13:30", location_id="MC", location_mode="required")]
    source = task(location_id="RCH", location_mode="required", splittable=False)
    result = generate(tasks=[source], blocks=fixed, route=lambda a, b: 15, mode=mode)
    assert result["status"] == "optimal", result["conflicts"]
    session = next(b for b in result["blocks"] if b.get("task_id") == "t")
    assert session["start"] == f"{DATE}T08:00:00-05:00"
    flexible = next(b for b in result["blocks"] if b["id"] == "lunch")
    assert flexible["location_id"] is None and flexible["resolved_location_id"] == "MC"
    walk = next(b for b in result["blocks"] if b["kind"] == "travel")
    assert walk["origin_id"] == "RCH" and walk["destination_id"] == "MC"
    assert minutes(walk) == 20 and walk["end"] == flexible["start"]
    assert not validate_blocks(result["blocks"], SETTINGS, lambda a, b: 15, [source])
    assert result["stats"]["objective_value"] == result["stats"]["objective_bound"]


def test_repositioning_before_first_remote_event_requires_real_home_travel():
    settings = {**SETTINGS, "home_location_id": "home", "start_at_home": True,
                "wake_time": "07:00", "break_minutes": 0}
    fixed = [block("remote", "08:00", "08:30", location_id=None, location_mode="remote"),
             block("lecture", "08:30", "09:30", location_id="MC", location_mode="required")]
    result = generate(blocks=fixed, settings=settings, route=lambda a, b: 15)
    assert result["status"] == "optimal", result["conflicts"]
    remote = next(b for b in result["blocks"] if b["id"] == "remote")
    assert remote["resolved_location_id"] == "MC"
    walk = next(b for b in result["blocks"] if b["kind"] == "travel")
    assert walk["origin_id"] == "home" and walk["destination_id"] == "MC"
    assert minutes(walk) == 20 and walk["end"] == remote["start"]
    assert not validate_blocks(result["blocks"], settings, lambda a, b: 15)
    # With no pre-event free time the same journey remains impossible.
    settings["wake_time"] = "08:00"
    assert generate(blocks=fixed, settings=settings, route=lambda a, b: 15)["status"] == "infeasible"


@pytest.mark.parametrize("split", [False, True])
def test_verified_suitable_candidate_is_available_without_legacy_alternative_toggle(split):
    suitability = {"requirements": ["exercise"], "source": "inferred", "confidence": "high",
                   "candidates": [{"location_id": "PAC", "source": "selected", "confidence": "high", "evidence": "Selected gym"},
                                  {"location_id": "other-gym", "source": "verified_capabilities", "confidence": "high", "evidence": "Saved gym; access confirmed"}],
                   "limitation": ""}
    settings = {**SETTINGS, "work_start": "10:00", "work_end": "11:10", "break_minutes": 0,
                "travel_buffer_minutes": 0}
    fixed = [block("before", "09:00", "10:00", location_id="MC"),
             block("after", "11:10", "12:00", location_id="MC")]
    source = task(title="Gym", location_id="PAC", location_mode="preferred", splittable=split,
                  min_session_minutes=30, max_session_minutes=30 if split else 60,
                  allow_alternative_locations=False, alternative_location_ids=[],
                  location_requirements=["exercise"], location_suitability=suitability)
    def route(a, b):
        return 5 if "other-gym" in {a, b} else 40
    result = generate(tasks=[source], blocks=fixed, settings=settings, route=route)
    assert result["status"] == "optimal", result["conflicts"]
    sessions = [b for b in result["blocks"] if b.get("task_id") == "t"]
    assert len(sessions) == (2 if split else 1)
    assert all(b["resolved_location_id"] == "other-gym" and b["location_id"] == "PAC" for b in sessions)
    assert all(b["location_suitability"] == suitability and "Saved gym; access confirmed" in b["rationale"] for b in sessions)
    assert all("verified suitable" in b["rationale"] for b in sessions)
    assert not validate_blocks(result["blocks"], settings, route, [source])
    # A fixed attendance requirement never consumes the wider candidate domain.
    required = generate(tasks=[{**source, "location_mode": "required"}], blocks=fixed, settings=settings, route=route)
    assert not any(b.get("task_id") for b in required["blocks"])


def test_unknown_suitability_reports_limit_without_inventing_a_venue():
    suitability = {"requirements": [], "source": "unknown", "confidence": "unknown",
                   "candidates": [{"location_id": "PAC", "source": "selected", "confidence": "high", "evidence": "Selected venue"}],
                   "limitation": "No verified suitable alternative is known."}
    result = generate(tasks=[task(location_id="PAC", location_mode="preferred", location_suitability=suitability)])
    session = next(b for b in result["blocks"] if b.get("task_id"))
    assert session["resolved_location_id"] == "PAC"
    assert suitability["limitation"] in session["rationale"]


def test_preferred_location_yields_only_to_explicitly_authorized_alternative():
    settings = {**SETTINGS, "work_start": "10:00", "work_end": "11:00", "break_minutes": 0}
    fixed = [block("before", "09:00", "10:00", location_id="A"), block("after", "11:00", "12:00", location_id="A")]
    source = task(location_id="PAC", location_mode="preferred", splittable=False)
    no_permission = generate(tasks=[source], blocks=fixed, settings=settings)
    assert no_permission["status"] == "partial"
    assert no_permission["unallocated"][0]["minutes"] == 60
    assert not any(b.get("task_id") for b in no_permission["blocks"])
    source.update(allow_alternative_locations=True, alternative_location_ids=["A"])
    result = generate(tasks=[source], blocks=fixed, settings=settings)
    assert result["status"] == "optimal", result["conflicts"]
    session = next(b for b in result["blocks"] if b.get("task_id"))
    assert session["location_id"] == "PAC" and session["resolved_location_id"] == "A"
    assert "alternative" in session["rationale"]
    assert not validate_blocks(result["blocks"], settings, lambda a, b: 10, [source])
    required = generate(tasks=[{**source, "location_mode": "required"}], blocks=fixed, settings=settings)
    assert required["status"] == "partial" and required["unallocated"][0]["minutes"] == 60


@pytest.mark.parametrize("permissions", [
    {"alternative_location_ids": ["MC"]},
    {"allow_alternative_locations": True, "alternative_location_ids": ["other-gym"]},
    {"allow_alternative_locations": True, "alternative_location_ids": []},
])
def test_known_campus_is_never_invented_as_gym_alternative(permissions):
    settings = {**SETTINGS, "work_start": "10:00", "work_end": "11:00", "break_minutes": 0}
    fixed = [block("before", "09:00", "10:00", location_id="MC"),
             block("after", "11:00", "12:00", location_id="MC")]
    gym = task(title="Gym", location_id="PAC", location_mode="preferred", splittable=False, **permissions)
    result = generate(tasks=[gym], blocks=fixed, settings=settings)
    assert result["status"] == "partial", result["conflicts"]
    assert result["unallocated"][0]["minutes"] == 60
    assert not any(b.get("task_id") for b in result["blocks"])


def test_whitelisted_alternative_is_in_solver_even_without_other_visits():
    settings = {**SETTINGS, "work_start": "10:00", "work_end": "11:10", "break_minutes": 0,
                "travel_buffer_minutes": 0}
    fixed = [block("before", "09:00", "10:00", location_id="MC"),
             block("after", "11:10", "12:00", location_id="MC")]
    gym = task(location_id="PAC", location_mode="preferred", splittable=False,
               allow_alternative_locations=True, alternative_location_ids=["other-gym"])
    result = generate(tasks=[gym], blocks=fixed, settings=settings,
                      route=lambda a, b: 5 if "other-gym" in (a, b) else 30)
    assert result["status"] == "optimal", result["conflicts"]
    session = next(b for b in result["blocks"] if b.get("task_id"))
    assert session["resolved_location_id"] == "other-gym"
    assert [(b["origin_id"], b["destination_id"]) for b in result["blocks"] if b["kind"] == "travel"] == [("MC", "other-gym"), ("other-gym", "MC")]


def test_configured_preferred_venue_wins_when_both_venues_fit():
    source = task(location_id="PAC", location_mode="preferred", splittable=False,
                  allow_alternative_locations=True, alternative_location_ids=["MC"])
    result = generate(tasks=[source])
    assert result["status"] == "optimal"
    session = next(b for b in result["blocks"] if b.get("task_id"))
    assert session["resolved_location_id"] == "PAC"
    assert "configured preferred venue" in session["rationale"]


@pytest.mark.parametrize("mode", ["required", "preferred"])
def test_validator_rejects_forged_actual_venue_and_block_only_permission(mode):
    source = task(location_id="PAC", location_mode=mode)
    forged = block(kind="task", task_id="t", location_id="PAC", location_mode=mode,
                   resolved_location_id="MC", allow_alternative_locations=True, alternative_location_ids=["MC"])
    errors = validate_blocks([forged], SETTINGS, lambda a, b: 10, [source])
    assert any("explicitly permitted" in error for error in errors)


def test_explicit_manual_location_override_still_requires_its_own_venue_permission():
    source = task(location_id="PAC", location_mode="preferred")
    override = block(kind="task", task_id="t", location_id="other-gym", location_mode="required",
                     resolved_location_id="other-gym", location_override=True)
    assert validate_blocks([override], SETTINGS, lambda a, b: 10, [source]) == []
    override["resolved_location_id"] = "MC"
    assert any("explicitly permitted" in error for error in validate_blocks([override], SETTINGS, lambda a, b: 10, [source]))


def test_authorized_venue_policy_is_retained_on_every_split_chunk():
    settings = {**SETTINGS, "work_start": "10:00", "work_end": "11:00", "break_minutes": 0}
    fixed = [block("before", "09:00", "10:00", location_id="MC"),
             block("after", "11:00", "12:00", location_id="MC")]
    gym = task(location_id="PAC", location_mode="preferred", min_session_minutes=30, max_session_minutes=30,
               allow_alternative_locations=True, alternative_location_ids=["MC"])
    result = generate(tasks=[gym], blocks=fixed, settings=settings)
    assert result["status"] == "optimal", result["conflicts"]
    chunks = [b for b in result["blocks"] if b.get("task_id")]
    assert len(chunks) == 2
    assert all(b["location_id"] == "PAC" and b["resolved_location_id"] == "MC"
               and b["allow_alternative_locations"] and b["alternative_location_ids"] == ["MC"] for b in chunks)


@pytest.mark.parametrize("status,locked", [("todo", True), ("in_progress", False), ("completed", False)])
def test_existing_protected_actual_venue_survives_without_reauthorizing_it(status, locked):
    recorded = block("recorded", "10:00", "11:00", location_id="PAC", location_mode="preferred",
                     resolved_location_id="MC", status=status, locked=locked, rationale="Original evidence")
    result = generate(blocks=[recorded])
    assert result["status"] == "optimal", result["conflicts"]
    assert next(b for b in result["blocks"] if b["id"] == "recorded") == recorded
    assert any("explicitly permitted" in error for error in validate_blocks([recorded], SETTINGS, lambda a, b: 10))
    assert validate_blocks([recorded], SETTINGS, lambda a, b: 10, protected_blocks=[recorded]) == []


def test_trusted_history_matches_equivalent_time_serialization_and_optional_defaults():
    recorded = block("recorded", "10:00", "11:00", location_id="PAC", location_mode="preferred",
                     resolved_location_id="MC", status="completed")
    recorded.update(start="2026-11-10T15:00Z", end="2026-11-10T16:00Z")
    serialized = {**recorded, "start": "2026-11-10T15:00:00+00:00", "end": "2026-11-10T16:00:00+00:00",
                  "allow_alternative_locations": False, "alternative_location_ids": [], "description": "", "room": ""}
    assert validate_blocks([serialized], SETTINGS, lambda a, b: 10, protected_blocks=[recorded]) == []
    serialized["resolved_location_id"] = "unauthorized"
    assert any("explicitly permitted" in error for error in validate_blocks([serialized], SETTINGS, lambda a, b: 10, protected_blocks=[recorded]))


@pytest.mark.parametrize("start_home,end_home,walks", [(False, False, 0), (True, False, 1), (False, True, 1), (True, True, 2)])
def test_home_boundaries_are_independent_opt_in(start_home, end_home, walks):
    settings = {**SETTINGS, "home_location_id": "home", "start_at_home": start_home, "end_at_home": end_home}
    result = generate(classes=[cls(location_id="campus")], settings=settings)
    assert result["status"] == "optimal"
    assert len([b for b in result["blocks"] if b["kind"] == "travel"]) == walks
    assert not validate_blocks(result["blocks"], settings, lambda a, b: 10)


def test_disabled_home_and_legacy_default_do_not_fetch_routes():
    def no_route(a, b):
        raise AssertionError("Unrequested home/default route lookup")
    result = generate(classes=[cls(location_id="campus")], settings={**SETTINGS, "home_location_id": "home"}, route=no_route)
    assert result["status"] == "optimal"


def test_zero_callback_cannot_teleport_distinct_known_locations():
    settings = {**SETTINGS, "travel_buffer_minutes": 0}
    impossible = generate(classes=[cls(location_id="A"), cls("b", "10:00", "11:00", location_id="B")], settings=settings, route=lambda a, b: 0)
    assert impossible["status"] == "infeasible"
    same = generate(classes=[cls(location_id="A"), cls("b", "10:00", "11:00", location_id="A")], settings=settings, route=lambda a, b: 0)
    assert same["status"] == "optimal"


def test_home_arrival_is_checked_across_remote_event_and_midnight_sleep():
    settings = {**SETTINGS, "sleep_time": "00:00", "home_location_id": "home", "end_at_home": True, "travel_buffer_minutes": 0}
    fixed = [block("campus", "21:00", "22:00", location_id="campus"), block("remote", "22:00", "23:55", location_mode="remote", location_id=None)]
    assert generate(blocks=fixed, settings=settings, route=lambda a, b: 15)["status"] == "infeasible"
    assert any("home" in error for error in validate_blocks(fixed, settings, lambda a, b: 15))


@pytest.mark.parametrize("status,locked", [("todo", True), ("in_progress", False), ("completed", False)])
def test_protected_preferred_session_keeps_its_actual_position(status, locked):
    fixed = [block("before", "09:00", "10:00", location_id="A"),
             block("recorded", "10:00", "11:00", location_id="B", location_mode="preferred", resolved_location_id="B", status=status, locked=locked)]
    result = generate(blocks=fixed)
    assert result["status"] == "infeasible"


def test_incomplete_manual_walk_cannot_clear_physical_position():
    edits = [block("a", "09:00", "10:00", location_id="A"),
             block("bad-walk", "10:00", "10:05", kind="travel", location_id=None),
             block("b", "10:05", "11:00", location_id="B")]
    assert any("known origin" in error for error in validate_blocks(edits, SETTINGS, lambda a, b: 30))
    assert generate(blocks=edits)["status"] == "infeasible"
