"""Advanced profiles can advance real forecast work without changing its identity."""
from copy import deepcopy

import pytest

from backend.app.weekly_scheduler import finalize_weekly_result, prepare_weekly_tasks

DATE = "2026-11-09"
SETTINGS = {"timezone": "America/Toronto", "work_start": "08:00", "work_end": "18:00",
            "break_minutes": 0, "weekly_solver_seconds": 2}


def prepare(level="high", **changes):
    definition = {"id": "d", "title": "Finite study", "importance": 5, "difficulty": 5,
                  "session_minutes": 60, "task_type": "academic", "allow_splitting": True,
                  "min_chunk_minutes": 30, "finite_work_minutes": 120, **changes}
    assignment = {"id": "a", "task_definition_id": "d", "week_start": "2026-11-08",
                  "min_sessions_per_week": 2, "status": "active"}
    return prepare_weekly_tasks(DATE, {**SETTINGS, "workload_level": level}, [definition], [assignment], [],
                               {"days": [{"date": DATE, "capacity_minutes": 60},
                                         {"date": "2026-11-10", "capacity_minutes": 120}], "chunks": []})


def test_advanced_profiles_offer_useful_future_sessions_without_new_work():
    medium, high = prepare("medium"), prepare("high")
    assert len(high["sessions"]) == len(medium["sessions"]) == 2
    assert high["weekly_progress"] == medium["weekly_progress"]
    assert any(unit["weekly_opportunity"] for unit in high["tasks"])
    assert len(high["tasks"]) > len(medium["tasks"])
    assert all(unit["min_session_minutes"] == 30 for unit in high["tasks"])
    assert sum(unit["weekly_planned_minutes"] for unit in high["tasks"]) == sum(unit["remaining_minutes"] for unit in medium["tasks"])
    assert all(not unit["weekly_opportunity"] for unit in medium["tasks"])


@pytest.mark.parametrize("changes", [{"status": "paused"}, {"earliest_start": "2026-11-10T08:00:00-05:00"},
                                      {"dependencies": ["missing"]}])
def test_opportunities_do_not_reopen_ineligible_work(changes):
    assert not any(unit["weekly_opportunity"] for unit in prepare(**changes)["tasks"])


def test_advanced_actual_work_does_not_inflate_future_session_credit():
    prepared = prepare()
    original = deepcopy(prepared)
    unit = next(unit for unit in prepared["tasks"] if unit["weekly_opportunity"])
    result = finalize_weekly_result({"blocks": [{"task_id": unit["id"], "status": "todo",
                                               "start": DATE + "T08:00:00-05:00",
                                               "end": DATE + "T09:00:00-05:00"}], "unallocated": []}, prepared)
    assert result["weekly_progress"][0]["expected_sessions"] <= 2
    assert result["weekly_progress"][0]["planned_today_minutes"] == 60
    assert result["stats"]["weekly_advanced_minutes"] == 60 - unit["weekly_planned_minutes"]
    assert result["stats"]["weekly_forecast_future_reduced_minutes"] > 0
    assert any("saved future plans" in text for text in result["explanations"])
    assert prepared == original

def test_opportunity_respects_other_day_reservation_and_daily_maximum():
    definition = {"id": "d", "title": "Reserved work", "importance": 5, "session_minutes": 60,
                  "allow_splitting": True, "min_chunk_minutes": 30, "max_sessions_per_day": 1,
                  "finite_work_minutes": 120}
    assignment = {"id": "a", "task_definition_id": "d", "week_start": "2026-11-08",
                  "min_sessions_per_week": 2}
    sessions = [{"id": "s1", "assignment_id": "a", "index": 0, "target_minutes": 60,
                 "completed_minutes": 0, "status": "todo"},
                {"id": "s2", "assignment_id": "a", "index": 1, "target_minutes": 60,
                 "completed_minutes": 0, "status": "todo"}]
    chunks = [{"logical_session_id": "s1", "task_definition_id": "d", "status": "todo", "locked": True,
               "start": DATE + "T08:00:00-05:00", "end": DATE + "T08:30:00-05:00"},
              {"logical_session_id": "s2", "task_definition_id": "d", "status": "todo",
               "start": "2026-11-10T08:00:00-05:00", "end": "2026-11-10T09:00:00-05:00"}]
    original = deepcopy(chunks)
    result = prepare_weekly_tasks(DATE, {**SETTINGS, "workload_level": "very_high"},
                                  [definition], [assignment], sessions,
                                  {"days": [{"date": DATE, "capacity_minutes": 120},
                                            {"date": "2026-11-10", "capacity_minutes": 120}], "chunks": chunks})
    assert all(not unit["weekly_opportunity"] for unit in result["tasks"])
    assert {unit["logical_session_id"] for unit in result["tasks"]} == {"s1"}
    assert result["tasks"][0]["remaining_minutes"] == 30
    assert chunks == original


def test_unsplittable_future_work_is_not_shortened_to_current_capacity():
    result = prepare(allow_splitting=False, session_minutes=120)
    assert not any(unit["weekly_opportunity"] for unit in result["tasks"])

def test_tail_candidate_identifiers_are_public_definition_and_session_ids():
    prepared = prepare()
    unit = prepared["tasks"][0]
    result = finalize_weekly_result({"blocks": [], "stats": {"tail_diagnostics": {"remaining_candidates": [
        {"task_id": unit["id"], "minimum_chunk_minutes": 30}]}}}, prepared)
    candidate = result["stats"]["tail_diagnostics"]["remaining_candidates"][0]
    assert candidate["task_id"] == "d"
    assert candidate["logical_session_id"] == unit["logical_session_id"]
    assert candidate["task_assignment_id"] == "a"
    assert candidate["title"] == "Finite study"
