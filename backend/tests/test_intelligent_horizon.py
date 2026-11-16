"""Rolling forecast boundaries, completion evidence, and missed-target pacing."""
from copy import deepcopy
from datetime import date, timedelta

from backend.app.weekly_scheduler import finalize_weekly_result, forecast_horizon, prepare_weekly_tasks


DATE = "2026-11-12"  # Thursday
SETTINGS = {"timezone": "America/Toronto", "work_start": "08:00", "work_end": "18:00",
            "break_minutes": 0, "weekly_solver_seconds": 2}


def definition(**fields):
    return {"id": "task", "title": "Study", "importance": 5, "difficulty": 5,
            "session_minutes": 60, "task_type": "academic", **fields}


def assignment(**fields):
    return {"id": "week", "task_definition_id": "task", "week_start": "2026-11-08",
            "min_sessions_per_week": 5, "session_minutes": 60, **fields}


def context(**fields):
    return {"days": [{"date": (date.fromisoformat(DATE) + timedelta(days=index)).isoformat(), "capacity_minutes": 300}
                     for index in range(14)], "chunks": [], **fields}


def test_rolling_horizon_crosses_sunday_without_proposing_future_sessions():
    future = assignment(id="future", week_start="2026-11-15", min_sessions_per_week=2,
                        effective_definition=definition(due_at="2026-11-17T12:00:00-05:00"))
    ctx = context(forecast_assignments=[future], forecast_sessions=[])
    original = deepcopy(ctx)
    prepared = prepare_weekly_tasks(DATE, SETTINGS, [definition()], [assignment(min_sessions_per_week=1)], [], ctx)
    report = prepared["horizon_forecast"]
    assert report["start"] == DATE and report["end"] == "2026-11-25"
    assert len(report["days"]) == 14
    risk = next(item for item in report["task_risks"] if item["assignment_id"] == "future")
    assert risk["cutoff"] == "2026-11-17T12:00:00-05:00"
    assert risk["deadline_risk"] == "approaching"
    assert all(item["assignment_id"] == "week" for item in prepared["sessions"])
    assert all(item["task_assignment_id"] == "week" for item in prepared["tasks"])
    assert ctx == original


def test_thursday_missed_recurring_target_is_softened_and_original_shortfall_retained():
    prepared = prepare_weekly_tasks(DATE, SETTINGS, [definition(recurrence={"kind": "weekly"})],
                                    [assignment(source="recurring")], [], context())
    progress = prepared["weekly_progress"][0]
    assert progress["minimum_sessions"] == 5
    assert progress["achievable_target_sessions"] == 3
    assert progress["deferred_target_sessions"] == 2
    assert progress["expected_sessions"] <= 3
    assert progress["expected_shortfall"] >= 2


def test_explicit_deadline_preserves_full_target_despite_lateweek_recurrence():
    task = definition(recurrence={"kind": "weekly"}, due_at="2026-11-14T18:00:00-05:00")
    prepared = prepare_weekly_tasks(DATE, SETTINGS, [task], [assignment(source="recurring")], [], context())
    assert prepared["weekly_progress"][0]["achievable_target_sessions"] == 5


def test_target_met_unfinished_gets_urgent_extras_but_completed_definition_stops():
    task = definition(due_at="2026-11-13T18:00:00-05:00")
    week = assignment(min_sessions_per_week=1)
    done = {"id": "done", "assignment_id": "week", "index": 0, "target_minutes": 60,
            "completed_minutes": 60, "status": "completed"}
    prepared = prepare_weekly_tasks(DATE, SETTINGS, [task], [week], [done], context())
    assert prepared["tasks"]
    assert all(item["logical_session_id"] != "done" for item in prepared["tasks"])
    closed = prepare_weekly_tasks(DATE, SETTINGS, [{**task, "status": "completed"}], [week], [done], context())
    assert closed["tasks"] == []


def test_split_confirmed_elapsed_and_planned_are_distinct_and_not_double_counted():
    split = {"id": "split", "assignment_id": "week", "index": 0, "target_minutes": 60,
             "completed_minutes": 30, "planned_minutes": 30, "elapsed_scheduled_minutes": 15,
             "future_scheduled_minutes": 15, "status": "in_progress"}
    report = forecast_horizon(DATE, SETTINGS, [definition()], [assignment(min_sessions_per_week=1)], [split], context())
    risk = report["task_risks"][0]
    assert risk["completed_sessions"] == 0
    assert risk["verified_completed_minutes"] == 30
    assert risk["planned_minutes"] == 30 and risk["elapsed_scheduled_minutes"] == 15
    assert risk["remaining_estimated_minutes"] == 30
    split["completed_minutes"] = 60
    assert forecast_horizon(DATE, SETTINGS, [definition()], [assignment(min_sessions_per_week=1)], [split], context())["task_risks"][0]["completed_sessions"] == 1


def test_laterweek_deadline_has_priority_gradient_today_without_crossweek_chunks():
    ordinary = prepare_weekly_tasks(DATE, SETTINGS, [definition()], [assignment(min_sessions_per_week=1)], [], context())
    dated = prepare_weekly_tasks(DATE, SETTINGS, [definition(due_at="2026-11-20T12:00:00-05:00")],
                                 [assignment(min_sessions_per_week=1)], [], context())
    assert dated["tasks"][0]["weekly_value"] > ordinary["tasks"][0]["weekly_value"]
    assert dated["tasks"][0]["planning_context"]["deadline_risk"] == "approaching"


