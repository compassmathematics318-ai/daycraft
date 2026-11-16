"""Acceptance scenarios exercising the genuine Windows CP-SAT day optimizer."""
from copy import deepcopy
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.meal_planning import meal_requirements
from backend.app.scheduler import generate_schedule, validate_blocks
from backend.app.task_library import regeneration_blocks


DAY = "2026-11-12"
LEVELS = ["very_low", "low", "medium", "high", "very_high"]
SETTINGS = {"timezone": "America/Toronto", "wake_time": "07:00", "sleep_time": "23:00",
            "work_start": "08:00", "work_end": "20:00", "focus_minutes": 50,
            "break_minutes": 10, "travel_buffer_minutes": 0, "solver_seconds": 3,
            "meals": []}
MEALS = [{"id": "breakfast", "name": "Breakfast", "duration_minutes": 30},
         {"id": "lunch", "name": "Lunch", "duration_minutes": 45},
         {"id": "dinner", "name": "Dinner", "duration_minutes": 30}]


def task(id="work", **changes):
    return {"id": id, "title": id, "status": "todo", "priority": 3, "remaining_minutes": 60,
            "duration_minutes": 60, "splittable": False, "min_session_minutes": 25,
            "max_session_minutes": 90, "location_mode": "remote", "dependencies": [], **changes}


def fixed(id, start, end, **changes):
    return {"id": id, "title": id, "kind": "class", "locked": True, "status": "todo",
            "start": f"{DAY}T{start}:00-05:00", "end": f"{DAY}T{end}:00-05:00",
            "location_mode": "remote", "location_id": None, **changes}


def plan(tasks=(), blocks=(), settings=None, now=None, mode="balanced", route=None):
    return generate_schedule(DAY, {**SETTINGS, **(settings or {})}, [], list(tasks), list(blocks),
                             route or (lambda a, b: 15), mode, now)


def minutes(block):
    return round((datetime.fromisoformat(block["end"]) - datetime.fromisoformat(block["start"])).total_seconds() / 60)


def assert_valid(result, settings=None, tasks=None, protected=()):
    assert result["status"] in {"optimal", "feasible", "partial"}, result["conflicts"]
    assert result["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert validate_blocks(result["blocks"], {**SETTINGS, **(settings or {})}, lambda a, b: 15,
                           tasks, list(protected)) == []


def test_three_flexible_meals_keep_durations_order_and_breakfast_outside_work_window():
    settings = {"meals": deepcopy(MEALS)}
    source = [task()]
    result = plan(source, [fixed("morning", "09:00", "10:00"), fixed("midday", "12:00", "15:00")], settings)
    assert_valid(result, settings, source)
    meals = [block for block in result["blocks"] if block["kind"] == "meal"]
    assert [block["title"] for block in meals] == ["Breakfast", "Lunch", "Dinner"]
    assert [minutes(block) for block in meals] == [30, 45, 30]
    assert meals[0]["end"] <= f"{DAY}T08:00:00-05:00"
    assert all(block["start"] >= f"{DAY}T08:00:00-05:00" for block in result["blocks"] if block.get("task_id"))
    assert meals[1]["end"] <= f"{DAY}T12:00:00-05:00" or meals[1]["start"] >= f"{DAY}T15:00:00-05:00"
    assert settings["meals"] == MEALS


def test_legacy_meal_time_is_soft_and_custom_duration_is_preserved():
    settings = {"meals": [{"name": "Lunch", "time": "12:00", "duration_minutes": 65}]}
    result = plan(blocks=[fixed("class", "11:00", "14:00")], settings=settings)
    assert_valid(result, settings)
    meal = next(block for block in result["blocks"] if block["kind"] == "meal")
    assert minutes(meal) == 65
    assert meal["end"] <= f"{DAY}T11:00:00-05:00" or meal["start"] >= f"{DAY}T14:00:00-05:00"


def test_required_meal_cannot_silently_disappear_when_whole_awake_day_is_occupied():
    result = plan(blocks=[fixed("all-day", "07:00", "23:00")], settings={"meals": MEALS})
    assert result["status"] == "infeasible"
    assert result["conflicts"]
    assert "meal" in " ".join(result["conflicts"]).lower()


