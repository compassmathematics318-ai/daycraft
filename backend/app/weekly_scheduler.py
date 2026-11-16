"""Pure weekly logical-session planning around the authoritative daily solver.

The weekly capacity forecast is deliberately approximate. CP-SAT distributes a
finite set of meaningful sessions across the remaining Sunday–Saturday horizon;
the daily model remains responsible for actual intervals, travel and conflicts.
The service supplies venue-suitability evidence; no minimum is a hard work quota.
"""
from __future__ import annotations

import math
from copy import deepcopy
from datetime import date as Date, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model

from .scheduler import _dt, _minutes, _project_priority_bonus, _related_assessment_bonus, validate_blocks
from .planning_intelligence import assessment_preparation_cutoff, interpret_task_context, workload_profile


def _session_id(assignment_id, index):
    return str(uuid5(NAMESPACE_URL, f"daycraft:weekly-session:{assignment_id}:{index}"))


def _effective_definition(definition, assignment):
    """Apply an explicit week's metadata without modifying its reusable source.

    The service supplies one effective assignment per definition/week, including
    stable virtual assignments for recurrence. Explicit nulls clear inherited
    dates; definition identity and project lifecycle remain authoritative.
    """
    overrides = assignment.get("overrides") or {}
    fields = {"title", "description", "importance", "difficulty", "due_at",
              "assessment_at", "deadline_at", "earliest_start", "preferred_start",
              "preferred_end", "session_minutes", "allow_splitting", "min_chunk_minutes",
              "dependencies", "hard_deadline", "schedule_inactive_project", "location_id", "location_mode",
              "allow_alternative_locations", "alternative_location_ids",
              "location_requirements", "location_suitability",
              "preferred_days", "preferred_time_of_day", "status", "task_type",
              "academic_subtype", "course", "related_activity_id", "room",
              "min_sessions_per_day", "max_sessions_per_day"}
    effective = {**definition, **{key: value for key, value in overrides.items() if key in fields}}
    # An older weekly availability override cannot reopen an explicitly finished task.
    if definition.get("status") == "completed":
        effective["status"] = "completed"
    if definition.get("deleted_at"):
        effective["status"] = "archived"
    return effective


def _cutoff(definition, tz, hard_only=True):
    keys = ("due_at", "assessment_at", "deadline_at") if definition.get("task_type", "academic") == "academic" else ("deadline_at",)
    if hard_only and not definition.get("hard_deadline", True):
        keys = tuple(key for key in keys if key == "assessment_at")
    values = [definition.get(key) for key in keys if definition.get(key)]
    instants = [_dt(value, tz) for value in values]
    preparation = assessment_preparation_cutoff(definition, tz)
    if preparation:
        instants.append(preparation)
    return min(instants, key=lambda item: item.astimezone(timezone.utc), default=None)


def _daily_capacity(day, settings, definition, tz):
    """A forecast cannot extend beyond the task's explicit eligibility bounds."""
    start = _dt(f"{day['date']}T{settings.get('work_start', '08:00')}", tz)
    if day.get("available_start"):
        start = max(start, _dt(day["available_start"], tz))
    end = _dt(f"{day['date']}T{settings.get('work_end', '22:00')}", tz)
    if definition.get("earliest_start"):
        start = max(start, _dt(definition["earliest_start"], tz))
    cutoff = _cutoff(definition, tz)
    if cutoff:
        end = min(end, cutoff)
    return max(0, min(int(day.get("capacity_minutes", 0)), _minutes(start, end)))


