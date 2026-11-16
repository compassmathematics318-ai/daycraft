"""Workload changes useful marginal work without inventing task completion."""
from copy import deepcopy

import pytest

from backend.app.weekly_scheduler import prepare_weekly_tasks


def prepare(level, *, importance=10, minimum=1, completed=0, pending=0, **definition_fields):
    definition = {"id": "d", "title": "Open work", "task_type": "academic",
                  "session_minutes": 30, "importance": importance, "difficulty": 5,
                  "allow_splitting": False, "dependencies": [], **definition_fields}
    assignment = {"id": "a", "task_definition_id": "d", "week_start": "2026-11-08",
                  "min_sessions_per_week": minimum, "status": "active"}
    sessions = [{"id": f"s{i}", "assignment_id": "a", "index": i,
                 "target_minutes": 30, "completed_minutes": 30, "status": "completed"}
                for i in range(completed)]
    sessions += [{"id": f"p{i}", "assignment_id": "a", "index": completed + i,
                  "target_minutes": 30, "completed_minutes": 0, "status": "todo"}
                 for i in range(pending)]
    original = deepcopy((definition, assignment, sessions))
    result = prepare_weekly_tasks("2026-11-14", {
        "timezone": "America/Toronto", "work_start": "08:00", "work_end": "20:00",
        "break_minutes": 0, "workload_level": level,
    }, [definition], [assignment], sessions,
        {"days": [{"date": "2026-11-14", "capacity_minutes": 720}]})
    assert (definition, assignment, sessions) == original
    return result


def test_higher_workload_advances_more_open_work_after_verified_target():
    results = [prepare(level, completed=1) for level in ("medium", "high", "very_high")]
    minutes = [sum(task["remaining_minutes"] for task in result["tasks"]) for result in results]
    assert minutes[0] < minutes[1] < minutes[2]
    for result in results:
        values = [task["weekly_value"] for task in result["tasks"]]
        assert values == sorted(values, reverse=True)
        assert all(left > right for left, right in zip(values, values[1:]))
        assert result["weekly_progress"][0]["completed_sessions"] == 1


def test_completed_extras_consume_their_marginal_value():
    before, after = prepare("very_high", completed=1), prepare("very_high", completed=3)
    assert [t["weekly_value"] for t in after["tasks"]] == [t["weekly_value"] for t in before["tasks"]][2:]


def test_lowering_workload_removes_stale_extra_proposals_from_pacing():
    clean, retained = prepare("medium"), prepare("medium", pending=10)
    assert [t["weekly_value"] for t in clean["tasks"]] == [t["weekly_value"] for t in retained["tasks"]]
    assert clean["weekly_progress"][0]["planned_today_minutes"] == retained["weekly_progress"][0]["planned_today_minutes"]
    assert len(clean["sessions"]) == len(retained["sessions"]) == 4


@pytest.mark.parametrize("level", ["very_low", "low", "medium", "high", "very_high"])
def test_workload_never_creates_weak_zero_target_work(level):
    assert prepare(level, importance=2, minimum=0)["tasks"] == []


@pytest.mark.parametrize("fields", [{"finite_work_minutes": 30}, {"legacy_task_id": "legacy"},
                                    {"status": "completed"}])
def test_finite_or_completed_work_never_grows_extras(fields):
    assert prepare("very_high", completed=1, **fields)["tasks"] == []