def test_remaining_day_does_not_invent_breakfast_completion_or_place_it_at_night():
    result = plan(settings={"meals": MEALS}, now=f"{DAY}T20:00:00-05:00")
    assert result["status"] == "infeasible"
    assert any("Breakfast" in conflict for conflict in result["conflicts"])
    assert not any(block.get("status") == "completed" for block in result["blocks"])


@pytest.mark.parametrize("status,locked", [("completed", False), ("in_progress", False), ("todo", True)])
def test_existing_meal_identity_and_history_survive_without_duplicate_allocation(status, locked):
    breakfast = fixed("eaten", "07:15", "07:45", kind="meal", title="Breakfast", meal_id="breakfast",
                      status=status, locked=locked, rationale="Original meal evidence")
    original = deepcopy(breakfast)
    result = plan(blocks=[breakfast], settings={"meals": MEALS}, now=f"{DAY}T11:00:00-05:00")
    assert_valid(result, {"meals": MEALS}, protected=[breakfast])
    assert next(block for block in result["blocks"] if block["id"] == "eaten") == original
    assert len([block for block in result["blocks"] if block["kind"] == "meal"]) == 3
    assert all(block["start"] >= f"{DAY}T11:00:00-05:00" for block in result["blocks"] if block["id"] != "eaten")


def test_duplicate_named_meal_definitions_keep_independent_ids_and_disabled_meal_is_omitted():
    meals = [{"id": "first", "name": "Snack", "duration_minutes": 15},
             {"id": "second", "name": "Snack", "duration_minutes": 20},
             {"id": "disabled", "name": "Snack", "duration_minutes": 30, "enabled": False}]
    result = plan(settings={"meals": meals})
    assert_valid(result, {"meals": meals})
    assert {block.get("meal_id") for block in result["blocks"]} == {"first", "second"}
    assert sorted(minutes(block) for block in result["blocks"]) == [15, 20]


def test_generated_legacy_meal_user_lock_survives_real_regeneration_and_edited_preferences():
    settings = {**SETTINGS, "meals": [{"name": "Snack", "duration_minutes": 15},
                                     {"name": "Snack", "duration_minutes": 20}]}
    before = deepcopy(settings)
    generated = plan(settings=settings)
    assert_valid(generated, settings)
    meals = [block for block in generated["blocks"] if block["kind"] == "meal"]
    assert len({block["meal_id"] for block in meals}) == 2
    locked = {**meals[0], "locked": True}
    settings["meals"][0].update(duration_minutes=25, time="11:00")
    ids_before = [item["definition"]["id"] for item in meal_requirements(before, [])]
    assert [item["definition"]["id"] for item in meal_requirements(settings, [])] == ids_before
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            preserved = regeneration_blocks(db, [locked, meals[1]], settings,
                                            datetime.fromisoformat(f"{DAY}T07:00:00-05:00"))
        assert preserved == [locked]
        regenerated = plan(blocks=preserved, settings=settings)
    finally:
        engine.dispose()
    assert_valid(regenerated, settings, protected=preserved)
    assert next(block for block in regenerated["blocks"] if block["id"] == locked["id"]) == locked
    assert len([block for block in regenerated["blocks"] if block["kind"] == "meal"]) == 2
    assert {block["meal_id"] for block in regenerated["blocks"] if block["kind"] == "meal"} == set(ids_before)


def test_meal_at_real_destination_reserves_actual_travel():
    result = plan(blocks=[fixed("class", "17:00", "18:00", location_mode="required", location_id="MC")],
                  settings={"meals": [{"name": "Dinner", "duration_minutes": 30, "location_id": "PAC", "time": "18:00"}]})
    assert_valid(result)
    meal = next(block for block in result["blocks"] if block["kind"] == "meal")
    assert meal["resolved_location_id"] == "PAC"
    walks = [block for block in result["blocks"] if block["kind"] == "travel"]
    assert any({block["origin_id"], block["destination_id"]} == {"MC", "PAC"} for block in walks)


