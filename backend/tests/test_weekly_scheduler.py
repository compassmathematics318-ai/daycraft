"""Real weekly/daily CP-SAT tests for soft targets and logical-session work."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from backend.app.scheduler import generate_schedule
from backend.app.weekly_scheduler import (
    finalize_weekly_result, internalize_weekly_blocks, prepare_weekly_tasks,
    validate_weekly_blocks,
)

DATE = "2026-11-14"  # Saturday, so a one-day forecast is the whole remaining week.
WEEK = "2026-11-08"
SETTINGS = {"timezone": "America/Toronto", "wake_time": "07:00", "sleep_time": "23:00",
            "work_start": "08:00", "work_end": "10:00", "break_minutes": 0,
            "travel_buffer_minutes": 0, "focus_minutes": 50, "default_location_id": None,
            "meals": [], "solver_seconds": 2, "weekly_solver_seconds": 2}


def definition(id="d", **overrides):
    return {"id": id, "title": id, "task_type": "academic", "session_minutes": 60,
            "importance": 5, "difficulty": 5, "allow_splitting": False,
            "min_chunk_minutes": None, "dependencies": [], **overrides}


def assignment(id="a", task_definition_id="d", minimum=1, **overrides):
    return {"id": id, "task_definition_id": task_definition_id, "week_start": WEEK,
            "min_sessions_per_week": minimum, "status": "todo", **overrides}


def prepare(definitions=None, assignments=None, sessions=None, days=None, chunks=None, date=DATE, settings=None):
    return prepare_weekly_tasks(date, settings or SETTINGS, definitions or [definition()],
                                assignments if assignments is not None else [assignment()], sessions or [],
                                {"days": days if days is not None else [{"date": date, "capacity_minutes": 120}],
                                 "chunks": chunks or []})


def generate(prepared, settings=None, blocks=None, mode="balanced"):
    settings = settings or SETTINGS
    result = generate_schedule(prepared["date"], settings, [], prepared["tasks"] + prepared.get("_daily_task_limits", []),
                               internalize_weekly_blocks(blocks or [], prepared), lambda a, b: 0, mode)
    return finalize_weekly_result(result, prepared)


def work(result):
    return [block for block in result["blocks"] if block.get("logical_session_id")]


def test_week_availability_override_cannot_reopen_completed_definition():
    week = assignment(overrides={"status": "active"}, allow_inactive=True)
    closed = prepare(definitions=[definition(status="completed", importance=10)], assignments=[week])
    assert closed["tasks"] == []
    assert work(generate(closed)) == []
    reopened = prepare(definitions=[definition(status="active", importance=10)], assignments=[week])
    assert work(generate(reopened))


@pytest.mark.parametrize("deleted,removed", [(True, False), (False, True)])
def test_lifecycle_tombstones_cannot_schedule_despite_active_override(deleted, removed):
    source = definition(importance=10, status="active", deleted_at="2026-11-12T12:00:00Z" if deleted else None)
    week = assignment(overrides={"status": "active"}, allow_inactive=True, removed_from_week=removed)
    prepared = prepare(definitions=[source], assignments=[week])
    assert prepared["tasks"] == []
    assert work(generate(prepared)) == []
    assert prepared["weekly_progress"][0]["excluded"]


@pytest.mark.parametrize("status,locked", [("completed", True), ("in_progress", False), ("todo", False)])
def test_regeneration_keeps_withdrawn_history_without_creating_new_work(status, locked):
    completed = {"id": "historical", "title": "Deleted task's recorded work", "kind": "task",
                 "start": f"{DATE}T08:00:00-05:00", "end": f"{DATE}T09:00:00-05:00",
                 "task_id": "d", "task_definition_id": "d", "task_assignment_id": "a",
                 "logical_session_id": "history-session", "status": status, "locked": locked,
                 "location_mode": "remote", "location_id": None, "_withdrawn_history": True}
    prepared = prepare(definitions=[definition(deleted_at="2026-11-12T12:00:00Z")],
                       assignments=[assignment(removed_from_week=True, status="skipped")])
    # Service supplies this non-schedulable validation unit for trusted saved work.
    prepared["tasks"].append({"id": "session:history-session", "logical_session_id": "history-session",
                              "task_definition_id": "d", "task_assignment_id": "a", "title": completed["title"],
                              "status": "skipped", "history_only": True, "remaining_minutes": 60,
                              "duration_minutes": 60, "splittable": False, "dependencies": [],
                              "location_mode": "remote", "location_id": None})
    result = generate(prepared, blocks=[completed])
    assert len(work(result)) == 1
    assert all(work(result)[0][key] == completed[key] for key in completed)
    assert all(unit.get("history_only") for unit in prepared["tasks"])


def minutes(block):
    return round((datetime.fromisoformat(block["end"]) - datetime.fromisoformat(block["start"])).total_seconds() / 60)


def test_weekly_preparation_retains_explicit_venue_permission_and_week_override():
    source = definition(location_id="PAC", location_mode="preferred")
    override = {"allow_alternative_locations": True, "alternative_location_ids": ["other-gym"]}
    prepared = prepare(definitions=[source], assignments=[assignment(overrides=override)])
    assert prepared["tasks"]
    assert all(unit["location_id"] == "PAC" and unit["allow_alternative_locations"]
               and unit["alternative_location_ids"] == ["other-gym"] for unit in prepared["tasks"])
    assert source.get("allow_alternative_locations") is None
    default = prepare(definitions=[source])
    assert all(not unit["allow_alternative_locations"] and unit["alternative_location_ids"] == [] for unit in default["tasks"])


def test_weekly_units_and_split_chunks_preserve_verified_suitability():
    suitability = {"requirements": ["quiet"], "source": "explicit", "confidence": "high",
                   "candidates": [{"location_id": "library", "source": "selected", "confidence": "high", "evidence": "Selected venue"},
                                  {"location_id": "other-library", "source": "verified_capabilities", "confidence": "high", "evidence": "Quiet study space; access confirmed"}],
                   "limitation": ""}
    source = definition(location_id="library", location_mode="preferred", allow_splitting=True,
                        min_chunk_minutes=30, location_requirements=["quiet"], location_suitability=suitability)
    settings = {**SETTINGS, "work_end": "09:30"}
    prepared = prepare(definitions=[source], settings=settings)
    assert prepared["tasks"][0]["location_suitability"] == suitability
    barrier = {"id": "meeting", "title": "meeting", "kind": "class", "location_mode": "required",
               "location_id": "other-library", "locked": True,
               "start": f"{DATE}T08:30:00-05:00", "end": f"{DATE}T09:00:00-05:00"}
    raw = generate_schedule(DATE, settings, [], prepared["tasks"], [barrier], lambda a, b: 30)
    result = finalize_weekly_result(raw, prepared)
    assert result["status"] == "optimal", result["conflicts"]
    assert len(work(result)) == 2
    assert all(b["resolved_location_id"] == "other-library" and b["location_suitability"] == suitability for b in work(result))
    assert not validate_weekly_blocks(result["blocks"], settings, lambda a, b: 30, prepared)
    assert source["location_suitability"] == suitability


def test_daily_maximum_limits_forecast_and_underlying_definition_across_units():
    prepared = prepare(definitions=[definition(session_minutes=30, importance=10, max_sessions_per_day=1)],
                       assignments=[assignment(minimum=4)])
    result = generate(prepared)
    assert len(work(result)) == 1
    assert prepared["weekly_progress"][0]["expected_sessions"] == 1
    assert result["weekly_progress"][0]["expected_sessions"] == 1
    assert result["daily_progress"][0]["maximum_sessions"] == 1


def test_daily_maximum_cannot_be_bypassed_by_splitting_one_logical_session():
    prepared = prepare(definitions=[definition(session_minutes=90, allow_splitting=True,
                                               min_chunk_minutes=30, max_sessions_per_day=1)])
    barrier = {"id": "meeting", "title": "meeting", "kind": "class", "locked": True,
               "start": f"{DATE}T08:30:00-05:00", "end": f"{DATE}T09:00:00-05:00"}
    result = generate(prepared, blocks=[barrier])
    assert len(work(result)) == 1
    assert minutes(work(result)[0]) <= 60
    assert result["weekly_progress"][0]["expected_sessions"] == 0
    assert result["weekly_progress"][0]["expected_shortfall"] == 1


def test_forecast_counts_every_reserved_chunk_by_date_including_completed_history():
    sessions = [{"id": "old", "assignment_id": "a", "index": 0, "target_minutes": 60,
                 "completed_minutes": 60, "status": "completed"}]
    chunks = [{"id": "first", "logical_session_id": "old", "status": "completed",
               "start": f"{DATE}T08:00:00-05:00", "end": f"{DATE}T08:30:00-05:00"},
              {"id": "second", "logical_session_id": "old", "status": "completed",
               "start": f"{DATE}T09:00:00-05:00", "end": f"{DATE}T09:30:00-05:00"}]
    prepared = prepare(definitions=[definition(max_sessions_per_day=2)], assignments=[assignment(minimum=2)],
                       sessions=sessions, chunks=chunks)
    assert prepared["tasks"] == []
    assert prepared["weekly_progress"][0]["expected_sessions"] == 1
    assert prepared["weekly_progress"][0]["expected_shortfall"] == 1
    chunks[1]["status"] = "skipped"
    prepared = prepare(definitions=[definition(max_sessions_per_day=2)], assignments=[assignment(minimum=2)],
                       sessions=sessions, chunks=chunks)
    assert len(prepared["tasks"]) == 1


def test_forecast_daily_maximum_is_independent_for_each_remaining_date():
    days = [{"date": "2026-11-13", "capacity_minutes": 120}, {"date": DATE, "capacity_minutes": 120}]
    prepared = prepare(date="2026-11-13", definitions=[definition(max_sessions_per_day=1)],
                       assignments=[assignment(minimum=3)], days=days)
    assert len(prepared["tasks"]) == 1
    assert prepared["weekly_progress"][0]["expected_sessions"] == 2


def test_effective_week_overrides_daily_limits_and_room_in_solver_units():
    prepared = prepare(definitions=[definition(min_sessions_per_day=1, max_sessions_per_day=5, room="old")],
                       assignments=[assignment(minimum=3, overrides={"min_sessions_per_day": 2,
                                                                   "max_sessions_per_day": 2, "room": "402"})])
    assert all(item["min_sessions_per_day"] == 2 and item["max_sessions_per_day"] == 2
               for item in prepared["tasks"])
    result = generate(prepared)
    assert len(work(result)) == 2
    assert all(item["room"] == "402" for item in work(result))
    assert result["daily_progress"][0]["expected_shortfall"] == 0


def test_weekly_daily_minimum_does_not_manufacture_zero_goal_filler():
    prepared = prepare(definitions=[definition(importance=1, min_sessions_per_day=3)],
                       assignments=[assignment(minimum=0)])
    assert prepared["tasks"] == []
    assert work(generate(prepared)) == []


def test_conditional_daily_minimum_can_batch_unsplittable_weekly_sessions():
    days = [{"date": "2026-11-13", "capacity_minutes": 120}, {"date": DATE, "capacity_minutes": 120}]
    prepared = prepare(date="2026-11-13", definitions=[definition(min_sessions_per_day=2)],
                       assignments=[assignment(minimum=2)], days=days)
    # Both required sessions belong together on one day; a zero-work day has
    # no minimum. Existing weekly work is batched without adding filler.
    assert prepared["weekly_progress"][0]["expected_sessions"] == 2
    assert len(prepared["tasks"]) in {0, 2}
    if prepared["tasks"]:
        result = generate(prepared)
        assert len(work(result)) == 2
        assert result["daily_progress"][0]["expected_shortfall"] == 0


def test_manual_weekly_validation_aggregates_distinct_logical_units():
    prepared = prepare(definitions=[definition(session_minutes=30, max_sessions_per_day=1)],
                       assignments=[assignment(minimum=2)])
    sessions = prepared["sessions"]
    blocks = [{"id": str(i), "title": "d", "kind": "task", "task_id": "d", "task_definition_id": "d",
               "logical_session_id": session["id"], "status": "completed" if i == 0 else "todo",
               "start": f"{DATE}T0{8 + i}:00:00-05:00", "end": f"{DATE}T0{8 + i}:30:00-05:00"}
              for i, session in enumerate(sessions[:2])]
    assert any("daily maximum" in error for error in validate_weekly_blocks(blocks, SETTINGS, lambda a, b: 0, prepared))


def test_unassigned_definitions_never_create_work():
    prepared = prepare(assignments=[])
    assert prepared["tasks"] == []
    assert prepared["sessions"] == []
    assert work(generate(prepared)) == []


def test_preferred_weekday_moves_flexible_work_without_becoming_a_hard_constraint():
    task = definition(preferred_days=[0])
    days = [{"date": "2026-11-08", "capacity_minutes": 120}, {"date": "2026-11-09", "capacity_minutes": 120}]
    sunday = prepare(definitions=[task], date="2026-11-08", days=days)
    assert sunday["tasks"] == []
    monday = prepare(definitions=[task], date="2026-11-09", days=days[1:])
    assert monday["tasks"]
    assert prepare(definitions=[task])["tasks"]  # Saturday is still eligible.


def test_task_time_preference_reaches_daily_solver():
    settings = {**SETTINGS, "work_end": "22:00"}
    prepared = prepare(definitions=[definition(preferred_time_of_day="evening")], settings=settings,
                       days=[{"date": DATE, "capacity_minutes": 840}])
    result = generate(prepared, settings=settings)
    assert work(result)
    assert all(datetime.fromisoformat(block["start"]).hour >= 17 for block in work(result))


def test_zero_minimum_low_importance_does_not_create_filler():
    prepared = prepare(definitions=[definition(importance=2)], assignments=[assignment(minimum=0)])
    assert prepared["tasks"] == []
    assert prepared["sessions"] == []
    assert work(generate(prepared)) == []


def test_high_importance_can_earn_more_than_minimum_with_diminishing_extras():
    prepared = prepare(definitions=[definition(importance=10, session_minutes=30)])
    result = generate(prepared)
    assert len({block["logical_session_id"] for block in work(result)}) > 1
    assert len({block["logical_session_id"] for block in work(result)}) <= 4
    assert result["weekly_progress"][0]["minimum_sessions"] == 1
    assert result["weekly_progress"][0]["expected_sessions"] > 1


def test_urgent_competing_work_can_leave_minimum_unmet():
    definitions = [definition("routine", importance=1),
                   definition("urgent", importance=10, due_at=f"{DATE}T09:00:00-05:00")]
    assignments = [assignment("r", "routine", minimum=3), assignment("u", "urgent")]
    prepared = prepare(definitions=definitions, assignments=assignments,
                       days=[{"date": DATE, "capacity_minutes": 60}])
    result = generate(prepared, settings={**SETTINGS, "work_end": "09:00"})
    assert {block["task_id"] for block in work(result)} == {"urgent"}
    routine = next(item for item in result["weekly_progress"] if item["assignment_id"] == "r")
    assert routine["expected_shortfall"] == 3


@pytest.mark.parametrize("duration", [1, 7, 137])
def test_exact_positive_integer_duration_is_not_rounded(duration):
    settings = {**SETTINGS, "work_end": "12:00"}
    prepared = prepare(definitions=[definition(session_minutes=duration)], settings=settings,
                       days=[{"date": DATE, "capacity_minutes": 240}])
    result = generate(prepared, settings=settings)
    assert sum(minutes(block) for block in work(result)) == duration
    assert result["conflicts"] == []
    assert not validate_weekly_blocks(result["blocks"], settings, lambda a, b: 0, prepared)


@pytest.mark.parametrize("duration", [10000, 9007199254740991])
def test_physically_impossible_duration_reports_shortfall_without_solver_overflow(duration):
    prepared = prepare(definitions=[definition(session_minutes=duration)])
    assert prepared["tasks"] == []
    assert prepared["weekly_progress"][0]["expected_shortfall"] == 1
    assert prepared["weekly_progress"][0]["solver_status"] == "OPTIMAL"


def test_huge_minimum_is_capacity_bounded_and_reports_full_shortfall():
    prepared = prepare(assignments=[assignment(minimum=9007199254740991)])
    assert len(prepared["sessions"]) <= 2
    assert prepared["weekly_progress"][0]["expected_shortfall"] >= 9007199254740989
    assert prepared["weekly_progress"][0]["solver_status"] == "OPTIMAL"


def test_weekly_pacing_uses_other_days_instead_of_all_targets_today():
    dates = [(datetime.fromisoformat(WEEK) + timedelta(days=i)).date().isoformat() for i in range(7)]
    prepared = prepare(assignments=[assignment(minimum=3)], date=WEEK,
                       days=[{"date": day, "capacity_minutes": 120} for day in dates])
    assert prepared["weekly_progress"][0]["expected_sessions"] == 3
    assert 0 < sum(unit["remaining_minutes"] for unit in prepared["tasks"]) < 180


def test_urgent_cutoff_today_is_not_deferred_to_future_capacity():
    prepared = prepare(definitions=[definition(due_at=f"{WEEK}T09:00:00-05:00")], date=WEEK,
                       days=[{"date": WEEK, "capacity_minutes": 60}, {"date": "2026-11-09", "capacity_minutes": 840}])
    assert sum(unit["remaining_minutes"] for unit in prepared["tasks"]) == 60


def test_partial_progress_and_other_day_reservation_are_not_double_counted():
    session = {"id": "s", "assignment_id": "a", "index": 0, "target_minutes": 60,
               "completed_minutes": 20, "status": "in_progress"}
    chunks = [{"id": "done", "logical_session_id": "s", "start": "2026-11-08T08:00:00-05:00",
               "end": "2026-11-08T08:20:00-05:00", "status": "completed"},
              {"id": "future", "logical_session_id": "s", "start": "2026-11-10T08:00:00-05:00",
               "end": "2026-11-10T08:40:00-05:00", "status": "todo"}]
    prepared = prepare(sessions=[session], date="2026-11-09", chunks=chunks,
                       days=[{"date": "2026-11-09", "capacity_minutes": 120}])
    assert prepared["tasks"] == []
    assert prepared["weekly_progress"][0]["completed_sessions"] == 0
    assert prepared["weekly_progress"][0]["expected_sessions"] == 1


def test_partial_session_is_not_a_completed_session_until_target_reached():
    session = {"id": "s", "assignment_id": "a", "index": 0, "target_minutes": 60,
               "completed_minutes": 20, "status": "in_progress"}
    prepared = prepare(definitions=[definition(allow_splitting=True, min_chunk_minutes=20)], sessions=[session],
                       days=[{"date": DATE, "capacity_minutes": 20}])
    result = generate(prepared, settings={**SETTINGS, "work_end": "08:20"})
    assert sum(minutes(block) for block in work(result)) == 20
    assert result["weekly_progress"][0]["completed_sessions"] == 0
    assert result["weekly_progress"][0]["expected_sessions"] == 0
    assert result["weekly_progress"][0]["expected_shortfall"] == 1


def test_split_chunks_share_one_logical_session_and_external_definition_id():
    settings = {**SETTINGS, "work_end": "09:40"}
    prepared = prepare(definitions=[definition(allow_splitting=True, min_chunk_minutes=20)], settings=settings,
                       days=[{"date": DATE, "capacity_minutes": 60}])
    fixed = {"id": "class", "title": "Class", "kind": "class", "locked": True,
             "start": f"{DATE}T08:20:00-05:00", "end": f"{DATE}T09:00:00-05:00", "location_id": None}
    result = generate(prepared, settings=settings, blocks=[fixed])
    assert sorted(minutes(block) for block in work(result)) == [20, 40]
    assert len({block["logical_session_id"] for block in work(result)}) == 1
    assert {block["task_id"] for block in work(result)} == {"d"}
    assert {block["chunk_index"] for block in work(result)} == {0, 1}
    assert result["weekly_progress"][0]["completed_sessions"] == 0
    assert result["weekly_progress"][0]["expected_sessions"] == 1
    assert not validate_weekly_blocks(result["blocks"], settings, lambda a, b: 0, prepared)


def test_actual_daily_conflicts_correct_optimistic_weekly_forecast():
    prepared = prepare(days=[{"date": DATE, "capacity_minutes": 60}])
    fixed = {"id": "class", "title": "Class", "kind": "class", "locked": True,
             "start": f"{DATE}T08:00:00-05:00", "end": f"{DATE}T09:00:00-05:00", "location_id": None}
    result = generate(prepared, settings={**SETTINGS, "work_end": "09:00"}, blocks=[fixed])
    assert work(result) == []
    assert result["weekly_progress"][0]["expected_shortfall"] == 1


def test_dates_remain_separate_and_earliest_cutoff_wins():
    item = definition(session_minutes=30, due_at=f"{DATE}T10:00:00-05:00",
                      assessment_at=f"{DATE}T09:00:00-05:00", earliest_start=f"{DATE}T08:30:00-05:00")
    original = deepcopy(item)
    prepared = prepare(definitions=[item])
    result = generate(prepared)
    assert sum(minutes(block) for block in work(result)) == 30
    assert all(block["start"] >= item["earliest_start"] and block["end"] <= item["assessment_at"] for block in work(result))
    assert item == original


@pytest.mark.parametrize("status,override", [("paused", False), ("archived", False), ("paused", True)])
def test_project_status_and_explicit_override_control_new_weekly_work(status, override):
    item = definition(project_id="p", project={"id": "p", "importance": 5, "status": status},
                      schedule_inactive_project=override)
    result = generate(prepare(definitions=[item]))
    assert bool(work(result)) is override


def test_legacy_finite_session_does_not_spawn_extra_work():
    item = definition(importance=10, legacy_task_id="legacy", finite_work_minutes=60)
    prepared = prepare(definitions=[item])
    assert len(prepared["sessions"]) == 1
    assert sum(minutes(block) for block in work(generate(prepared))) == 60


def test_assignment_duration_snapshot_survives_definition_duration_edit():
    prepared = prepare(definitions=[definition(session_minutes=137)],
                       assignments=[assignment(session_minutes=7)])
    assert prepared["sessions"][0]["target_minutes"] == 7
    assert sum(minutes(block) for block in work(generate(prepared))) == 7


def test_paused_logical_session_receives_no_new_chunks():
    session = {"id": "paused", "assignment_id": "a", "index": 0, "target_minutes": 60,
               "completed_minutes": 20, "status": "paused"}
    prepared = prepare(sessions=[session])
    assert prepared["tasks"] == []
    assert prepared["weekly_progress"][0]["expected_shortfall"] == 1


def test_one_minute_sessions_include_recovery_and_grid_capacity():
    settings = {**SETTINGS, "break_minutes": 10, "work_end": "09:00"}
    prepared = prepare(definitions=[definition(session_minutes=1)], settings=settings,
                       assignments=[assignment(minimum=100)], days=[{"date": DATE, "capacity_minutes": 60}])
    assert prepared["weekly_progress"][0]["expected_sessions"] <= 4
    assert prepared["weekly_progress"][0]["expected_shortfall"] >= 96
    result = generate(prepared, settings=settings)
    assert result["conflicts"] == []
    assert len(work(result)) <= 4
    assert not validate_weekly_blocks(result["blocks"], settings, lambda a, b: 0, prepared)


def test_index_holes_do_not_remove_unmet_minimum_utility():
    session = {"id": "retained", "assignment_id": "a", "index": 8, "target_minutes": 60,
               "completed_minutes": 0, "status": "todo"}
    prepared = prepare(definitions=[definition(importance=1)], sessions=[session])
    assert sum(minutes(block) for block in work(generate(prepared))) == 60
    assert prepared["weekly_progress"][0]["expected_shortfall"] == 0


def test_nonacademic_type_ignores_preserved_academic_dates():
    item = definition(task_type="personal", due_at="2025-01-01T09:00:00-05:00",
                      assessment_at="2025-01-02T09:00:00-05:00")
    result = generate(prepare(definitions=[item]))
    assert sum(minutes(block) for block in work(result)) == 60


def test_dependency_work_finishes_before_dependent_session():
    definitions = [definition("pre"), definition("post", dependencies=["pre"])]
    assignments = [assignment("p", "pre"), assignment("q", "post")]
    prepared = prepare(definitions=definitions, assignments=assignments)
    result = generate(prepared)
    before = [block for block in work(result) if block["task_id"] == "pre"]
    after = [block for block in work(result) if block["task_id"] == "post"]
    assert before and after
    assert max(block["end"] for block in before) <= min(block["start"] for block in after)
    assert not validate_weekly_blocks(result["blocks"], SETTINGS, lambda a, b: 0, prepared)


@pytest.mark.parametrize("cycle", [False, True])
def test_unavailable_or_cyclic_dependencies_cannot_create_work(cycle):
    definitions = [definition("a", dependencies=["b"])]
    assignments = [assignment("aa", "a")]
    if cycle:
        definitions.append(definition("b", dependencies=["a"]))
        assignments.append(assignment("bb", "b"))
    prepared = prepare(definitions=definitions, assignments=assignments)
    assert prepared["tasks"] == []
    assert all(item["expected_shortfall"] == 1 for item in prepared["weekly_progress"])


def test_weekly_dependency_cannot_release_before_partial_prerequisite_is_finished():
    definitions = [definition("pre", allow_splitting=True, min_chunk_minutes=20),
                   definition("post", dependencies=["pre"], session_minutes=20)]
    assignments = [assignment("p", "pre"), assignment("q", "post")]
    prepared = prepare(definitions=definitions, assignments=assignments, date=WEEK,
                       days=[{"date": WEEK, "capacity_minutes": 20}, {"date": "2026-11-09", "capacity_minutes": 60}])
    assert all(unit["task_definition_id"] != "post" for unit in prepared["tasks"])


@pytest.mark.parametrize("mode", ["balanced", "deadline", "deep"])
def test_modes_preserve_exact_session_duration_and_hard_cutoff(mode):
    item = definition(session_minutes=7, due_at=f"{DATE}T08:10:00-05:00", difficulty=10)
    prepared = prepare(definitions=[item])
    result = generate(prepared, mode=mode)
    assert sum(minutes(block) for block in work(result)) == 7
    assert all(block["end"] <= item["due_at"] for block in work(result))
    assert result["conflicts"] == []


def test_soft_general_deadline_keeps_urgency_but_allows_later_work():
    item = definition(task_type="personal", hard_deadline=False,
                      deadline_at="2026-11-13T17:00:00-05:00")
    result = generate(prepare(definitions=[item]))
    assert sum(minutes(block) for block in work(result)) >= 60
    assert result["conflicts"] == []


def test_assessment_cutoff_remains_hard_when_due_date_is_soft():
    item = definition(hard_deadline=False, due_at="2026-11-13T17:00:00-05:00",
                      assessment_at=f"{DATE}T08:30:00-05:00")
    prepared = prepare(definitions=[item])
    assert prepared["tasks"] == []
    assert prepared["weekly_progress"][0]["expected_shortfall"] == 1


def test_week_metadata_overrides_are_local_and_null_clears_inherited_cutoff():
    source = definition(title="Recurring reading", importance=2, difficulty=1,
                        due_at="2026-11-01T08:00:00-05:00")
    original = deepcopy(source)
    week = assignment(overrides={"title": "Read chapter 8", "importance": 5,
                                 "difficulty": 9, "due_at": None,
                                 "assessment_at": f"{DATE}T09:00:00-05:00"})
    prepared = prepare(definitions=[source], assignments=[week])
    result = generate(prepared)
    assert sum(minutes(block) for block in work(result)) == 60
    assert {block["title"] for block in work(result)} == {"Read chapter 8"}
    assert all(block["end"] <= week["overrides"]["assessment_at"] for block in work(result))
    assert prepared["tasks"][0]["difficulty"] == 9
    assert prepared["tasks"][0].get("due_at") is None
    assert source == original
    other_week = prepare(definitions=[source])
    assert other_week["tasks"] == []


def test_week_specific_dependency_override_is_enforced_in_both_models():
    definitions = [definition("pre"), definition("post")]
    assignments = [assignment("p", "pre"),
                   assignment("q", "post", overrides={"dependencies": ["pre"]})]
    prepared = prepare(definitions=definitions, assignments=assignments)
    post = next(unit for unit in prepared["tasks"] if unit["task_definition_id"] == "post")
    assert post["dependencies"]
    result = generate(prepared)
    before = [block for block in work(result) if block["task_id"] == "pre"]
    after = [block for block in work(result) if block["task_id"] == "post"]
    assert before and after
    assert max(block["end"] for block in before) <= min(block["start"] for block in after)


def test_recurring_and_explicit_work_share_daily_capacity_and_public_identity():
    definitions = [definition("recurring", session_minutes=30),
                   definition("one-off", session_minutes=30)]
    assignments = [assignment("recurring:d:2026-11-08", "recurring", source="recurring"),
                   assignment("specific", "one-off", source="explicit")]
    prepared = prepare(definitions=definitions, assignments=assignments)
    result = generate(prepared)
    assert {block["task_id"] for block in work(result)} == {"recurring", "one-off"}
    assert sum(minutes(block) for block in work(result)) == 60
    assert {block["task_assignment_id"] for block in work(result)} == {item["id"] for item in assignments}
    assert prepare(definitions=definitions, assignments=assignments)["sessions"] == prepared["sessions"]


@pytest.mark.parametrize("status", ["paused", "completed", "skipped"])
def test_week_status_excludes_new_work_even_when_source_recurs(status):
    prepared = prepare(assignments=[assignment(source="recurring", status=status)])
    assert prepared["tasks"] == []
    assert prepared["weekly_progress"][0]["excluded"]


def test_completed_extra_sessions_reduce_remaining_extras_marginal_value():
    item = definition(importance=10, session_minutes=30)
    completed = [{"id": f"s{i}", "assignment_id": "a", "index": i,
                  "target_minutes": 30, "completed_minutes": 30, "status": "completed"}
                 for i in range(2)]
    prepared = prepare(definitions=[item], sessions=completed)
    # First completed session met the minimum; the second consumed the extra
    # worth 80/minute. Remaining extra work is worth 50 then 20, never reset.
    assert sorted(unit["weekly_value"] for unit in prepared["tasks"]) == [20, 50]
    result = generate(prepared)
    assert result["weekly_progress"][0]["expected_sessions"] == 4


def test_project_difficulty_does_not_raise_intrinsic_work_value_or_extra_count():
    low = definition(project_id="p", project={"id": "p", "importance": 5, "difficulty": 0})
    high = deepcopy(low)
    high["project"]["difficulty"] = 10
    first, second = prepare(definitions=[low]), prepare(definitions=[high])
    assert [unit["weekly_value"] for unit in first["tasks"]] == [unit["weekly_value"] for unit in second["tasks"]]
    assert len(first["sessions"]) == len(second["sessions"])



def test_week_assignment_location_policy_reaches_daily_session_and_preserves_source():
    source = definition(location_mode="required", location_id="A")
    prepared = prepare(definitions=[source], assignments=[assignment(overrides={"location_mode": "remote", "location_id": None})])
    assert prepared["tasks"][0]["location_mode"] == "remote"
    assert prepared["tasks"][0]["location_id"] is None
    result = generate(prepared)
    assert result["status"] == "optimal", result["conflicts"]
    assert work(result)[0]["location_mode"] == "remote"
    assert source["location_mode"] == "required" and source["location_id"] == "A"


def test_linked_assessment_changes_soft_competition_without_creating_cutoff():
    context = {"id": "exam", "category": "assessment", "title": "Algebra exam",
               "assessment_start": f"{DATE}T08:00:00-05:00", "occurrences": []}
    definitions = [definition("unlinked", importance=1),
                   definition("linked", importance=1, related_activity=context)]
    assignments = [assignment("a1", "unlinked"), assignment("a2", "linked")]
    settings = {**SETTINGS, "work_end": "09:00"}
    prepared = prepare(definitions=definitions, assignments=assignments, settings=settings,
                       days=[{"date": DATE, "capacity_minutes": 60}])
    result = generate(prepared, settings=settings)
    assert {block["task_id"] for block in work(result)} == {"linked"}
    assert work(result)[0]["start"] >= context["assessment_start"]
    assert "related assessment: Algebra exam" in work(result)[0]["rationale"]
    assert not validate_weekly_blocks(result["blocks"], settings, lambda a, b: 0, prepared)
    assert definitions[1].get("assessment_at") is None


def test_linked_assessment_bonus_is_bounded_and_never_overrides_explicit_cutoff():
    linked = {"category": "assessment", "title": "Exam",
              "assessment_start": f"{DATE}T08:30:00-05:00"}
    ordinary = prepare(definitions=[definition(importance=1)])
    contextual = prepare(definitions=[definition(importance=1, related_activity=linked)])
    assert 0 < contextual["tasks"][0]["weekly_value"] - ordinary["tasks"][0]["weekly_value"] <= 60
    blocked = prepare(definitions=[definition(importance=10, related_activity=linked,
                                               deadline_at=f"{DATE}T07:30:00-05:00")])
    assert work(generate(blocked)) == []
    assert blocked["weekly_progress"][0]["expected_shortfall"] == 1


@pytest.mark.parametrize("category,date", [("class", DATE), ("commitment", DATE),
                                          ("assessment", "2026-11-13"),
                                          ("assessment", "2026-12-01")])
def test_class_commitment_and_past_or_distant_assessment_are_context_only(category, date):
    linked = {"category": category, "title": "Context", "assessment_start": f"{date}T09:00:00-05:00"}
    ordinary = prepare(definitions=[definition()])
    contextual = prepare(definitions=[definition(related_activity=linked)])
    assert [task["weekly_value"] for task in contextual["tasks"]] == [task["weekly_value"] for task in ordinary["tasks"]]
    assert sum(minutes(block) for block in work(generate(contextual))) == 60


def test_allocated_minimum_with_elapsed_pending_work_allows_justified_extras_without_credit():
    session = {"id": "pending", "assignment_id": "a", "index": 0,
               "target_minutes": 30, "completed_minutes": 0, "status": "todo"}
    chunk = {"id": "elapsed", "logical_session_id": "pending", "status": "todo",
             "start": "2026-11-13T08:00:00-05:00", "end": "2026-11-13T08:30:00-05:00"}
    definitions = [definition(importance=10, session_minutes=30)]
    original = deepcopy((definitions, session, chunk))
    prepared = prepare(definitions=definitions, sessions=[session], chunks=[chunk])
    result = generate(prepared)
    assert work(result) and all(block["logical_session_id"] != "pending" for block in work(result))
    assert result["weekly_progress"][0]["completed_sessions"] == 0
    assert result["weekly_progress"][0]["expected_sessions"] > 1
    assert not result["weekly_progress"][0]["excluded"]
    assert (definitions, session, chunk) == original


def test_current_day_elapsed_pending_session_is_reserved_without_duplicate_units_or_credit():
    session = {"id": "pending", "assignment_id": "a", "index": 0,
               "target_minutes": 60, "completed_minutes": 0, "status": "todo"}
    chunk = {"id": "elapsed", "logical_session_id": "pending", "status": "todo", "preserve": True,
             "start": f"{DATE}T08:00:00-05:00", "end": f"{DATE}T09:00:00-05:00"}
    saved = {key: value for key, value in chunk.items() if key != "preserve"}
    saved.update(title="Saved work", kind="task", task_id="d", task_definition_id="d", task_assignment_id="a",
                 location_mode="remote", location_id=None, locked=False, rationale="Awaiting confirmation",
                 _elapsed_work_history=True)
    original = deepcopy((session, chunk, saved))
    prepared = prepare(definitions=[definition(location_mode="remote")], sessions=[session], chunks=[chunk])
    result = generate(prepared, blocks=[saved])
    assert result["status"] in {"optimal", "feasible"}
    assert [unit["logical_session_id"] for unit in prepared["tasks"]] == ["pending"]
    assert len(work(result)) == 1
    assert all(work(result)[0][key] == value for key, value in saved.items())
    assert result["weekly_progress"][0]["completed_sessions"] == 0
    assert result["weekly_progress"][0]["expected_sessions"] == 1
    assert (session, chunk, saved) == original


@pytest.mark.parametrize("confirmed", [False, True])
def test_partial_chunk_confirmation_and_undo_leave_only_unreserved_minutes_to_schedule(confirmed):
    session = {"id": "split", "assignment_id": "a", "index": 0,
               "target_minutes": 60, "completed_minutes": 30 if confirmed else 0,
               "status": "in_progress" if confirmed else "todo"}
    saved = [{"id": "first", "title": "First chunk", "kind": "task", "task_id": "d",
              "task_definition_id": "d", "task_assignment_id": "a", "logical_session_id": "split",
              "chunk_index": 0, "start": f"{DATE}T08:00:00-05:00", "end": f"{DATE}T08:30:00-05:00",
              "status": "completed" if confirmed else "todo", "locked": False,
              "location_id": None, "location_mode": "remote", "_elapsed_work_history": True},
             {"id": "second", "title": "Second chunk", "kind": "task", "task_id": "d",
              "task_definition_id": "d", "task_assignment_id": "a", "logical_session_id": "split",
              "chunk_index": 1, "start": f"{DATE}T08:30:00-05:00", "end": f"{DATE}T08:45:00-05:00",
              "status": "todo", "locked": False, "location_id": None, "location_mode": "remote",
              "_elapsed_work_history": True}]
    if confirmed:
        saved[0].update(completion_confirmed_at=f"{DATE}T08:31:00-05:00",
                        completion_previous_status="todo", completion_verified=True)
    original = deepcopy((session, saved))
    chunks = [{**block, "preserve": True} for block in saved]
    prepared = prepare(definitions=[definition(location_mode="remote", allow_splitting=True,
                                               min_chunk_minutes=15, max_sessions_per_day=3)],
                       sessions=[session], chunks=chunks, days=[{"date": DATE, "capacity_minutes": 75}])
    result = generate(prepared, blocks=saved)
    assert result["status"] in {"optimal", "feasible"}
    assert {block["logical_session_id"] for block in work(result)} == {"split"}
    assert len(work(result)) == 3
    assert sum(minutes(block) for block in work(result)) == 60
    fresh = [block for block in work(result) if block["id"] not in {"first", "second"}]
    assert len(fresh) == 1 and minutes(fresh[0]) == 15
    for block in saved:
        retained = next(item for item in work(result) if item["id"] == block["id"])
        assert all(retained[key] == value for key, value in block.items())
    assert result["daily_progress"][0]["scheduled_sessions"] == 3
    assert result["weekly_progress"][0]["completed_sessions"] == 0
    assert result["weekly_progress"][0]["expected_sessions"] == 1
    assert (session, saved) == original


@pytest.mark.parametrize("importance,expect_extra", [(5, False), (10, True)])
def test_confirmed_minimum_keeps_history_and_allows_only_justified_new_logical_sessions(importance, expect_extra):
    session = {"id": "done", "assignment_id": "a", "index": 0,
               "target_minutes": 30, "completed_minutes": 30, "status": "completed"}
    saved = {"id": "confirmed", "title": "Completed work", "kind": "task", "task_id": "d",
             "task_definition_id": "d", "task_assignment_id": "a", "logical_session_id": "done",
             "start": f"{DATE}T08:00:00-05:00", "end": f"{DATE}T08:30:00-05:00",
             "status": "completed", "locked": False, "location_mode": "remote", "location_id": None,
             "completion_confirmed_at": f"{DATE}T08:31:00-05:00", "completion_previous_status": "todo",
             "completion_verified": True, "_elapsed_work_history": True}
    prepared = prepare(definitions=[definition(location_mode="remote", session_minutes=30, importance=importance)],
                       sessions=[session], chunks=[{**saved, "preserve": True}],
                       days=[{"date": DATE, "capacity_minutes": 90}])
    result = generate(prepared, blocks=[saved])
    assert result["status"] in {"optimal", "feasible"}
    assert all(unit["logical_session_id"] != "done" for unit in prepared["tasks"])
    retained = next(block for block in work(result) if block["id"] == "confirmed")
    assert retained == saved
    extras = [block for block in work(result) if block["id"] != "confirmed"]
    assert bool(extras) == expect_extra
    assert all(block["logical_session_id"] != "done" for block in extras)
    assert result["weekly_progress"][0]["completed_sessions"] == 1


def test_week_completion_is_local_and_definition_completion_requires_explicit_reopening():
    definitions = [definition(importance=10)]
    weeks = [assignment(status="completed"),
             assignment("next", week_start="2026-11-15")]
    assert prepare(definitions=definitions, assignments=weeks)["tasks"] == []
    next_week = prepare(definitions=definitions, assignments=weeks, date="2026-11-15")
    assert next_week["tasks"]
    definitions[0]["status"] = "completed"
    assert prepare(definitions=definitions, assignments=weeks, date="2026-11-15")["tasks"] == []
    definitions[0]["status"] = "active"
    assert prepare(definitions=definitions, assignments=weeks, date="2026-11-15")["tasks"]


def test_linked_assessment_can_justify_extras_after_verified_minimum_without_closing_week():
    session = {"id": "done", "assignment_id": "a", "index": 0,
               "target_minutes": 30, "completed_minutes": 30, "status": "completed"}
    context = {"category": "assessment", "title": "Exam",
               "occurrences": [{"start": f"{DATE}T09:00:00-05:00"}]}
    prepared = prepare(definitions=[definition(session_minutes=30, importance=5, related_activity=context)],
                       sessions=[session])
    result = generate(prepared)
    assert work(result)
    assert result["weekly_progress"][0]["completed_sessions"] == 1
    assert result["weekly_progress"][0]["expected_sessions"] > 1
    assert not result["weekly_progress"][0]["excluded"]


@pytest.mark.parametrize("reserved_date", ["2026-11-12", DATE])
def test_reserved_prerequisite_target_does_not_become_verified_dependency_credit(reserved_date):
    definitions = [definition("pre", importance=1, session_minutes=30),
                   definition("post", importance=1, session_minutes=30, dependencies=["pre"])]
    assignments = [assignment("p", "pre"), assignment("q", "post")]
    session = {"id": "reserved", "assignment_id": "p", "index": 0,
               "target_minutes": 30, "completed_minutes": 0, "status": "todo"}
    chunk = {"id": "pending", "logical_session_id": "reserved", "status": "todo", "locked": True,
             "start": f"{reserved_date}T08:00:00-05:00", "end": f"{reserved_date}T08:30:00-05:00"}
    prepared = prepare(definitions=definitions, assignments=assignments, sessions=[session], chunks=[chunk])
    today_block = {**chunk, "title": "pre", "kind": "task", "task_id": "pre",
                   "task_definition_id": "pre", "task_assignment_id": "p"}
    result = generate(prepared, blocks=[today_block] if reserved_date == DATE else [])
    dependent = [block for block in work(result) if block["task_id"] == "post"]
    if reserved_date == DATE:
        # Pending prerequisite work in this proposed plan must precede its
        # dependent, while still receiving no verified completion credit.
        assert dependent and all(block["start"] >= chunk["end"] for block in dependent)
    else:
        # Elapsed pending coverage alone cannot bypass daily dependency checks.
        assert dependent == []
    pre_progress = next(item for item in result["weekly_progress"] if item["task_definition_id"] == "pre")
    assert pre_progress["completed_sessions"] == 0
    assert definitions[0].get("status") != "completed"