def forecast_horizon(date, settings, definitions, assignments, sessions, context):
    """Read-only capacity/target forecast, never a set of future clock times.

    Assignment eligibility remains Sunday–Saturday. A session target estimates
    useful effort, not an assertion that its task will finish after that effort.
    """
    tz = ZoneInfo(settings.get("timezone", "America/Toronto"))
    reference = _dt(f"{date}T{settings.get('work_start', '08:00')}", tz)
    days = [deepcopy(day) for day in context.get("days", []) if day["date"] >= date]
    days.sort(key=lambda day: day["date"])
    if days and days[0]["date"] == date and days[0].get("available_start"):
        reference = max(reference, _dt(days[0]["available_start"], tz))
    lookup = {item["id"]: item for item in definitions}
    all_assignments = {item["id"]: item for item in assignments + context.get("forecast_assignments", [])}
    all_sessions = {item["id"]: item for item in sessions + context.get("forecast_sessions", [])}
    risks, forecast_inputs = [], []
    for assignment in all_assignments.values():
        source = lookup.get(assignment.get("task_definition_id"))
        if not source:
            continue
        task = _effective_definition({**source, **assignment.get("effective_definition", {})}, assignment)
        if source.get("_definition_status", source.get("status")) == "completed":
            task["status"] = "completed"
        project = task.get("project") or {}
        if (assignment.get("removed_from_week") or source.get("deleted_at")
                or assignment.get("status") in {"paused", "completed", "skipped", "archived"}
                or task.get("status") in {"paused", "completed", "skipped", "archived"}
                or project.get("status") in {"paused", "archived"} and not task.get("schedule_inactive_project")):
            continue
        own = [item for item in all_sessions.values() if item.get("assignment_id") == assignment["id"] and item.get("status") != "skipped"]
        minimum = int(assignment.get("min_sessions_per_week", task.get("min_sessions_per_week", 0)))
        session_minutes = int(assignment.get("session_minutes", task.get("session_minutes", 60)))
        completed = sum(int(item.get("completed_minutes", 0)) >= int(item["target_minutes"]) for item in own)
        partial = sum(max(0, int(item["target_minutes"]) - int(item.get("completed_minutes", 0))) for item in own if int(item.get("completed_minutes", 0)) < int(item["target_minutes"]))
        estimate = partial + max(0, minimum - len(own)) * session_minutes
        verified_minutes = sum(int(item.get("completed_minutes", 0)) for item in own)
        planned_minutes = sum(int(item.get("planned_minutes", 0)) for item in own)
        elapsed_minutes = sum(int(item.get("elapsed_scheduled_minutes", 0)) for item in own)
        future_minutes = sum(int(item.get("future_scheduled_minutes", 0)) for item in own)
        cutoff = _cutoff(task, tz, hard_only=False)
        preparation_cutoff = assessment_preparation_cutoff(task, tz)
        related = task.get("related_activity") or {}
        related_dates = ([related["assessment_start"]] if related.get("assessment_start") else [item["start"] for item in related.get("occurrences", []) if item.get("start")]) if related.get("category") == "assessment" else []
        upcoming = sorted((_dt(value, tz) for value in related_dates), key=lambda value: value.astimezone(timezone.utc))
        prep = next((value for value in upcoming if value >= reference), None)
        risk_cutoff = min([value for value in (cutoff, prep) if value], default=None)
        week_end = (Date.fromisoformat(assignment["week_start"]) + timedelta(days=6)).isoformat()
        eligible = [day for day in days if assignment["week_start"] <= day["date"] <= week_end]
        available = 0
        for day in eligible:
            capacity = _daily_capacity(day, settings, task, tz)
            if risk_cutoff:
                start = _dt(day.get("available_start") or f"{day['date']}T{settings.get('work_start', '08:00')}", tz)
                capacity = min(capacity, max(0, _minutes(start, risk_cutoff)))
            available += capacity
        hours = (risk_cutoff.astimezone(timezone.utc) - reference.astimezone(timezone.utc)).total_seconds() / 3600 if risk_cutoff else None
        risk = "overdue" if hours is not None and hours <= 0 else "at_risk" if risk_cutoff and max(0, estimate - future_minutes) > available else "approaching" if hours is not None and hours <= 14 * 24 else "none"
        # A met target still leaves an explicitly unfinished task open, with
        # unknown extra effort; never convert zero target remainder to done.
        reason = (f"{estimate} estimated minutes toward the weekly target; {available} forecast minutes available in its assigned week"
                  + (" before the applicable date." if risk_cutoff else ".")
                  + (f" Explicit assessment preparation must finish before the linked assessment starts at {preparation_cutoff.isoformat()}; stored task dates are unchanged." if preparation_cutoff else " Linked assessment supplies preparation context, not an invented task cutoff." if prep and (not cutoff or prep < cutoff) else "")
                  + (" Target is met; actual task completion remains unconfirmed and may need additional work." if completed >= minimum else " Actual completion may need fewer or more sessions."))
        risks.append({"task_definition_id": task["id"], "assignment_id": assignment["id"],
                      "title": task.get("title", "Task"), "week_start": assignment["week_start"],
                      "cutoff": cutoff.isoformat() if cutoff else None,
                      "preparation_at": prep.isoformat() if prep else None,
                      "preparation_cutoff": preparation_cutoff.isoformat() if preparation_cutoff else None,
                      "remaining_estimated_minutes": estimate, "available_before_cutoff_minutes": available,
                      "verified_completed_minutes": verified_minutes, "planned_minutes": planned_minutes,
                      "elapsed_scheduled_minutes": elapsed_minutes,
                      "completed_sessions": completed, "deadline_risk": risk, "reason": reason})
        forecast_inputs.append((risks[-1], task, eligible, risk_cutoff, max(0, estimate - future_minutes)))
    # Allocate only aggregate minutes to expose competition. No exact times or
    # persisted proposals are produced. Explicit cutoffs are considered first;
    # remaining importance breaks ties, never identity or display-name merging.
    budgets = {day["date"]: max(0, int(day.get("capacity_minutes", 0))) for day in days}
    for row, task, eligible, cutoff, needed in sorted(forecast_inputs, key=lambda item: (
            item[3].astimezone(timezone.utc).timestamp() if item[3] else float("inf"),
            -float(item[1].get("importance", 5)), item[0]["assignment_id"])):
        allocated = 0
        for day in eligible:
            capacity = min(budgets[day["date"]], _daily_capacity(day, settings, task, tz))
            if cutoff:
                start = _dt(day.get("available_start") or f"{day['date']}T{settings.get('work_start', '08:00')}", tz)
                capacity = min(capacity, max(0, _minutes(start, cutoff)))
            amount = min(max(0, needed - allocated), capacity)
            budgets[day["date"]] -= amount
            allocated += amount
        row["forecast_allocated_minutes"] = allocated
        row["estimated_shortfall_minutes"] = max(0, needed - allocated)
        if row["estimated_shortfall_minutes"]:
            row["reason"] += f" Competing targets leave an estimated {row['estimated_shortfall_minutes']} minutes unallocated in this forecast."
            if cutoff and row["deadline_risk"] != "overdue":
                row["deadline_risk"] = "at_risk"
    for day in days:
        day["forecast_minutes"] = max(0, int(day.get("capacity_minutes", 0))) - budgets[day["date"]]
    current_week_end = (Date.fromisoformat(date) + timedelta(days=6 - ((Date.fromisoformat(date).weekday() + 1) % 7))).isoformat()
    for row, task, _, cutoff, _ in forecast_inputs:
        future_capacity = 0
        if cutoff and cutoff.date().isoformat() > current_week_end and days and cutoff.date().isoformat() <= days[-1]["date"]:
            for day in days:
                if day["date"] <= current_week_end:
                    continue
                start = _dt(f"{day['date']}T{settings.get('work_start', '08:00')}", tz)
                future_capacity += min(budgets[day["date"]], max(0, _minutes(start, cutoff)))
            # A bounded advance-work preference responds to future congestion;
            # it creates no task cutoff or entitlement to work in another week.
            useful_buffer = max(1, int(task.get("session_minutes", 60)) * 2)
            advance_bonus = max(0, min(60, round(60 * (1 - future_capacity / useful_buffer))))
        else:
            advance_bonus = 0
        shared_risk_bonus = min(60, round(60 * row["estimated_shortfall_minutes"] / max(1, row["remaining_estimated_minutes"]))) if cutoff else 0
        row["future_capacity_before_cutoff_minutes"] = future_capacity
        row["preparation_urgency_bonus"] = max(advance_bonus, shared_risk_bonus)
        if advance_bonus:
            row["reason"] += f" Only {future_capacity} unclaimed forecast minutes remain after this week before the applicable date; advancing work now earns {advance_bonus} bounded preparation points."
    return {"start": date, "end": days[-1]["date"] if days else date, "forecast_only": True,
            "capacity_minutes": sum(max(0, int(day.get("capacity_minutes", 0))) for day in days),
            "days": days, "task_risks": risks,
            "limitations": ["Approximate capacity forecast; daily routes, fragmentation, recovery and competing tasks can reduce feasibility.",
                            "Future assignments and saved plans are read only. Work stays within its assigned Sunday–Saturday week.",
                            "Session targets estimate effort, not task completion. Generic linked assessments are soft context; explicitly declared assessment preparation must precede the actual assessment start."]}