@pytest.mark.parametrize("mode", ["balanced", "deadline", "deep"])
def test_all_five_workloads_change_useful_optional_inclusion_without_changing_strategy(mode):
    source = [task(str(index)) for index in range(10)]
    results = [plan(source, settings={"workload_level": level}, mode=mode) for level in LEVELS]
    allocated = []
    for result, level in zip(results, LEVELS, strict=True):
        assert_valid(result, {"workload_level": level}, source)
        assert result["mode"] == mode
        assert result["workload_level"] == level
        assert result["stats"]["workload_profile"]["level"] == level
        allocated.append(result["stats"]["allocated_minutes"])
    assert allocated == sorted(allocated)
    assert allocated[-1] > allocated[0]
    assert len(set(allocated)) >= 4


@pytest.mark.parametrize("level", LEVELS)
def test_workload_never_defers_feasible_immediate_deadline_for_soft_free_time(level):
    urgent = task("urgent", priority=1, deadline_at=f"{DAY}T10:00:00-05:00", task_type="academic")
    source = [urgent, task("discretionary", remaining_minutes=600, duration_minutes=600, splittable=True)]
    result = plan(source, settings={"workload_level": level})
    assert_valid(result, {"workload_level": level}, source)
    urgent_blocks = [block for block in result["blocks"] if block.get("task_id") == "urgent"]
    assert sum(minutes(block) for block in urgent_blocks) == 60
    assert all(block["end"] <= urgent["deadline_at"] for block in urgent_blocks)


def test_very_high_with_no_useful_work_never_fabricates_a_task():
    result = plan(settings={"workload_level": "very_high"})
    assert result["blocks"] == []
    assert result["stats"]["allocated_minutes"] == 0


@pytest.mark.parametrize("mode", ["balanced", "deadline", "deep"])
@pytest.mark.parametrize("urgent", [False, True])
def test_weekly_value_units_keep_useful_very_low_progress_without_double_strategy_cost(mode, urgent):
    changes = {"deadline_at": f"{DAY}T12:00:00-05:00", "task_type": "academic"} if urgent else {}
    source = [task("session:important", priority=5, weekly_value=600, weekly_full_bonus=0,
                   remaining_minutes=135, duration_minutes=135, splittable=True,
                   min_session_minutes=45, max_session_minutes=45, **changes)]
    settings = {"workload_level": "very_low"}
    result = plan(source, settings=settings, mode=mode)
    assert_valid(result, settings, source)
    assert result["stats"]["allocated_minutes"] == 135
    assert result["stats"]["weekly_opportunity_cost_scale"] == 1.0
    if urgent:
        assert all(block["end"] <= source[0]["deadline_at"] for block in result["blocks"] if block.get("task_id"))


def test_short_chunks_share_focus_and_still_receive_sustained_recovery():
    source = [task(splittable=True, remaining_minutes=80, duration_minutes=80,
                   min_session_minutes=20, max_session_minutes=20)]
    result = plan(source)
    assert_valid(result, tasks=source)
    chunks = [block for block in result["blocks"] if block.get("task_id")]
    breaks = [block for block in result["blocks"] if block["kind"] == "break"]
    assert len(chunks) == 4
    assert 0 < len(breaks) < len(chunks)
    assert all(minutes(block) >= SETTINGS["break_minutes"] for block in breaks)


def test_independent_validator_rejects_arbitrarily_fragmented_nonstop_work():
    source = [task(splittable=True, remaining_minutes=60, min_session_minutes=20, max_session_minutes=20)]
    chunks = [fixed(str(index), start, end, kind="task", task_id="work", locked=False)
              for index, (start, end) in enumerate([("08:00", "08:20"), ("08:20", "08:40"), ("08:40", "09:00")])]
    errors = validate_blocks(chunks, SETTINGS, lambda a, b: 15, source)
    assert any("sustained focus" in error for error in errors)


