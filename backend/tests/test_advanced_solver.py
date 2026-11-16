"""Capacity and search diagnostics against real, validated CP-SAT solutions."""
from backend.app.scheduler import generate_schedule, validate_blocks


DAY = "2026-11-13"
SETTINGS = {"timezone": "America/Toronto", "wake_time": "07:00", "sleep_time": "23:00",
            "work_start": "08:00", "work_end": "10:00", "break_minutes": 10,
            "focus_minutes": 50, "travel_buffer_minutes": 0, "meals": [],
            "workload_level": "very_high", "solver_seconds": 2}


def task(identifier="study", **changes):
    return {"id": identifier, "title": identifier, "kind": "academic", "remaining_minutes": 120,
            "duration_minutes": 120, "priority": 5, "splittable": False,
            "min_session_minutes": 120, "max_session_minutes": 120, "dependencies": [],
            "status": "todo", "location_id": "home", **changes}


def solve(tasks, settings=None, classes=None):
    config = {**SETTINGS, **(settings or {})}
    result = generate_schedule(DAY, config, classes or [], tasks, [], lambda a, b: 15, "balanced")
    assert result["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert not validate_blocks(result["blocks"], config, lambda a, b: 15, tasks)
    return result


def test_exact_terminal_session_covers_all_configured_start_grid():
    result = solve([task()], {"work_start": "08:05", "work_end": "10:05"})
    work = [block for block in result["blocks"] if block.get("task_id")]
    assert work[0]["start"] == f"{DAY}T08:05:00-05:00"
    assert work[0]["end"] == f"{DAY}T10:05:00-05:00"
    assert not [block for block in result["blocks"] if block["kind"] == "break"]


def test_optional_weekly_supply_does_not_become_unmet_baseline():
    result = solve([task(weekly_opportunity=True, weekly_planned_minutes=0)], {"work_end": "09:00"})
    assert result["unallocated"] == []
    tail = result["stats"]["tail_diagnostics"]
    assert tail["contiguous_free_minutes"] == 60
    assert tail["remaining_candidates"][0]["minimum_chunk_minutes"] == 120
    assert "do not prove" in tail["scope"]


def test_expanded_unit_retains_only_baseline_shortfall():
    result = solve([task(weekly_opportunity=True, weekly_planned_minutes=60)], {"work_end": "09:00"})
    assert result["stats"]["unallocated_minutes"] == 60
    assert result["unallocated"][0]["minutes"] == 60


def test_actual_capacity_counts_fixed_travel_and_recovery():
    result = solve([task(remaining_minutes=50, duration_minutes=50, min_session_minutes=50,
                         max_session_minutes=50, location_id="campus", location_mode="required")],
                   {"wake_time": "08:00", "work_end": "11:00", "home_location_id": "home", "start_at_home": True,
                    "end_at_home": True})
    stats = result["stats"]
    assert stats["actual_productive_capacity_minutes"] == 140
    assert stats["actual_unused_productive_minutes"] == 90
    assert stats["tail_diagnostics"]["contiguous_free_minutes"] >= 0


def test_tail_reports_actual_daily_limit_across_logical_units():
    tasks = [task(str(i), remaining_minutes=50, duration_minutes=50, min_session_minutes=50,
                  max_session_minutes=50, task_definition_id="shared", max_sessions_per_day=1)
             for i in range(2)]
    result = solve(tasks)
    remaining = result["stats"]["tail_diagnostics"]["remaining_candidates"]
    assert len(remaining) == 1
    assert remaining[0]["daily_maximum_reached"]
    assert "daily maximum of 1" in result["unallocated"][0]["reason"]


def test_explicit_budget_keeps_single_worker_unless_requested():
    result = solve([task()])
    assert result["stats"]["configured_solver_seconds"] == 2
    assert result["stats"]["search_workers"] == 1
    assert result["stats"]["solver_budget_policy"] == "explicit_budget"
    assert not result["stats"]["parallel_search_nondeterministic"]


def test_explicit_parallel_workers_are_bounded_and_reported():
    result = solve([task()], {"solver_workers": 99})
    assert result["stats"]["search_workers"] == 8
    assert result["stats"]["configured_solver_seconds"] == 2
    assert result["stats"]["parallel_search_nondeterministic"]
    assert any("parallel incumbent choices may vary" in text for text in result["explanations"])