def prepare_weekly_tasks(date, settings, definitions, assignments, sessions,
                         week_context, mode="balanced"):
    """Return daily solver units, deterministic session proposals and forecasts.

    ``week_context`` contains ``days`` ({date, capacity_minutes}) and ``chunks``
    ({id, logical_session_id, start, end, status, locked?, preserve?}). Completed minutes on
    each session are authoritative; completed chunks are never counted twice.
    Other-day pending chunks reserve that same session's work. Current-day todo
    chunks are replaceable unless locked, in progress, or explicitly preserved
    by the service as elapsed saved work. Preserving a chunk grants no credit.
    """
    tz = ZoneInfo(settings.get("timezone", "America/Toronto"))
    planning_date = Date.fromisoformat(date)
    week_start = planning_date - timedelta(days=(planning_date.weekday() + 1) % 7)
    week_end = week_start + timedelta(days=6)
    raw_days = week_context.get("days", [])
    days = [dict(day) for day in raw_days if date <= day["date"] <= week_end.isoformat()]
    if not days:
        work_start = _dt(f"{date}T{settings.get('work_start', '08:00')}", tz)
        work_end = _dt(f"{date}T{settings.get('work_end', '22:00')}", tz)
        days = [{"date": date, "capacity_minutes": max(0, _minutes(work_start, work_end))}]
    days.sort(key=lambda day: day["date"])
    day_index = next((i for i, day in enumerate(days) if day["date"] == date), None)
    definition_map = {item["id"]: item for item in definitions}
    session_map = {item["id"]: deepcopy(item) for item in sessions}
    chunks_by_session = {}
    for chunk in week_context.get("chunks", []):
        chunks_by_session.setdefault(chunk.get("logical_session_id"), []).append(chunk)
    prepared = {"tasks": [], "sessions": [], "weekly_progress": [], "date": date,
                "week_start": week_start.isoformat(), "week_end": week_end.isoformat(),
                "forecast": "Capacity forecast; actual daily commitments, routes and hard constraints are validated by the daily optimizer.",
                "_session_forecasts": {}, "_daily_task_limits": [], "context_factors": []}
    prepared["horizon_forecast"] = forecast_horizon(date, settings, definitions, assignments, sessions, week_context)
    risk_by_assignment = {item["assignment_id"]: item for item in prepared["horizon_forecast"]["task_risks"]}
    model = cp_model.CpModel()
    terms, session_variables, assignment_details = [], [], []
    capacities = [max(0, int(day.get("capacity_minutes", 0))) for day in days]
    day_allocations = [[] for _ in days]
    for assignment in assignments:
        if assignment.get("week_start") != week_start.isoformat():
            continue
        source_definition = definition_map.get(assignment.get("task_definition_id"))
        if not source_definition:
            continue
        definition = _effective_definition(source_definition, assignment)
        prepared["_daily_task_limits"].append({
            "id": "definition:" + definition["id"], "task_definition_id": definition["id"],
            "title": definition.get("title", "Task"), "status": "completed", "remaining_minutes": 0,
            "min_sessions_per_day": definition.get("min_sessions_per_day", 1),
            "max_sessions_per_day": definition.get("max_sessions_per_day"),
        })
        own_sessions = sorted([item for item in session_map.values() if item.get("assignment_id") == assignment["id"]], key=lambda item: item.get("index", 0))
        minimum = int(assignment.get("min_sessions_per_week", definition.get("min_sessions_per_week", 0)))
        completed = sum(item.get("status") != "skipped" and int(item.get("completed_minutes", 0)) >= int(item["target_minutes"]) for item in own_sessions)
        status = assignment.get("status", "active")
        project = definition.get("project") or {}
        excluded = (bool(source_definition.get("deleted_at")) or bool(assignment.get("removed_from_week"))
                    or status in {"paused", "archived", "completed", "skipped"}
                    or definition.get("status") in {"paused", "archived", "completed", "skipped"}
                    or project.get("status") in {"paused", "archived"} and not definition.get("schedule_inactive_project", False))
        importance = float(definition.get("importance", 5))
        project_bonus = _project_priority_bonus(definition)
        difficulty = float(definition.get("difficulty", 0))
        cutoff = _cutoff(definition, tz, hard_only=False)
        hours_left = ((cutoff.astimezone(timezone.utc) - _dt(f"{date}T00:00", tz).astimezone(timezone.utc)).total_seconds() / 3600) if cutoff else None
        # Fourteen-day gradient includes approaching dates beyond Sunday.
        urgency = max(0, 7 - math.ceil(max(0, hours_left or 0) / 48)) if cutoff else 0
        related_bonus = _related_assessment_bonus(definition, _dt(f"{date}T{settings.get('work_start', '08:00')}", tz))
        intelligence = interpret_task_context(definition, _dt(f"{date}T{settings.get('work_start', '08:00')}", tz), week_context.get("events", []))
        risk = risk_by_assignment.get(assignment["id"], {})
        intelligence["deadline_risk"] = risk.get("deadline_risk", "none")
        intelligence["deadline_reason"] = risk.get("reason", "")
        # Linked assessment urgency and forecast preparation share one bounded
        # contextual allowance rather than double-rewarding the same evidence.
        intelligence["preparation_urgency_bonus"] = min(max(0, 60 - related_bonus), risk.get("preparation_urgency_bonus", 0))
        context_bonus = intelligence["context_bonus"] + intelligence["preparation_urgency_bonus"]
        prepared["context_factors"].append({"task_definition_id": definition["id"], "assignment_id": assignment["id"],
                                             "title": definition.get("title", "Task"), **deepcopy(intelligence)})
        # Missed recurring targets are not an automatic late-week catch-up
        # quota. Actual deadlines retain their full protection. Explicitly
        # preserved work remains visible and never becomes completion credit.
        recurring = assignment.get("source") == "recurring" or bool(definition.get("recurrence"))
        remaining_days = (week_end - planning_date).days + 1
        achievable = (completed + math.ceil(max(0, minimum - completed) * remaining_days / 7)
                      if recurring and not cutoff else minimum)
        achievable = min(minimum, max(completed, achievable))
        eligible_capacities = [_daily_capacity(day, settings, definition, tz) for day in days]
        total_capacity = sum(eligible_capacities)
        target = int(assignment.get("session_minutes", definition.get("session_minutes", 60)))
        allow_splitting = bool(definition.get("allow_splitting", False))
        chunk_minimum = max(1, int(definition.get("min_chunk_minutes") or target)) if allow_splitting else target
        # Extras have a positive, diminishing reason to exist. Low-importance
        # zero-minimum assignments never manufacture work to fill spare time.
        extra_scores = []
        advance_multiplier = workload_profile(settings.get("workload_level", "medium"))["advance_work_multiplier"]
        # Only supported importance/date/project/context evidence can justify
        # advance work. A workload preference scales that evidence; it never
        # turns an unimportant zero-goal definition into a work entitlement.
        extra_evidence = ((importance - 6) * 20
                          + urgency * (30 if mode == "deadline" else 20)
                          + project_bonus / 5 + related_bonus + context_bonus)
        physical_count = max(1, total_capacity // max(5, min(target, max(eligible_capacities, default=0) or 1)))
        extra_index = 0
        # Bound construction by physical capacity, including already completed
        # extras so their consumed marginal value is never reset on replanning.
        while extra_index < physical_count + max(0, completed - minimum):
            score = round(extra_evidence * advance_multiplier - extra_index * 30)
            if score <= 0:
                break
            extra_scores.append(score)
            extra_index += 1
        if definition.get("finite_work_minutes") is not None or definition.get("legacy_task_id"):
            extra_scores = []
        completed_extras = max(0, completed - minimum)
        desired_count = min(max(0, achievable + len(extra_scores) - completed), physical_count)
        existing_active = [item for item in own_sessions if item.get("status") not in {"completed", "skipped"} and int(item.get("completed_minutes", 0)) < int(item["target_minutes"])]
        next_index = max((item.get("index", 0) for item in own_sessions), default=-1) + 1
        for _ in range(max(0, desired_count - len(existing_active))):
            proposal = {"id": _session_id(assignment["id"], next_index), "assignment_id": assignment["id"],
                        "index": next_index, "target_minutes": target, "completed_minutes": 0, "status": "todo"}
            existing_active.append(proposal)
            next_index += 1
        remaining_goal = max(0, achievable - completed)
        def has_reserved_work(session):
            return any(chunk.get("status") not in {"completed", "skipped"}
                       and (_dt(chunk["start"], tz).date().isoformat() != date
                            or chunk.get("locked") or chunk.get("preserve")
                            or chunk.get("status") == "in_progress")
                       for chunk in chunks_by_session.get(session["id"], []))
        # A prior, higher-workload proposal is not useful work merely because
        # its ID exists. Exclude unsupported extras before pacing quantiles and
        # work budgets, while retaining partial/reserved work for continuation.
        existing_active = [session for position, session in enumerate(existing_active)
                           if position < remaining_goal
                           or completed_extras + max(0, position - remaining_goal) < len(extra_scores)
                           or int(session.get("completed_minutes", 0)) > 0 or has_reserved_work(session)]
        detail = {"assignment": assignment, "definition": definition, "minimum": minimum,
                  "achievable": achievable, "intelligence": intelligence,
                  "completed": completed, "excluded": excluded, "session_variables": [],
                  "capacities": eligible_capacities, "reserved_complete": 0}
        assignment_details.append(detail)
        for session_position, session in enumerate(existing_active):
            session = deepcopy(session)
            sid = session["id"]
            session_target = int(session["target_minutes"])
            actual_completed = min(session_target, int(session.get("completed_minutes", 0)))
            remaining = max(0, session_target - actual_completed)
            reserved, preserved_today, reserved_chunks = 0, 0, []
            for chunk in chunks_by_session.get(sid, []):
                if chunk.get("status") in {"completed", "skipped"}:
                    continue
                chunk_date = _dt(chunk["start"], tz).date().isoformat()
                amount = _minutes(_dt(chunk["start"], tz), _dt(chunk["end"], tz))
                if chunk_date != date:
                    reserved += amount
                    reserved_chunks.append(chunk)
                elif chunk.get("locked") or chunk.get("status") == "in_progress" or chunk.get("preserve"):
                    reserved += amount
                    preserved_today += amount
            needed = max(0, remaining - reserved)
            complete = model.new_bool_var(f"complete_{sid}")
            allocations, presences = [], []
            for i, capacity in enumerate(eligible_capacities):
                cap = min(needed, capacity) if not excluded and session.get("status") != "paused" else 0
                amount = model.new_int_var(0, cap, f"minutes_{sid}_{i}")
                present = model.new_bool_var(f"present_{sid}_{i}")
                model.add(amount <= cap * present)
                lower = min(chunk_minimum, needed) if actual_completed or reserved else min(chunk_minimum, session_target)
                if allow_splitting:
                    model.add(amount >= lower).only_enforce_if(present)
                else:
                    model.add(amount == needed).only_enforce_if(present)
                allocations.append(amount)
                presences.append(present)
                # Exact-minute work still starts on five-minute boundaries and
                # needs recovery. Reserve rounded work+recovery in the forecast
                # so one-minute sessions do not claim impossible daily counts.
                rest = max(0, int(settings.get("break_minutes", 10)))
                cost_grid = model.new_int_var(0, max(0, (cap + rest + 4) // 5), f"cost_{sid}_{i}")
                model.add(cost_grid * 5 >= amount + rest * present)
                model.add(cost_grid * 5 <= amount + (rest + 4) * present)
                day_allocations[i].append(cost_grid * 5)
            if not allow_splitting:
                model.add(sum(presences) <= 1)
            model.add(sum(allocations) <= needed)
            model.add(sum(allocations) == needed).only_enforce_if(complete)
            if needed:
                model.add(sum(allocations) < needed).only_enforce_if(complete.Not())
            else:
                model.add(complete == 1)
                detail["reserved_complete"] += 1
            remaining_goal = max(0, achievable - completed)
            required_session = session_position < remaining_goal
            extra_position = completed_extras + max(0, session_position - remaining_goal)
            marginal = (300 + importance * 30 + urgency * (80 if mode == "deadline" else 40) + project_bonus + related_bonus + context_bonus) if required_session else (extra_scores[extra_position] if extra_position < len(extra_scores) else 30 if actual_completed or reserved else 0)
            if marginal <= 0:
                # Previously proposed sessions remain in history, but reducing
                # workload must not schedule zero-value work through a tie.
                for allocation in allocations:
                    model.add(allocation == 0)
            terms.append(sum(allocations) * max(0, round(marginal)))
            for i, allocation in enumerate(allocations):
                if definition.get("preferred_days") and Date.fromisoformat(days[i]["date"]).weekday() not in definition["preferred_days"]:
                    terms.append(-allocation * 70)
            terms.append(complete * max(0, round(marginal * min(session_target, total_capacity + reserved) / 2)))
            if total_capacity and existing_active:
                # Spread session starts at equal capacity quantiles, beginning
                # now, instead of consuming the entire weekly goal on day one.
                quantile = session_position * total_capacity / len(existing_active)
                cumulative, preferred_day = 0, 0
                for i, capacity in enumerate(eligible_capacities):
                    if capacity and cumulative + capacity > quantile:
                        preferred_day = i
                        break
                    cumulative += capacity
                for i, allocation in enumerate(allocations):
                    terms.append(-allocation * abs(i - preferred_day) * 10)
            variable = {"session": session, "definition": definition, "assignment": assignment,
                        "allocations": allocations, "presences": presences, "complete": complete, "needed": needed,
                        "preserved_today": preserved_today, "reserved": reserved,
                        "remaining": remaining, "value": max(1, round(marginal)), "excluded": excluded,
                        "chunk_minimum": chunk_minimum, "allow_splitting": allow_splitting,
                        "reserved_chunks": reserved_chunks}
            session_variables.append(variable)
            detail["session_variables"].append(variable)
        # The minimum is soft: a finite weighted shortfall penalty competes with
        # actual task importance/urgency. It never overrides a hard constraint.
        attainable_minimum = min(achievable, completed + len(detail["session_variables"]))
        shortfall = model.new_int_var(0, max(0, attainable_minimum), f"shortfall_{assignment['id']}")
        model.add(shortfall >= attainable_minimum - completed - sum(item["complete"] for item in detail["session_variables"]))
        terms.append(-shortfall * round(4000 + importance * 600 + urgency * 600))
        detail["shortfall"] = shortfall
        work_to_plan = min(total_capacity, sum(item["needed"] for item in detail["session_variables"]))
        for i, capacity in enumerate(eligible_capacities):
            ideal = math.ceil(work_to_plan * capacity / total_capacity) if total_capacity else 0
            daily_minimum = definition.get("min_sessions_per_day", 1)
            if daily_minimum > 1:
                # Pacing must allow a useful batch on an active day. Otherwise
                # its per-minute penalty would defeat the conditional minimum
                # before the authoritative daily solver ever saw two units.
                batch = min(daily_minimum, len(detail["session_variables"])) * min(target, capacity)
                ideal = min(capacity, max(ideal, batch))
            over = model.new_int_var(0, max(0, capacities[i]), f"pacing_{assignment['id']}_{i}")
            model.add(over >= sum(item["allocations"][i] for item in detail["session_variables"]) - ideal)
            # Difficulty affects distribution, never the value of doing work.
            terms.append(-over * round(100 + difficulty * 8))
    # Count reserved *chunks*, including completed history, rather than logical
    # sessions. One session may already occupy several slots on the same date.
    assignment_definitions = {item["id"]: item["task_definition_id"] for item in assignments}
    reserved_counts = {}
    for chunk in week_context.get("chunks", []):
        if chunk.get("status") == "skipped":
            continue
        chunk_date = _dt(chunk["start"], tz).date().isoformat()
        if chunk_date == date and not (chunk.get("locked") or chunk.get("preserve")
                                       or chunk.get("status") in {"completed", "in_progress"}):
            continue
        session = session_map.get(chunk.get("logical_session_id"), {})
        definition_id = chunk.get("task_definition_id") or assignment_definitions.get(session.get("assignment_id"))
        key = (definition_id, chunk_date)
        reserved_counts[key] = reserved_counts.get(key, 0) + 1
    for policy in prepared["_daily_task_limits"]:
        definition_id = policy["task_definition_id"]
        own_variables = [item for item in session_variables if item["definition"]["id"] == definition_id]
        for i, day in enumerate(days):
            presences = [item["presences"][i] for item in own_variables]
            reserved_count = reserved_counts.get((definition_id, day["date"]), 0)
            maximum = policy["max_sessions_per_day"]
            if maximum is not None:
                # Existing over-limit history is preserved and reported by the
                # daily validator; it leaves no allowance for additional work.
                model.add(sum(presences) <= max(0, maximum - reserved_count))
            minimum = policy["min_sessions_per_day"]
            if minimum > 1 and presences:
                bounded_minimum = min(minimum, reserved_count + len(presences))
                active_day = model.new_bool_var(f"daily_active_{definition_id}_{i}")
                model.add(sum(presences) + reserved_count >= 1).only_enforce_if(active_day)
                model.add(sum(presences) + reserved_count == 0).only_enforce_if(active_day.Not())
                shortfall = model.new_int_var(0, bounded_minimum, f"daily_shortfall_{definition_id}_{i}")
                model.add(shortfall >= bounded_minimum - reserved_count - sum(presences)).only_enforce_if(active_day)
                model.add(shortfall == 0).only_enforce_if(active_day.Not())
                # A finite preference competes with pacing; it creates no
                # sessions and cannot turn a zero-goal routine into filler.
                terms.append(-shortfall * max(1, 15000 // (len(days) * bounded_minimum)))
    # Dependency references are definition IDs. Each unmet prerequisite goal
    # must be available by the dependent day; the daily model enforces the exact
    # same-day ordering and rejects cycles or unavailable work independently.
    details_by_definition = {detail["definition"]["id"]: detail for detail in assignment_details}
    dependency_graph = {key: set(detail["definition"].get("dependencies", [])) & details_by_definition.keys()
                        for key, detail in details_by_definition.items()}
    while True:
        ready = {key for key, dependencies in dependency_graph.items() if not dependencies}
        if not ready:
            break
        dependency_graph = {key: dependencies - ready for key, dependencies in dependency_graph.items() if key not in ready}
    for variable in session_variables:
        if variable["definition"]["id"] in dependency_graph:
            for present in variable["presences"]:
                model.add(present == 0)
        for dependency_id in variable["definition"].get("dependencies", []):
            prerequisite = details_by_definition.get(dependency_id)
            if prerequisite and prerequisite["completed"] >= max(1, prerequisite["minimum"]):
                continue
            if not prerequisite:
                for present in variable["presences"]:
                    model.add(present == 0)
                continue
            required_count = max(1, prerequisite["minimum"] - prerequisite["completed"])
            prerequisites = prerequisite["session_variables"][:required_count]
            if not prerequisites:
                for present in variable["presences"]:
                    model.add(present == 0)
            for before in prerequisites:
                for i, present in enumerate(variable["presences"]):
                    reserved_by_day = sum(_minutes(_dt(chunk["start"], tz), _dt(chunk["end"], tz))
                                          for chunk in before["reserved_chunks"]
                                          if _dt(chunk["end"], tz).date().isoformat() <= days[i]["date"])
                    required_minutes = max(0, before["remaining"] - before["preserved_today"] - reserved_by_day)
                    model.add(sum(before["allocations"][:i + 1]) >= required_minutes).only_enforce_if(present)
    for i, capacity in enumerate(capacities):
        model.add(sum(day_allocations[i]) <= capacity)
    model.maximize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.1, float(settings.get("weekly_solver_seconds", 2)))
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 42
    result = solver.solve(model)
    feasible = result in {cp_model.OPTIMAL, cp_model.FEASIBLE}
    advance_candidates = workload_profile(settings.get("workload_level", "medium")).get("allow_advance_candidates", False)
    for variable in session_variables:
        definition, session, assignment = variable["definition"], variable["session"], variable["assignment"]
        prepared["sessions"].append(session)
        amount = solver.value(variable["allocations"][day_index]) if feasible and day_index is not None else 0
        future = sum(solver.value(item) for i, item in enumerate(variable["allocations"]) if i != day_index) if feasible else 0
        prepared["_session_forecasts"][session["id"]] = {
            "assignment_id": assignment["id"], "target_minutes": session["target_minutes"],
            "completed_minutes": session.get("completed_minutes", 0), "future_minutes": future,
            "reserved_other_minutes": variable["reserved"] - variable["preserved_today"],
        }
        amount += variable["preserved_today"]
        planned_amount = amount
        # Forecast placement is pacing advice. Ambitious profiles may let the
        # authoritative daily model advance useful unreserved work from later
        # in this same forecast, while keeping the forecast itself unchanged.
        lower = min(variable["chunk_minimum"], variable["needed"]) if (
            session.get("completed_minutes", 0) or variable["reserved"]) else variable["chunk_minimum"]
        available_today = _daily_capacity(days[day_index], settings, definition, tz) if day_index is not None else 0
        opportunity = (advance_candidates and feasible and future > 0
                       and not variable["excluded"] and session.get("status") != "paused"
                       and definition["id"] not in dependency_graph
                       and available_today >= (lower if variable["allow_splitting"] else variable["needed"]))
        maximum = definition.get("max_sessions_per_day")
        if maximum is not None and reserved_counts.get((definition["id"], date), 0) >= maximum:
            opportunity = False
        if any(dependency not in details_by_definition for dependency in definition.get("dependencies", [])):
            opportunity = False
        if opportunity:
            amount = variable["needed"] + variable["preserved_today"]
        if not amount:
            continue
        original_remaining = variable["remaining"]
        minimum = min(lower, amount)
        unit = {"id": "session:" + session["id"], "title": definition.get("title", definition.get("name", "Task")),
                "kind": "project" if definition.get("project_id") else "academic", "status": "todo",
                "task_definition_id": definition["id"], "task_assignment_id": assignment["id"],
                "task_type": definition.get("task_type", "academic"),
                "academic_subtype": definition.get("academic_subtype"),
                "logical_session_id": session["id"], "duration_minutes": amount, "remaining_minutes": amount,
                "splittable": variable["allow_splitting"], "min_session_minutes": minimum,
                "max_session_minutes": amount, "exact_minutes": True,
                "weekly_planned_minutes": planned_amount, "weekly_opportunity": amount > planned_amount,
                "priority": max(1, min(5, math.ceil(float(definition.get("importance", 5)) / 2))),
                "weekly_value": variable["value"], "weekly_full_bonus": 0, "difficulty": definition.get("difficulty", 0),
                "planning_context": deepcopy(details_by_definition[definition["id"]]["intelligence"]),
                "hard_deadline": definition.get("hard_deadline", True),
                "dependencies": [], "location_id": definition.get("location_id"),
                "location_mode": definition.get("location_mode") or ("required" if definition.get("location_id") else "unspecified"),
                "allow_alternative_locations": definition.get("allow_alternative_locations", False),
                "alternative_location_ids": list(definition.get("alternative_location_ids", [])),
                **{key: deepcopy(definition[key]) for key in ("location_requirements", "location_suitability") if key in definition},
                **({"related_activity": deepcopy(definition["related_activity"])} if definition.get("related_activity") else {}),
                "session_target_minutes": session["target_minutes"], "session_remaining_minutes": original_remaining,
                "min_sessions_per_day": definition.get("min_sessions_per_day", 1),
                "max_sessions_per_day": definition.get("max_sessions_per_day"),
                **{key: definition[key] for key in ("earliest_start", "due_at", "assessment_at", "deadline_at", "preferred_start", "preferred_end", "preferred_time_of_day", "project", "project_id", "schedule_inactive_project", "room") if definition.get(key) is not None}}
        prepared["tasks"].append(unit)
    units_by_session = {unit["logical_session_id"]: unit for unit in prepared["tasks"]}
    for unit in prepared["tasks"]:
        definition = details_by_definition[unit["task_definition_id"]]["definition"]
        for dependency_id in definition.get("dependencies", []):
            prerequisite = details_by_definition.get(dependency_id)
            if prerequisite and prerequisite["completed"] >= max(1, prerequisite["minimum"]):
                continue
            if not prerequisite:
                unit["dependencies"].append("definition:" + dependency_id)
                continue
            required_count = max(1, prerequisite["minimum"] - prerequisite["completed"])
            for before in prerequisite["session_variables"][:required_count]:
                sid = before["session"]["id"]
                unit["dependencies"].append(units_by_session[sid]["id"] if sid in units_by_session else "session:" + sid)
    for detail in assignment_details:
        planned = sum(solver.value(item["complete"]) for item in detail["session_variables"]) if feasible else detail["reserved_complete"]
        today_minutes = sum(solver.value(item["allocations"][day_index]) for item in detail["session_variables"]) if feasible and day_index is not None else 0
        prepared["weekly_progress"].append({"assignment_id": detail["assignment"]["id"],
            "task_definition_id": detail["definition"]["id"], "week_start": week_start.isoformat(),
            "minimum_sessions": detail["minimum"], "completed_sessions": detail["completed"],
            "achievable_target_sessions": detail["achievable"],
            "deferred_target_sessions": max(0, detail["minimum"] - detail["achievable"]),
            "expected_sessions": detail["completed"] + planned,
            "expected_shortfall": max(0, detail["minimum"] - detail["completed"] - planned),
            "planned_today_minutes": today_minutes, "excluded": detail["excluded"],
            "forecast": True, "solver_status": solver.status_name(result)})
    return prepared


def internalize_weekly_blocks(blocks, prepared):
    """Adapt external definition IDs to distinct logical units for validation."""
    units = {unit["logical_session_id"]: unit for unit in prepared["tasks"]}
    result = deepcopy(blocks)
    for block in result:
        if block.get("logical_session_id") in units:
            block["task_id"] = units[block["logical_session_id"]]["id"]
    return result


def validate_weekly_blocks(blocks, settings, route_minutes, prepared, legacy_tasks=None, protected_blocks=None):
    return validate_blocks(internalize_weekly_blocks(blocks, prepared), settings, route_minutes,
                           list(legacy_tasks or []) + prepared["tasks"] + prepared.get("_daily_task_limits", []),
                           protected_blocks=internalize_weekly_blocks(protected_blocks or [], prepared))


def finalize_weekly_result(result, prepared):
    """Expose definition IDs and stable session/chunk IDs without unit ID leaks."""
    result = deepcopy(result)
    units = {unit["id"]: unit for unit in prepared["tasks"]}
    chunk_counts, actual_minutes = {}, {}
    for block in result.get("blocks", []):
        unit = units.get(block.get("task_id"))
        if not unit:
            continue
        sid = unit["logical_session_id"]
        chunk_counts[sid] = chunk_counts.get(sid, 0) + 1
        if block.get("status") not in {"completed", "skipped"}:
            actual_minutes[sid] = actual_minutes.get(sid, 0) + _minutes(
                _dt(block["start"], ZoneInfo("UTC")), _dt(block["end"], ZoneInfo("UTC")))
        block.update(task_id=unit["task_definition_id"], task_definition_id=unit["task_definition_id"],
                     task_assignment_id=unit["task_assignment_id"], logical_session_id=sid,
                     chunk_index=chunk_counts[sid] - 1)
    for collection in ("unallocated", "excluded_tasks"):
        for item in result.get(collection, []):
            unit = units.get(item.get("task_id"))
            if unit:
                item.update(task_id=unit["task_definition_id"], logical_session_id=unit["logical_session_id"],
                            task_assignment_id=unit["task_assignment_id"])
    for item in result.get("stats", {}).get("tail_diagnostics", {}).get("remaining_candidates", []):
        unit = units.get(item.get("task_id"))
        if unit:
            item.update(task_id=unit["task_definition_id"], logical_session_id=unit["logical_session_id"],
                        task_assignment_id=unit["task_assignment_id"], title=unit["title"])
    result["weekly_progress"] = deepcopy(prepared["weekly_progress"])
    result["horizon_forecast"] = deepcopy(prepared.get("horizon_forecast", {}))
    result["planning_context"] = {"version": "rules-v1", "task_factors": deepcopy(prepared.get("context_factors", [])),
                                  "interpretation": "Deterministic local rules influence soft priorities, focus and recovery. No external AI was called."}
    forecasts = prepared.get("_session_forecasts", {})
    future_reduced = 0
    for progress in result["weekly_progress"]:
        predicted = progress["completed_sessions"]
        for sid, forecast in forecasts.items():
            if forecast["assignment_id"] != progress["assignment_id"]:
                continue
            # Advanced work replaces the same session's future prediction; a
            # saved other-day reservation is never moved or counted twice.
            actual = actual_minutes.get(sid, 0)
            future = min(forecast["future_minutes"], max(0, forecast["target_minutes"]
                         - forecast["completed_minutes"] - forecast["reserved_other_minutes"] - actual))
            future_reduced += forecast["future_minutes"] - future
            total = (forecast["completed_minutes"] + future
                     + forecast["reserved_other_minutes"] + actual)
            predicted += int(total >= forecast["target_minutes"])
        progress["expected_sessions"] = predicted
        progress["expected_shortfall"] = max(0, progress["minimum_sessions"] - predicted)
        progress["planned_today_minutes"] = sum(actual_minutes.get(sid, 0) for sid, forecast in forecasts.items()
                                                  if forecast["assignment_id"] == progress["assignment_id"])
    progress_by_assignment = {item["assignment_id"]: item for item in result["weekly_progress"]}
    existing_unallocated = {item.get("task_id") for item in result.get("unallocated", [])}
    for risk in result["horizon_forecast"].get("task_risks", []):
        preparation = risk.get("preparation_cutoff")
        progress = progress_by_assignment.get(risk["assignment_id"])
        if (not preparation or not progress or progress.get("excluded") or not progress["expected_shortfall"]
                or preparation[:10] > prepared["date"]
                or risk["task_definition_id"] in existing_unallocated):
            continue
        missing = risk.get("estimated_shortfall_minutes", 0)
        if missing:
            result.setdefault("unallocated", []).append({"task_id": risk["task_definition_id"],
                "task_assignment_id": risk["assignment_id"], "title": risk["title"], "minutes": missing,
                "reason": f"Assessment preparation cannot fit before the linked assessment starts at {preparation}. Work after that start does not count as preparation; stored task dates and completion remain unchanged."})
            existing_unallocated.add(risk["task_definition_id"])
            if result.get("status") in {"optimal", "feasible"}:
                result["status"] = "partial"
    advanced = sum(max(0, actual_minutes.get(unit["logical_session_id"], 0)
                           - unit.get("weekly_planned_minutes", unit["remaining_minutes"]))
                   for unit in prepared["tasks"] if unit.get("weekly_opportunity"))
    offered = sum(max(0, unit["remaining_minutes"] - unit.get("weekly_planned_minutes", unit["remaining_minutes"]))
                  for unit in prepared["tasks"] if unit.get("weekly_opportunity"))
    result.setdefault("stats", {}).update(weekly_opportunity_offered_minutes=offered,
                                          weekly_advanced_minutes=advanced,
                                          weekly_forecast_future_reduced_minutes=future_reduced)
    if offered:
        result.setdefault("explanations", []).append(
            f"The daily optimizer advanced {advanced} minutes beyond today's rolling weekly forecast from {offered} useful unreserved opportunity minutes. "
            f"Future session forecasts were reduced by {future_reduced} minutes; saved future plans and completion credit were preserved.")
    if result.get("stats") is not None:
        result["stats"]["unallocated_minutes"] = sum(item["minutes"] for item in result.get("unallocated", []))
    result["explanations"] = result.get("explanations", []) + [
        "Weekly session minimums are soft goals. Importance, urgency and available capacity may produce fewer or more complete sessions.",
        "Split chunks retain one logical session ID; only completed minutes reaching its target count as a completed session.",
        "Existing unskipped chunks reserve their session's work, including past plans. Mark a missed chunk Skipped before replanning those minutes.",
        prepared["forecast"],
    ]
    return result