def test_legacy_finite_task_context_supports_separate_study_without_mutating_facts():
    study = task("study", title="Study mathematical proofs", description="Read notes and derive the proof",
                 related_activity={"id": "course", "title": "Mathematics", "category": "class",
                                   "occurrences": [{"start": f"{DAY}T08:00:00-05:00",
                                                    "end": f"{DAY}T09:00:00-05:00"}]})
    source = [task("plain"), study]
    before = deepcopy(source)
    result = plan(source, blocks=[fixed("lecture", "08:00", "09:00")],
                  settings={"work_start": "09:00", "work_end": "10:00", "break_minutes": 0})
    assert_valid(result, {"work_start": "09:00", "work_end": "10:00", "break_minutes": 0}, source)
    study_blocks = [block for block in result["blocks"] if block.get("task_id") == "study"]
    assert sum(minutes(block) for block in study_blocks) == 60
    assert "Related class occurs today" in study_blocks[0]["rationale"]
    assert source == before
    assert not any(block.get("status") == "completed" for block in result["blocks"])


@pytest.mark.parametrize("hard_deadline", [True, False])
def test_explicit_assessment_preparation_fits_before_actual_quiz_without_storing_a_deadline(hard_deadline):
    source = [task("prepare", task_type="academic", academic_subtype="assessment_preparation",
                   hard_deadline=hard_deadline,
                   related_activity={"id": "quiz", "title": "Math quiz", "category": "assessment",
                                     "assessment_start": f"{DAY}T09:00:00-05:00"})]
    before = deepcopy(source)
    quiz = fixed("quiz-event", "09:00", "10:00", category="assessment", activity_id="quiz")
    settings = {"work_start": "07:30"}
    result = plan(source, blocks=[quiz], settings=settings)
    assert_valid(result, settings, source)
    prepared = [block for block in result["blocks"] if block.get("task_id") == "prepare"]
    assert sum(minutes(block) for block in prepared) == 60
    assert all(block["end"] <= f"{DAY}T09:00:00-05:00" for block in prepared)
    assert "preparation must finish before the linked assessment" in prepared[0]["rationale"]
    assert source == before
    assert "assessment_at" not in source[0] and "deadline_at" not in source[0]


@pytest.mark.parametrize("hard_deadline", [True, False])
def test_explicit_preparation_is_unmet_when_only_work_time_is_after_actual_quiz(hard_deadline):
    source = [task("prepare", task_type="academic", academic_subtype="assessment_preparation",
                   hard_deadline=hard_deadline,
                   related_activity={"id": "quiz", "title": "Math quiz", "category": "assessment",
                                     "assessment_start": f"{DAY}T09:00:00-05:00"})]
    before = deepcopy(source)
    result = plan(source, settings={"work_start": "10:00", "work_end": "12:00"})
    assert_valid(result, {"work_start": "10:00", "work_end": "12:00"}, source)
    assert result["status"] == "partial"
    assert not any(block.get("task_id") == "prepare" for block in result["blocks"])
    assert result["unallocated"][0]["minutes"] == 60
    assert "Work after that assessment cannot satisfy its preparation" in result["unallocated"][0]["reason"]
    assert source == before


@pytest.mark.parametrize("hard_deadline", [True, False])
def test_independent_manual_validation_rejects_preparation_moved_after_actual_quiz(hard_deadline):
    source = [task("prepare", task_type="academic", academic_subtype="assessment_preparation",
                   hard_deadline=hard_deadline,
                   related_activity={"id": "quiz", "title": "Math quiz", "category": "assessment",
                                     "assessment_start": f"{DAY}T09:00:00-05:00"})]
    moved = fixed("manual-study", "10:00", "11:00", kind="task", task_id="prepare", locked=False)
    errors = validate_blocks([moved], SETTINGS, lambda a, b: 15, source)
    assert any("assessment preparation must finish before its linked assessment" in error for error in errors)


@pytest.mark.parametrize("level", LEVELS)
def test_high_difficulty_is_not_intrinsic_priority_and_hard_daily_max_survives(level):
    source = [task("difficult", priority=1, difficulty=10),
              task("important", priority=5, difficulty=1, max_sessions_per_day=1)]
    result = plan(source, settings={"workload_level": level, "work_end": "09:00", "break_minutes": 0})
    assert_valid(result, {"workload_level": level, "work_end": "09:00", "break_minutes": 0}, source)
    assert [block["task_id"] for block in result["blocks"] if block.get("task_id")] == ["important"]
