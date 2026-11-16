"""Quality properties against actual CP-SAT intervals, independent of objective details."""
from copy import deepcopy
from datetime import datetime

import pytest

from backend.app.scheduler import generate_schedule, validate_blocks

DATE = "2026-11-13"
SETTINGS = {"timezone": "America/Toronto", "wake_time": "07:00", "sleep_time": "23:55",
            "work_start": "08:00", "work_end": "23:30", "break_minutes": 10,
            "travel_buffer_minutes": 0, "focus_minutes": 50, "default_location_id": "home",
            "meals": [], "solver_seconds": 3}
LEVELS = ("very_low", "low", "medium", "high", "very_high")


def unit(i, duration=45, **values):
    return {"id": str(i), "title": f"Study {i}", "kind": "academic", "remaining_minutes": duration,
            "duration_minutes": duration, "priority": 4, "splittable": False,
            "min_session_minutes": 25, "max_session_minutes": duration, "dependencies": [],
            "status": "todo", "location_id": "home", "weekly_value": 800,
            "task_definition_id": f"d{i}", "logical_session_id": f"s{i}", **values}


def solve(tasks, level, settings=None, classes=None):
    config = {**SETTINGS, **(settings or {}), "workload_level": level}
    original = deepcopy(tasks)
    result = generate_schedule(DATE, config, classes or [], tasks, [], lambda a, b: 0, "balanced")
    assert tasks == original
    assert result["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert not validate_blocks(result["blocks"], config, lambda a, b: 0, tasks)
    return result


def work(result):
    return sorted((b for b in result["blocks"] if b.get("task_id")), key=lambda b: b["start"])


def elapsed(start, end):
    return int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60)


@pytest.mark.parametrize("level", LEVELS)
def test_scarce_urgent_work_uses_compact_productive_span(level):
    result = solve([unit(i, deadline=f"{DATE}T20:00:00-05:00") for i in range(2)], level)
    blocks = work(result)
    assert sum(elapsed(b["start"], b["end"]) for b in blocks) == 90
    assert elapsed(blocks[0]["start"], blocks[-1]["end"]) <= 105


@pytest.mark.parametrize("level", LEVELS)
def test_terminal_work_does_not_add_a_standalone_recovery_block(level):
    result = solve([unit(0, 60)], level, {"work_end": "09:00", "sleep_time": "10:00"})
    productive = work(result)
    assert productive
    assert not [b for b in result["blocks"] if b["kind"] == "break" and b["start"] >= productive[-1]["end"]]


def test_high_profiles_can_use_valuable_evening_availability():
    anchor = {"id": "busy", "title": "Commitment", "date": DATE, "start_time": "08:00",
              "end_time": "19:00", "location_id": "home"}
    for level in ("high", "very_high"):
        result = solve([unit(i, 60, weekly_value=900) for i in range(4)], level, classes=[anchor])
        productive = work(result)
        assert sum(elapsed(b["start"], b["end"]) for b in productive) >= 180
        assert max(b["end"] for b in productive) > f"{DATE}T22:00:00-05:00"


def test_valuable_unfinished_weekly_work_advances_more_at_very_high():
    from backend.app.weekly_scheduler import prepare_weekly_tasks

    day = "2026-11-14"
    definition = {"id": "d", "title": "Study", "task_type": "academic", "session_minutes": 60,
                  "importance": 10, "difficulty": 5, "allow_splitting": False,
                  "dependencies": [], "location_id": "home", "min_sessions_per_day": 0}
    assignment = {"id": "a", "task_definition_id": "d", "week_start": "2026-11-08",
                  "min_sessions_per_week": 1, "status": "todo"}
    verified = {"id": "done", "assignment_id": "a", "index": 0, "target_minutes": 60,
                "completed_minutes": 60, "status": "completed"}
    source = deepcopy((definition, assignment, verified))
    allocated = []
    for level in ("medium", "high", "very_high"):
        settings = {**SETTINGS, "workload_level": level}
        prepared = prepare_weekly_tasks(day, settings, [definition], [assignment], [verified],
                                        {"days": [{"date": day, "capacity_minutes": 900}], "chunks": []})
        units = prepared["tasks"] + prepared.get("_daily_task_limits", [])
        result = generate_schedule(day, settings, [], units, [], lambda a, b: 0, "balanced")
        assert result["solver_status"] == "OPTIMAL"
        assert not validate_blocks(result["blocks"], settings, lambda a, b: 0, units)
        allocated.append(sum(elapsed(b["start"], b["end"]) for b in work(result)))
    assert allocated[0] < allocated[1] < allocated[2]
    assert allocated[2] - allocated[1] >= 60
    assert (definition, assignment, verified) == source
