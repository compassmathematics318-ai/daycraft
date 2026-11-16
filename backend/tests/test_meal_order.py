"""Meal chronology is a CP-SAT hard constraint, independently audited by ID."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from backend.app.meal_planning import meal_requirements, validate_required_meals
from backend.app.scheduler import generate_schedule, validate_blocks


DAY = "2026-11-12"
SETTINGS = {"timezone": "America/Toronto", "wake_time": "07:00", "sleep_time": "23:00",
            "work_start": "08:00", "work_end": "20:00", "focus_minutes": 50,
            "break_minutes": 10, "travel_buffer_minutes": 0, "solver_seconds": 2,
            "meals": []}
LEVELS = ["very_low", "low", "medium", "high", "very_high"]


def meal(identity, name, **changes):
    return {"id": identity, "name": name, "duration_minutes": 30, **changes}


def block(identity, start_clock, end_clock, **changes):
    return {"id": identity, "title": identity, "kind": "meal", "locked": True,
            "start": f"{DAY}T{start_clock}:00-05:00", "end": f"{DAY}T{end_clock}:00-05:00",
            "location_mode": "unspecified", "location_id": None, "meal_id": identity,
            "status": "todo", "rationale": "Original historical evidence", **changes}


def plan(meals, blocks=(), tasks=(), now=None, route=None, **settings):
    config = {**SETTINGS, **settings, "meals": meals}
    source = deepcopy((config, blocks, tasks))
    result = generate_schedule(DAY, config, [], list(tasks), list(blocks),
                               route or (lambda a, b: 0), now=now)
    assert (config, blocks, tasks) == source
    return result, config


def assert_valid_order(result, config, protected=(), tasks=None, route=None):
    assert result["status"] in {"optimal", "feasible", "partial"}, result["conflicts"]
    assert result["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert not validate_blocks(result["blocks"], config, route or (lambda a, b: 0), tasks, list(protected))
    requirements = meal_requirements(config, list(protected))
    assert not validate_required_meals(result["blocks"], requirements)
    matched = meal_requirements(config, result["blocks"])
    for left, right in zip(matched, matched[1:]):
        assert datetime.fromisoformat(left["preserved"]["end"]) <= datetime.fromisoformat(right["preserved"]["start"])
    return [item["preserved"] for item in matched]


@pytest.mark.parametrize("level", LEVELS)
def test_reordered_custom_names_and_reversed_clock_preferences_follow_settings_at_every_workload(level):
    meals = [meal("z", "Zebra", time="19:00"), meal("a", "Alpha", time="08:00"),
             meal("m", "Maple", time="07:00")]
    tasks = [{"id": str(index), "title": "Work", "status": "todo", "priority": 3,
              "remaining_minutes": 60, "duration_minutes": 60, "splittable": False,
              "location_mode": "remote", "dependencies": []} for index in range(3)]
    result, config = plan(meals, tasks=tasks, workload_level=level)
    rows = assert_valid_order(result, config, tasks=tasks)
    assert [row["meal_id"] for row in rows] == ["z", "a", "m"]
    assert [row["title"] for row in result["blocks"] if row["kind"] == "meal"] == ["Zebra", "Alpha", "Maple"]
    assert result["workload_level"] == level
    assert all(datetime.fromisoformat(row["end"]) - datetime.fromisoformat(row["start"])
               == timedelta(minutes=30) for row in rows)


def test_standard_meals_keep_flexible_awake_windows_around_fixed_commitments():
    meals = [meal("b", "Breakfast"), meal("l", "Lunch", duration_minutes=45), meal("d", "Dinner")]
    commitment = block("lecture", "11:00", "14:00", kind="class", meal_id=None, location_mode="remote")
    result, config = plan(meals, [commitment])
    rows = assert_valid_order(result, config, [commitment])
    assert rows[0]["end"] <= f"{DAY}T08:00:00-05:00"
    assert rows[1]["end"] <= commitment["start"] or rows[1]["start"] >= commitment["end"]
    assert [row["meal_id"] for row in rows] == ["b", "l", "d"]


def test_reordered_standard_meals_can_require_lunch_after_dinner():
    meals = [meal("b", "Breakfast"), meal("d", "Dinner"), meal("l", "Lunch")]
    result, config = plan(meals)
    rows = assert_valid_order(result, config)
    assert [row["title"] for row in rows] == ["Breakfast", "Dinner", "Lunch"]
    assert rows[1]["end"] <= rows[2]["start"]


def test_impossible_standard_order_does_not_relax_timing_or_drop_required_meals():
    result, _ = plan([meal("d", "Dinner"), meal("b", "Breakfast")])
    assert result["status"] == "infeasible"
    assert result["solver_status"] == "INFEASIBLE"
    conflict = " ".join(result["conflicts"])
    assert "Dinner then Breakfast" in conflict
    assert "Preferences" in conflict and "awake" in conflict
    assert result["blocks"] == []


@pytest.mark.parametrize("protection", [{"locked": True, "status": "todo"},
                                        {"locked": False, "status": "completed"},
                                        {"locked": False, "status": "in_progress"}])
def test_inverted_protected_custom_meals_report_order_and_preserve_every_field(protection):
    meals = [meal("z", "Zebra"), meal("a", "Alpha")]
    history = [block("z", "17:00", "17:30", title="Old Zebra", **protection),
               block("a", "09:00", "09:30", title="Old Alpha", **protection)]
    before = deepcopy(history)
    result, _ = plan(meals, history)
    assert result["status"] == "infeasible"
    assert sorted(result["blocks"], key=lambda row: row["id"]) == sorted(before, key=lambda row: row["id"])
    conflict = " ".join(result["conflicts"])
    assert "Zebra" in conflict and "Alpha" in conflict and "order" in conflict
    assert "Preferences" in conflict and "preserved" in conflict


def test_disabled_definition_neither_generates_nor_participates_in_order_even_with_history():
    meals = [meal("z", "Zebra"), meal("off", "Disabled", enabled=False), meal("a", "Alpha")]
    history = [block("z", "14:00", "14:30"), block("off", "08:00", "08:30", status="completed")]
    result, config = plan(meals, history)
    rows = assert_valid_order(result, config, history)
    assert [row["meal_id"] for row in rows] == ["z", "a"]
    assert next(row for row in result["blocks"] if row["id"] == "off") == history[1]
    empty, empty_config = plan(meals)
    assert_valid_order(empty, empty_config)
    assert [row["meal_id"] for row in empty["blocks"] if row["kind"] == "meal"] == ["z", "a"]


def test_remaining_day_matches_completed_identity_after_rename_without_duplicate_or_relocation():
    history = block("z", "08:00", "08:30", title="Old name", status="completed", locked=False)
    meals = [meal("z", "Renamed first", duration_minutes=45), meal("a", "Next meal")]
    now = f"{DAY}T11:00:00-05:00"
    result, config = plan(meals, [history], now=now)
    rows = assert_valid_order(result, config, [history])
    assert rows[0] == history
    assert rows[1]["start"] >= now
    assert len([row for row in result["blocks"] if row.get("meal_id") == "z"]) == 1


def test_legacy_title_matched_locked_meal_retains_original_metadata_without_meal_id():
    history = block("legacy-record", "08:00", "08:30", title="Zebra", extra_evidence={"source": "legacy"})
    history.pop("meal_id")
    result, config = plan([meal("z", "Zebra"), meal("a", "Alpha")], [history])
    rows = assert_valid_order(result, config, [history])
    assert rows[0] == history
    assert len([row for row in result["blocks"] if row["kind"] == "meal"]) == 2


def test_remaining_day_cannot_put_missing_first_meal_after_completed_second():
    history = block("a", "09:00", "09:30", status="completed", locked=False,
                    extra_evidence={"note": "retain exactly"})
    result, _ = plan([meal("z", "Zebra"), meal("a", "Alpha")], [history],
                     now=f"{DAY}T12:00:00-05:00")
    assert result["status"] == "infeasible"
    assert result["solver_status"] == "INFEASIBLE"
    assert result["blocks"] == [history]
    assert "Zebra then Alpha" in " ".join(result["conflicts"])


def test_order_keeps_fixed_activity_travel_and_awake_bounds_with_meals_outside_work_hours():
    meals = [meal("z", "Zebra", location_id="cafe", time="19:00"),
             meal("a", "Alpha", location_id="home", time="07:00")]
    commitment = block("lecture", "12:00", "14:00", kind="class", meal_id=None,
                       location_mode="required", location_id="campus")
    def route(a, b):
        return 20 if a != b else 0
    result, config = plan(meals, [commitment], route=route, work_start="10:00", work_end="11:00",
                          sleep_time="20:00", home_location_id="home", start_at_home=True, end_at_home=True)
    rows = assert_valid_order(result, config, [commitment], route=route)
    assert any(row["kind"] == "travel" for row in result["blocks"])
    assert next(row for row in result["blocks"] if row["id"] == "lecture")["start"] == commitment["start"]
    assert all(f"{DAY}T07:00:00-05:00" <= row["start"] < row["end"] <= f"{DAY}T20:00:00-05:00" for row in rows)
    assert any(row["start"] >= f"{DAY}T11:00:00-05:00" for row in rows)


def test_independent_audit_rejects_reordered_custom_records_and_compares_real_instants():
    meals = [meal("z", "Zebra"), meal("a", "Alpha")]
    requirements = meal_requirements({"meals": meals}, [])
    inverted = [block("z", "17:00", "17:30"), block("a", "09:00", "09:30")]
    assert any("Zebra" in error and "Alpha" in error for error in validate_required_meals(inverted, requirements))
    # 13:00Z is 08:00 Toronto; clock-string sorting would incorrectly invert it.
    correct = [block("z", "08:00", "08:30", start=f"{DAY}T13:00:00Z", end=f"{DAY}T13:30:00Z"),
               block("a", "08:30", "09:00")]
    assert not validate_required_meals(correct, requirements)