def test_overdue_cutoff_reports_unreachable_work_without_allocating_after_date():
    task = definition(due_at="2026-11-11T12:00:00-05:00")
    prepared = prepare_weekly_tasks(DATE, SETTINGS, [task], [assignment()], [], context())
    assert prepared["tasks"] == []
    risk = prepared["horizon_forecast"]["task_risks"][0]
    assert risk["deadline_risk"] == "overdue"
    assert risk["available_before_cutoff_minutes"] == 0


def test_futureweek_override_and_explicit_completion_cannot_reopen_source():
    future = assignment(id="future", week_start="2026-11-15", effective_definition=definition(status="active"))
    report = forecast_horizon(DATE, SETTINGS, [definition(status="completed")], [], [], context(forecast_assignments=[future]))
    assert report["task_risks"] == []


def test_competing_deadlines_share_forecast_capacity_instead_of_each_claiming_it():
    tasks = [definition(id="first", due_at="2026-11-12T18:00:00-05:00"),
             definition(id="second", due_at="2026-11-12T18:00:00-05:00")]
    assignments = [assignment(id="a", task_definition_id="first", min_sessions_per_week=1),
                   assignment(id="b", task_definition_id="second", min_sessions_per_week=1)]
    report = forecast_horizon(DATE, SETTINGS, tasks, assignments, [],
                              {"days": [{"date": DATE, "capacity_minutes": 60}]})
    assert sum(item["forecast_allocated_minutes"] for item in report["task_risks"]) == 60
    assert sum(item["estimated_shortfall_minutes"] for item in report["task_risks"]) == 60
    assert report["days"][0]["forecast_minutes"] == 60
    assert any(item["deadline_risk"] == "at_risk" for item in report["task_risks"])


def test_future_commitments_raise_current_preparation_value_without_creating_future_work():
    task = definition(due_at="2026-11-17T12:00:00-05:00")
    week = assignment(min_sessions_per_week=1)
    open_context = context()
    busy_context = deepcopy(open_context)
    for day in busy_context["days"]:
        if day["date"] >= "2026-11-15":
            day["capacity_minutes"] = 0
    open_plan = prepare_weekly_tasks(DATE, SETTINGS, [task], [week], [], open_context)
    busy_plan = prepare_weekly_tasks(DATE, SETTINGS, [task], [week], [], busy_context)
    assert busy_plan["tasks"][0]["weekly_value"] > open_plan["tasks"][0]["weekly_value"]
    assert busy_plan["tasks"][0]["planning_context"]["preparation_urgency_bonus"] == 60
    assert all(item["task_assignment_id"] == "week" for item in busy_plan["tasks"])


def test_explicit_preparation_after_actual_assessment_is_unallocated_and_overdue_without_mutating_dates():
    task = definition(academic_subtype="assessment_preparation", hard_deadline=False,
                      related_activity={"id": "exam", "category": "assessment",
                                        "assessment_start": "2026-11-12T07:30:00-05:00"})
    week = assignment(min_sessions_per_week=1)
    original = deepcopy((task, week))
    prepared = prepare_weekly_tasks(DATE, SETTINGS, [task], [week], [], context())
    assert prepared["tasks"] == []
    risk = prepared["horizon_forecast"]["task_risks"][0]
    assert risk["deadline_risk"] == "overdue"
    assert risk["preparation_cutoff"] == "2026-11-12T07:30:00-05:00"
    assert "must finish before" in risk["reason"]
    result = finalize_weekly_result({"status": "optimal", "blocks": [], "unallocated": [], "stats": {}}, prepared)
    assert result["status"] == "partial"
    assert result["unallocated"][0]["minutes"] == 60
    assert "after that start does not count" in result["unallocated"][0]["reason"]
    assert result["stats"]["unallocated_minutes"] == 60
    assert (task, week) == original
    assert task.get("due_at") is None and task.get("assessment_at") is None


def test_explicit_preparation_units_keep_subtype_and_actual_context_before_cutoff():
    task = definition(academic_subtype="assessment_preparation", hard_deadline=False,
                      related_activity={"id": "exam", "category": "assessment",
                                        "assessment_start": "2026-11-12T12:00:00-05:00"})
    prepared = prepare_weekly_tasks(DATE, SETTINGS, [task], [assignment(min_sessions_per_week=1)], [], context())
    assert prepared["tasks"]
    assert prepared["tasks"][0]["academic_subtype"] == "assessment_preparation"
    assert prepared["tasks"][0]["related_activity"] == task["related_activity"]
    assert prepared["tasks"][0].get("assessment_at") is None


def test_generic_link_to_past_assessment_remains_context_without_a_prep_cutoff():
    task = definition(academic_subtype="studying", related_activity={"category": "assessment",
                      "assessment_start": "2026-11-12T07:30:00-05:00"})
    prepared = prepare_weekly_tasks(DATE, SETTINGS, [task], [assignment(min_sessions_per_week=1)], [], context())
    assert prepared["tasks"]
    assert prepared["horizon_forecast"]["task_risks"][0]["preparation_cutoff"] is None
