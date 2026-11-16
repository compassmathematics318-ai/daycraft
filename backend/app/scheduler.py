"""Deterministic CP-SAT daily scheduling with sequence-dependent walking time.

The circuit is the actual chronological activity order. Travel and recovery gaps
are constraints on its arcs, not a cosmetic pass after optimization. Starts of
new work use a five-minute grid; fixed commitments retain their exact timestamps.
UTC elapsed minutes preserve real duration on DST transition days.
"""
from __future__ import annotations

import math
import os
from copy import deepcopy
from datetime import date as Date, datetime, time, timedelta, timezone
from functools import lru_cache
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model

from .progress import _daily_policies, daily_session_progress
from .meal_planning import meal_requirements, meal_timing, validate_meal_order, validate_required_meals
from .planning_intelligence import assessment_preparation_cutoff, interpret_task_context, workload_profile

Route = Callable[[str | None, str | None], int]
UTC = timezone.utc
WORK_KINDS = {"task", "project"}


def validate_daily_session_limits(blocks, tasks, settings):
    return [f"{item['title']}: daily maximum of {item['maximum_sessions']} work blocks exceeded on {item['date']} ({item['scheduled_sessions']} blocks)."
            for item in daily_session_progress(blocks, tasks, settings)
            if item["maximum_sessions"] is not None and item["scheduled_sessions"] > item["maximum_sessions"]]


def _project_priority_bonus(task: dict) -> int:
    """Project context adds 0..90 per-minute points to every scheduling mode.

    Each 0.5 importance step adds five points: round((importance - 1) * 10).
    This stays below one task-priority step (100, or 160 in Deadline First).
    Dates, difficulty, contributors and descriptions never invent work or hard
    constraints; the task remains the sole source of duration and deadline.
    """
    project = task.get("project") or {}
    return round((max(1, min(10, float(project.get("importance", 1)))) - 1) * 10)


def _task_cutoff(task: dict, tz: ZoneInfo) -> datetime | None:
    """Protect explicit dates and actual linked assessment-preparation cutoffs."""
    keys = ("deadline_at",) if task.get("task_type") not in {None, "academic"} else ("due_at", "assessment_at", "deadline_at")
    if not task.get("hard_deadline", True):
        keys = tuple(key for key in keys if key == "assessment_at")
    values = [task.get(key) for key in keys if task.get(key)]
    if task.get("deadline") and task.get("hard_deadline", True):
        values.append(task["deadline"])
    cutoffs = [_dt(value, tz) for value in values]
    preparation_cutoff = assessment_preparation_cutoff(task, tz)
    if preparation_cutoff is not None:
        cutoffs.append(preparation_cutoff)
    return min(cutoffs, key=lambda value: value.astimezone(UTC), default=None)


def _related_assessment_bonus(task: dict, reference: datetime) -> int:
    """A generic linked assessment supplies 0..60 soft priority points.

    The service joins the current activity and canonical occurrences. Classes
    and commitments supply context only. Passed assessments add no urgency;
    explicit task dates retain their independent urgency and constraints. Only
    explicitly typed preparation uses the separate authoritative cutoff helper.
    """
    activity = task.get("related_activity") or {}
    if activity.get("category") != "assessment":
        return 0
    values = [activity["assessment_start"]] if activity.get("assessment_start") else [
        occurrence["start"] for occurrence in activity.get("occurrences", []) if occurrence.get("start")]
    upcoming = [_dt(value, reference.tzinfo).astimezone(UTC) for value in values]
    upcoming = [value for value in upcoming if value >= reference.astimezone(UTC)]
    if not upcoming:
        return 0
    days = (min(upcoming) - reference.astimezone(UTC)).total_seconds() / 86400
    return max(0, min(60, round(60 * (1 - days / 7))))


def _location_mode(value):
    """Old saved records with a venue retain their required attendance policy."""
    return value.get("location_mode") or ("required" if value.get("location_id") else "unspecified")


def allowed_location_ids(value):
    """Physical venues from server-verified suitability or explicit legacy input.

    Enrichment is rebuilt from saved place evidence before API scheduling and
    validation; it is never a client's assertion of permission. Required venues
    stay singleton. Remote/unknown work has no mandatory destination.
    """
    mode = _location_mode(value)
    if mode not in {"required", "preferred"}:
        return []
    selected = value.get("location_id")
    suitability = value.get("location_suitability")
    if mode == "preferred" and suitability is not None:
        alternatives = [candidate["location_id"] for candidate in suitability.get("candidates", [])
                        if candidate.get("location_id")]
    else:
        alternatives = value.get("alternative_location_ids", []) if mode == "preferred" and value.get("allow_alternative_locations", False) else []
    return list(dict.fromkeys(location for location in [selected, *alternatives] if location))


def _protected_location(block, protected_blocks):
    """Match venue history to server-trusted records despite schema defaults.

    Serializing an old block adds optional descriptive fields, so full raw-dict
    equality is too strict. Identity, attendance, protection and timing must all
    remain unchanged; a client's locked/status flag alone grants no exemption.
    """
    def instant(value):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError, TypeError):
            return value  # The ordinary validator reports malformed timestamps.

    def identity(value):
        return (tuple(value.get(key) for key in ("id", "kind", "task_id", "logical_session_id",
                                                "class_id", "occurrence_id", "location_id", "resolved_location_id")),
                instant(value.get("start")), instant(value.get("end")),
                _location_mode(value), value.get("locked", False), value.get("status", "todo"),
                value.get("allow_alternative_locations", False), tuple(value.get("alternative_location_ids", [])))
    return any(identity(block) == identity(saved)
               and (saved.get("locked") or saved.get("status") in {"completed", "in_progress"}
                    or saved.get("_withdrawn_history") or saved.get("_elapsed_work_history"))
               for saved in protected_blocks or [])


def _recorded_venue(block):
    """Use only with a matching trusted snapshot, never as new venue evidence."""
    return block.get("resolved_location_id") or (
        block.get("location_id") if (block.get("_withdrawn_history") or block.get("_elapsed_work_history"))
        and _location_mode(block) in {"required", "preferred"} else None)


def _dt(value: str, tz: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
        # A nonexistent local time must not be silently moved across a DST jump.
        if parsed.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != parsed.replace(tzinfo=None):
            raise ValueError(f"Nonexistent local time: {value}")
    return parsed.astimezone(tz)


def _at(day: Date, value: str, tz: ZoneInfo) -> datetime:
    return _dt(f"{day.isoformat()}T{value}", tz)


def _minutes(start: datetime, end: datetime) -> int:
    return round((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() / 60)


def _block(title: str, kind: str, start: str, end: str, **extra) -> dict:
    return {"id": str(uuid4()), "title": title, "kind": kind, "start": start,
            "end": end, "location_id": None, "task_id": None, "class_id": None,
            "locked": False, "status": "todo", "rationale": "", "estimated": False, **extra}


def _route(a, b, settings, route_minutes: Route) -> int:
    if a == b or a is None or b is None:
        return 0
    # Distinct known places cannot become a zero-minute teleport, even when an
    # imported/manual route reports zero. Same-place movement remains free.
    total = max(1, math.ceil(float(route_minutes(a, b)))) + int(settings.get("travel_buffer_minutes", 5))
    return math.ceil(total / 5) * 5


def _locations(block, default):
    if block["kind"] == "travel":
        return block.get("origin_id"), block.get("destination_id") or block.get("location_id")
    loc = block.get("resolved_location_id") or (block.get("location_id") if _location_mode(block) in {"required", "preferred"} else None)
    return loc, loc


def _active_classes(day: Date, classes):
    for item in classes:
        if day.isoformat() in item.get("exceptions", []):
            continue
        if item.get("date"):
            active = item["date"] == day.isoformat()
        else:
            active = (day.weekday() in item.get("weekdays", [])
                      and (not item.get("start_date") or item["start_date"] <= day.isoformat())
                      and (not item.get("end_date") or item["end_date"] >= day.isoformat()))
        if active:
            yield item


def validate_blocks(blocks: list[dict], settings: dict, route_minutes: Route,
                    tasks: list[dict] | None = None,
                    protected_blocks: list[dict] | None = None) -> list[str]:
    """Independently check edits and solver output without trusting solver state."""
    tz = ZoneInfo(settings.get("timezone", "America/Toronto"))
    errors, parsed = [], []
    task_map = {t["id"]: t for t in tasks or []}
    for b in blocks:
        policy = _location_mode(b)
        if b.get("kind") == "travel" and (not b.get("origin_id") or not (b.get("destination_id") or b.get("location_id"))):
            errors.append(f"{b['title']}: travel requires known origin and destination locations.")
        if b.get("kind") != "travel" and policy in {"required", "preferred"} and not b.get("location_id"):
            errors.append(f"{b['title']}: physical location policy needs a location.")
        if b.get("kind") != "travel" and not _protected_location(b, protected_blocks):
            source = b if b.get("location_override") else task_map.get(b.get("task_id")) or b
            if source is not b and (policy != _location_mode(source) or b.get("location_id") != source.get("location_id")):
                errors.append(f"{b['title']}: location policy must match its task's configured venue.")
            resolved = b.get("resolved_location_id")
            if _location_mode(source) in {"required", "preferred"} and resolved and resolved not in allowed_location_ids(source):
                errors.append(f"{b['title']}: actual venue is not an explicitly permitted or verified suitable location for this activity.")
        try:
            start, end = _dt(b["start"], tz), _dt(b["end"], tz)
            if end.astimezone(UTC) <= start.astimezone(UTC):
                errors.append(f"{b['title']}: end must follow start.")
                continue
            day = start.date()
            wake, sleep = _at(day, settings.get("wake_time", "07:00"), tz), _at(day, settings.get("sleep_time", "23:00"), tz)
            if settings.get("sleep_time") == "00:00":
                sleep += timedelta(days=1)
            if start.astimezone(UTC) < wake.astimezone(UTC) or end.astimezone(UTC) > sleep.astimezone(UTC):
                errors.append(f"{b['title']}: outside waking hours.")
            if b.get("kind") in WORK_KINDS and b.get("status") not in {"completed", "skipped", "in_progress"}:
                ws, we = _at(day, settings.get("work_start", "08:00"), tz), _at(day, settings.get("work_end", "22:00"), tz)
                if start.astimezone(UTC) < ws.astimezone(UTC) or end.astimezone(UTC) > we.astimezone(UTC):
                    errors.append(f"{b['title']}: outside working hours.")
                task = task_map.get(b.get("task_id"))
                if task:
                    duration = _minutes(start, end)
                    if task.get("splittable", True):
                        if duration < task.get("min_session_minutes", 25) or duration > task.get("max_session_minutes", 90):
                            errors.append(f"{b['title']}: session duration outside task limits.")
                    elif duration != task.get("remaining_minutes", task.get("duration_minutes", 0)):
                        errors.append(f"{b['title']}: unsplittable work must fit in one complete session.")
                    cutoff = _task_cutoff(task, tz)
                    if cutoff and end.astimezone(UTC) > cutoff.astimezone(UTC):
                        preparation_cutoff = assessment_preparation_cutoff(task, tz)
                        if preparation_cutoff and end.astimezone(UTC) > preparation_cutoff.astimezone(UTC):
                            errors.append(f"{b['title']}: assessment preparation must finish before its linked assessment at {preparation_cutoff.isoformat()}.")
                        else:
                            errors.append(f"{b['title']}: hard deadline exceeded.")
                    if task.get("earliest_start") and start.astimezone(UTC) < _dt(task["earliest_start"], tz).astimezone(UTC):
                        errors.append(f"{b['title']}: before earliest start.")
            parsed.append((start.astimezone(UTC), end.astimezone(UTC), b))
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(f"Invalid activity time: {exc}")
    parsed.sort(key=lambda row: (row[0], row[1]))
    for i, (start, end, b) in enumerate(parsed):
        for next_start, _, following in parsed[i + 1:]:
            if next_start >= end:
                break
            errors.append(f"Overlap: {b['title']} and {following['title']}.")
    # Rest and meal blocks can occupy a gap but do not teleport the person.
    travel_nodes = [p for p in parsed if p[2]["kind"] not in {"break"}]
    # Propagate feasible physical positions through the chronological chain.
    # A remote or unknown event may happen at any reachable known position. Its
    # occupied interval cannot absorb a walk; only the preceding free gap can.
    home = settings.get("home_location_id")
    known = {b.get("location_id") for _, _, b in travel_nodes if b.get("location_id")}
    known |= {b.get(key) for _, _, b in travel_nodes for key in ("origin_id", "destination_id", "resolved_location_id") if b.get(key)}
    known |= {location for _, _, b in travel_nodes for location in allowed_location_ids(b)}
    if home and (settings.get("start_at_home") or settings.get("end_at_home")):
        known.add(home)
    candidates = known or {None}
    positions = {home} if home and settings.get("start_at_home") else set(candidates)
    previous_end = None
    for start, end, b in travel_nodes:
        if previous_end is None:
            previous_end = _at(start.astimezone(tz).date(), settings.get("wake_time", "07:00"), tz).astimezone(UTC)
        gap = _minutes(previous_end, start)
        mode = _location_mode(b)
        if b["kind"] == "travel":
            origin, destination = _locations(b, None)
            feasible = {destination} if any(_route(pos, origin, settings, route_minutes) <= gap for pos in positions) else set()
        elif mode in {"remote", "unspecified"}:
            # Repositioning before a flexible activity is real travel, even if
            # that activity has no mandatory venue (for example lunch before a
            # class). Retaining only the predecessor position falsely blocks
            # the entire morning when that lunch directly precedes the class.
            resolved = b.get("resolved_location_id")
            targets = {resolved} if resolved else candidates
            feasible = {target for target in targets
                        if any(_route(pos, target, settings, route_minutes) <= gap for pos in positions)}
        else:
            source = b if b.get("location_override") else task_map.get(b.get("task_id")) or b
            targets = set(allowed_location_ids(source))
            if _protected_location(b, protected_blocks) and _recorded_venue(b):
                targets = {_recorded_venue(b)}
            if b.get("resolved_location_id"):
                targets &= {b["resolved_location_id"]}
            feasible = {target for target in targets if any(_route(pos, target, settings, route_minutes) <= gap for pos in positions)}
        if not feasible:
            errors.append(f"Insufficient travel time before {b['title']}; known physical locations cannot be bypassed by remote or unspecified activities.")
            # Continue from this known destination to expose further conflicts.
            feasible = {b.get("location_id")} if mode in {"required", "preferred"} else set(candidates)
        positions, previous_end = feasible, end
    if travel_nodes and home and settings.get("end_at_home"):
        last = travel_nodes[-1]
        sleep = _at(last[1].astimezone(tz).date(), settings.get("sleep_time", "23:00"), tz)
        if settings.get("sleep_time") == "00:00":
            sleep += timedelta(days=1)
        if not any(_route(pos, home, settings, route_minutes) <= _minutes(last[1], sleep) for pos in positions):
            errors.append(f"Insufficient travel time home after {last[2]['title']}.")
    default = None
    # A walk is a genuine activity; it must itself reserve enough time.
    for start, end, b in parsed:
        if b["kind"] == "travel":
            need = _route(*_locations(b, default), settings, route_minutes)
            if _minutes(start, end) < need:
                errors.append(f"{b['title']}: travel block is too short ({need} min required).")
    # Authorized short chunks can form one focus run. Count actual sustained
    # work, not arbitrary block boundaries. Walking never counts as recovery.
    rest = max(0, int(settings.get("break_minutes", 10)))
    focus_limit = max(5, int(settings.get("focus_minutes", 50)))
    busy = [row for row in parsed if row[2]["kind"] not in {"break", "meal", "travel"}
            and row[2].get("status") != "skipped"]
    accumulated, previous = 0, None
    for start, end, b in busy:
        rested = True
        if previous:
            before_start, before_end, before = previous
            walking = sum(_minutes(max(before_end, s), min(start, e)) for s, e, item in parsed
                          if item["kind"] == "travel" and s < start and e > before_end)
            rested = _minutes(before_end, start) - walking >= rest
            if before["kind"] in WORK_KINDS and accumulated >= focus_limit and not rested:
                errors.append(f"{before['title']}: requires {rest} minutes recovery after sustained focus before the next activity.")
        if b["kind"] in WORK_KINDS:
            duration = _minutes(start, end)
            accumulated = duration + (accumulated if previous and previous[2]["kind"] in WORK_KINDS and not rested else 0)
            if rest and accumulated > max(focus_limit, duration):
                errors.append(f"{b['title']}: sustained focus exceeds {focus_limit} minutes without {rest} minutes recovery.")
        else:
            accumulated = 0
        previous = (start, end, b)
    if tasks is not None:
        allocations: dict[str, list] = {}
        for start, end, b in parsed:
            if b.get("task_id") and b.get("status") not in {"completed", "skipped"}:
                allocations.setdefault(b["task_id"], []).append((start, end, b))
        for tid, sessions in allocations.items():
            task = task_map.get(tid)
            if not task:
                errors.append(f"Unknown task: {tid}.")
                continue
            allocated = sum(_minutes(s, e) for s, e, _ in sessions)
            remaining = task.get("remaining_minutes", task.get("duration_minutes", 0))
            if allocated > remaining:
                errors.append(f"{task['title']}: allocated work exceeds remaining work.")
            if not task.get("splittable", True) and len(sessions) > 1:
                errors.append(f"{task['title']}: cannot split this task.")
            for dep in task.get("dependencies", []):
                predecessor = task_map.get(dep)
                if predecessor and (predecessor.get("status") == "completed" or predecessor.get("remaining_minutes", 0) <= 0):
                    continue
                predecessor_sessions = allocations.get(dep, [])
                if not predecessor or sum(_minutes(s, e) for s, e, _ in predecessor_sessions) < predecessor.get("remaining_minutes", 0):
                    errors.append(f"{task['title']}: prerequisite {dep} is not fully allocated.")
                elif max(e for _, e, _ in predecessor_sessions) > min(s for s, _, _ in sessions):
                    errors.append(f"{task['title']}: prerequisite work must finish first.")
    errors.extend(validate_daily_session_limits(blocks, tasks, settings))
    return list(dict.fromkeys(errors))


def generate_schedule(date: str, settings: dict, classes: list[dict], tasks: list[dict],
                      blocks: list[dict], route_minutes: Route, mode: str = "balanced",
                      now: str | None = None) -> dict:
    day, tz = Date.fromisoformat(date), ZoneInfo(settings.get("timezone", "America/Toronto"))
    route_minutes = lru_cache(maxsize=None)(route_minutes)
    midnight = datetime.combine(day, time(), tzinfo=tz)
    anchor = midnight.astimezone(UTC)
    def offset(value):
        return _minutes(midnight, value)
    def iso(value):
        return (anchor + timedelta(minutes=int(value))).astimezone(tz).isoformat()
    awake_start = offset(_at(day, settings.get("wake_time", "07:00"), tz))
    sleep = _at(day, settings.get("sleep_time", "23:00"), tz)
    if settings.get("sleep_time") == "00:00":
        sleep += timedelta(days=1)
    awake_end = offset(sleep)
    level = settings.get("workload_level", "medium")
    profile = workload_profile(level)
    # Deadline First expands ordinary priority rewards (100 -> 160/step).
    # Normalize the competing workload cost so a strategy change does not
    # accidentally turn every workload into maximum optional inclusion.
    workload_scale = 1.35 if mode == "deadline" else 1.0
    planning_start = max(awake_start, math.ceil(offset(_dt(now, tz)) / 5) * 5) if now else awake_start
    work_start = max(awake_start, offset(_at(day, settings.get("work_start", "08:00"), tz)))
    work_end = min(awake_end, offset(_at(day, settings.get("work_end", "22:00"), tz)))
    if now:
        work_start = max(work_start, math.ceil(offset(_dt(now, tz)) / 5) * 5)
    rest = max(0, int(settings.get("break_minutes", 10)))
    default = None
    home = settings.get("home_location_id")
    start_home = home if settings.get("start_at_home") else None
    end_home = home if settings.get("end_at_home") else None
    fixed = deepcopy(blocks)
    existing_classes = {b.get("class_id") for b in fixed if b.get("class_id")}
    for cls in _active_classes(day, classes):
        if cls["id"] in existing_classes:
            continue
        fixed.append(_block(cls["title"], "class", _at(day, cls["start_time"], tz).isoformat(),
                            _at(day, cls["end_time"], tz).isoformat(), class_id=cls["id"],
                            location_id=cls.get("location_id"), location_mode=_location_mode(cls), room=cls.get("room", ""), locked=True,
                            allow_alternative_locations=cls.get("allow_alternative_locations", False),
                            alternative_location_ids=list(cls.get("alternative_location_ids", [])),
                            **{key: deepcopy(cls[key]) for key in ("location_requirements", "location_suitability") if key in cls},
                            rationale="Fixed class commitment; its time cannot move."))
    meals = meal_requirements(settings, fixed)
    reference = _dt(now, tz) if now else _at(day, settings.get("work_start", "08:00"), tz)
    # Legacy finite tasks use the same evidence-based context rules as weekly
    # logical units. The pure solver enriches copies; user records stay intact.
    contextual_tasks = []
    for task in tasks:
        if task.get("planning_context") is not None:
            contextual_tasks.append(task)
            continue
        context = interpret_task_context(task, reference, fixed)
        contextual_tasks.append({**task, "planning_context": context,
                                 "context_bonus": context.get("context_bonus", 0)})
    tasks = contextual_tasks
    base = {"date": date, "mode": mode, "status": "infeasible", "solver_status": "NOT_RUN",
            "workload_level": level,
            "blocks": fixed, "unallocated": [], "excluded_tasks": [], "conflicts": [], "explanations": [],
            "stats": {"workload_profile": profile}}
    task_map = {t["id"]: t for t in tasks}
    candidates = [t for t in tasks if not t.get("deleted_at") and t.get("status") not in {"completed", "skipped"} and t.get("remaining_minutes", t.get("duration_minutes", 0)) > 0]
    active, excluded_preserved = [], {}
    for task in candidates:
        project = task.get("project") or {}
        if project.get("status") in {"paused", "archived"} and not task.get("schedule_inactive_project", False):
            preserved_minutes = sum(_minutes(_dt(b["start"], tz), _dt(b["end"], tz)) for b in fixed
                                    if b.get("task_id") == task["id"] and b.get("status") not in {"completed", "skipped"})
            excluded_preserved[task["id"]] = preserved_minutes
            base["excluded_tasks"].append({
                "task_id": task["id"], "title": task["title"], "project_id": project.get("id") or task.get("project_id"),
                "minutes": max(0, task.get("remaining_minutes", task.get("duration_minutes", 0)) - preserved_minutes),
                "reason": f"Project is {project['status']}; automatic scheduling is excluded unless explicitly requested. Existing locked or started sessions are preserved.",
            })
        else:
            active.append(task)
    project_explanations = [
        "Linked tasks receive 0–90 project-importance points per minute, below one task-priority step; task deadlines and all hard constraints still apply.",
        "Project dates and difficulty provide context only; durations come from tasks. Project descriptions and goals are stored context and are not interpreted by an AI model.",
    ] if any(t.get("project") for t in candidates) else []
    if base["excluded_tasks"]:
        project_explanations.append(f"{len(base['excluded_tasks'])} task(s) from paused or archived projects excluded from automatic scheduling; preserved commitments remain.")
    base["explanations"] = project_explanations
    if any(_location_mode(item) == "unspecified" for item in active + [b for b in fixed if b["kind"] not in {"meal", "break", "travel"}]):
        base["explanations"] = [*project_explanations, "Some activities have unspecified locations: attendance locations are unknown, so their travel coverage cannot be verified."]
    # Fixed gaps are checked separately by the model so the solver may insert
    # intermediate locations if a manual route matrix violates triangle inequality.
    fixed_errors = [e for e in validate_blocks(fixed, settings, route_minutes, protected_blocks=blocks) if not e.startswith("Insufficient travel time")]
    fixed_errors.extend(validate_daily_session_limits(fixed, tasks, settings))
    fixed_errors.extend(validate_meal_order(fixed, meals))
    if awake_end <= awake_start or work_end < work_start and not now:
        fixed_errors.append("Waking and working hours must be ordered within the selected day.")
    def remaining(task):
        return int(task.get("remaining_minutes", task.get("duration_minutes", 0)))
    def failure(reason, solver_status="NOT_RUN", status="infeasible"):
        base.update(status=status, solver_status=solver_status)
        base["conflicts"] = reason
        base["daily_progress"] = daily_session_progress(fixed, tasks, settings)
        base["unallocated"] = [{"task_id": t["id"], "title": t["title"], "minutes": min(remaining(t), t.get("weekly_planned_minutes", remaining(t))) if t.get("weekly_opportunity") else remaining(t),
                                "reason": "Resolve fixed conflicts or extend available hours." if status == "infeasible" else "Solver time limit reached before a feasible solution; try a longer limit."} for t in active
                               if not t.get("weekly_opportunity") or t.get("weekly_planned_minutes", 0) > 0]
        base["blocks"].sort(key=lambda b: _dt(b["start"], tz).astimezone(UTC))
        return base
    if fixed_errors:
        return failure(fixed_errors)
    model = cp_model.CpModel()
    nodes = []
    intervals = []
    for b in fixed:
        start, end = offset(_dt(b["start"], tz)), offset(_dt(b["end"], tz))
        iv = model.new_interval_var(start, end - start, end, f"fixed_{len(nodes)}")
        intervals.append(iv)
        nodes.append({"s": start, "e": end, "p": model.new_constant(1), "b": b, "task": None,
                      "rest": 0, "fixed": True, "duration": end - start,
                      "minimum_end": end, "maximum_start": start})
    allocations, full, task_nodes, fixed_alloc = {}, {}, {}, dict(excluded_preserved)
    terms, reasons = [], {}
    meal_nodes = []
    for requirement in meals:
        meal = requirement["definition"]
        if requirement["preserved"]:
            preserved_node = next(node for node in nodes if node["b"]["id"] == requirement["preserved"]["id"])
            preserved_node["configured_meal"] = True
            meal_nodes.append(preserved_node)
            continue
        index, duration = requirement["index"], int(meal["duration_minutes"])
        preferred, earliest, latest = meal_timing(meal, index, len(meals), awake_start, awake_end)
        if meal.get("time"):
            preferred = offset(_at(day, meal["time"], tz))
        earliest = max(planning_start, earliest)
        if earliest + duration > latest:
            return failure([f"Required meal {meal['name']} ({duration} minutes) has no sensible remaining awake window. Confirm an already eaten meal, adjust its definition, or change the day's commitments."])
        g = model.new_int_var(0, max(0, awake_end // 5), f"meal_grid_{index}")
        s = model.new_int_var(0, max(0, awake_end), f"meal_start_{index}")
        e = model.new_int_var(0, max(0, awake_end), f"meal_end_{index}")
        model.add(s == g * 5)
        model.add(s >= earliest)
        model.add(e <= latest)
        intervals.append(model.new_interval_var(s, duration, e, f"meal_interval_{index}"))
        deviation = model.new_int_var(0, max(0, awake_end), f"meal_timing_deviation_{index}")
        model.add_abs_equality(deviation, s - preferred)
        terms.append(-deviation * 20000)
        b = _block(meal["name"], "meal", "", "", locked=False,
                   location_id=meal.get("location_id"),
                   location_mode="required" if meal.get("location_id") else "unspecified",
                   **({"meal_id": meal["id"]} if meal.get("id") else {}),
                   rationale="Essential flexible meal; the optimizer chooses a feasible time around commitments and travel.")
        node = {"s": s, "e": e, "p": model.new_constant(1), "b": b, "task": None,
                "rest": 0, "fixed": False, "meal": meal, "duration": duration,
                "grid": g, "preferred": preferred, "earliest": earliest, "latest": latest,
                "minimum_end": earliest + duration, "maximum_start": latest - duration}
        nodes.append(node)
        meal_nodes.append(node)
    # Configured array order is mandatory for every enabled meal, including the
    # fixed historical nodes. Work rewards and clock preferences cannot invert it.
    for left, right in zip(meal_nodes, meal_nodes[1:]):
        model.add(left["e"] <= right["s"])
    for t in active:
        tid = t["id"]
        locked_minutes = sum(_minutes(_dt(b["start"], tz), _dt(b["end"], tz)) for b in fixed
                             if b.get("task_id") == tid and b.get("status") not in {"completed", "skipped"})
        fixed_alloc[tid] = locked_minutes
        needed = max(0, remaining(t) - locked_minutes)
        exact = bool(t.get("exact_minutes"))
        grid = 1 if exact else 5
        minimum = max(grid, math.ceil(t.get("min_session_minutes", 25) / grid) * grid)
        maximum = math.floor(t.get("max_session_minutes", 90) / grid) * grid
        if not t.get("splittable", True):
            minimum = maximum = needed
        slots = min(remaining(t) // max(grid, minimum), max(0, (work_end - work_start) // max(grid, minimum))) if t.get("splittable", True) else int(needed > 0 and needed <= work_end - work_start)
        # A bounded day has at most this many useful sessions. The model never
        # allocates more sessions than the available waking minutes can contain.
        count = min(slots, needed // max(grid, minimum)) if needed >= minimum and minimum <= maximum else 0
        durations, presences, own_nodes = [], [], []
        deadline_end = work_end
        cutoff = _task_cutoff(t, tz)
        preparation_cutoff = assessment_preparation_cutoff(t, tz)
        if cutoff:
            deadline_end = min(deadline_end, offset(cutoff))
        earliest_start = max(work_start, offset(_dt(t["earliest_start"], tz))) if t.get("earliest_start") else work_start
        preference_start = offset(_at(day, t["preferred_start"], tz)) if t.get("preferred_start") else None
        preference_end = offset(_at(day, t["preferred_end"], tz)) if t.get("preferred_end") else None
        priority = int(t.get("priority", 3))
        proximity = 0
        if t.get("deadline"):
            hours = max(0, (offset(_dt(t["deadline"], tz)) - awake_start) / 60)
            proximity = max(0, 100 - int(hours))
        value = 200 + priority * (160 if mode == "deadline" else 100) + proximity * (10 if mode == "deadline" else 4)
        value += _project_priority_bonus(t)
        related_bonus = _related_assessment_bonus(t, _at(day, settings.get("work_start", "08:00"), tz))
        value += related_bonus
        value = int(t.get("weekly_value", value))
        # Deadline protection is invariant across workload profiles. This is a
        # reward for reducing explicit risk, never permission to exceed cutoff.
        risk = (t.get("planning_context") or {}).get("deadline_risk", "none")
        hours_to_cutoff = (offset(cutoff) - planning_start) / 60 if cutoff else None
        urgent = risk in {"at_risk", "critical", "overdue"} or hours_to_cutoff is not None and hours_to_cutoff <= 48
        if urgent:
            value += 2000
        value += max(0, min(60, int(t.get("context_bonus", 0))))
        for index in range(count):
            name = f"{tid}_{index}"
            p = model.new_bool_var(f"present_{name}")
            start_grid = model.new_int_var(0, max(0, awake_end // 5), f"grid_{name}")
            s = model.new_int_var(0, max(0, awake_end), f"start_{name}")
            model.add(s == start_grid * 5)
            d_grid = model.new_int_var(0, max(0, maximum // grid), f"duration_grid_{name}")
            d = model.new_int_var(0, max(0, maximum), f"duration_{name}")
            model.add(d == d_grid * grid)
            model.add(d >= minimum).only_enforce_if(p)
            model.add(d == 0).only_enforce_if(p.Not())
            e = model.new_int_var(0, max(0, awake_end), f"end_{name}")
            iv = model.new_optional_interval_var(s, d, e, p, f"interval_{name}")
            model.add(s >= earliest_start).only_enforce_if(p)
            model.add(e <= deadline_end).only_enforce_if(p)
            if presences:
                model.add(p <= presences[-1])
                model.add(s >= own_nodes[-1]["e"]).only_enforce_if(p)
            project = t.get("project") or {}
            b = _block(t["title"], "project" if project or t.get("kind") == "project" else "task", "", "",
                       location_id=t.get("location_id"), location_mode=_location_mode(t), task_id=tid,
                       allow_alternative_locations=t.get("allow_alternative_locations", False),
                       alternative_location_ids=list(t.get("alternative_location_ids", [])),
                       **{key: deepcopy(t[key]) for key in ("location_requirements", "location_suitability") if key in t},
                       **({"project_id": project.get("id") or t.get("project_id")} if project else {}),
                       **{key: t[key] for key in ("task_definition_id", "task_assignment_id", "logical_session_id", "room") if t.get(key)},
                       rationale=f"Priority {priority}/5" + ("; deadline proximity increases its value" if t.get("deadline") else "")
                       + (f"; project importance {project['importance']:g}/10 contributes {_project_priority_bonus(t)} priority points per minute" if project.get("importance") is not None else "")
                       + (f"; related {t['related_activity'].get('category', 'activity')}: {t['related_activity'].get('title', '')}" if t.get("related_activity") else "")
                       + (f"; linked assessment proximity contributes {related_bonus} soft priority points per minute" if related_bonus else "")
                       + (f"; preparation must finish before the linked assessment at {preparation_cutoff.isoformat()}" if preparation_cutoff else "")
                       + ("; explicit deadline risk receives protected priority" if urgent else "")
                       + f"; {level.replace('_', ' ')} workload balances useful progress with recovery"
                       + ("; longer sessions favored by Deep Work mode." if mode == "deep" else "; scheduled within available hours."))
            node = {"s": s, "e": e, "p": p, "b": b, "task": t, "rest": 0, "fixed": False,
                    "d": d, "grid": start_grid, "d_grid": d_grid, "value": value,
                    "minimum": minimum, "maximum": maximum, "deadline": deadline_end}
            node.update(minimum_end=earliest_start + minimum, maximum_start=deadline_end - minimum, sequence=index)
            node["duration_grid"] = grid
            nodes.append(node)
            own_nodes.append(node)
            intervals.append(iv)
            durations.append(d)
            presences.append(p)
            terms.extend([d * value * 1000, -p * (60000 if mode == "deep" else 15000), -s])
            # Weekly marginal values already include the chosen strategy and
            # bypass the legacy priority formula. Applying its normalization
            # again would suppress otherwise worthwhile weekly work.
            opportunity_scale = 1.0 if "weekly_value" in t else workload_scale
            terms.append(-d * round(profile["opportunity_cost"] * opportunity_scale) * 1000)
            late_day = model.new_int_var(0, max(0, awake_end), f"late_day_{name}")
            late_start = work_start + round(max(0, work_end - work_start) * profile["late_start_ratio"])
            model.add(late_day >= e - late_start).only_enforce_if(p)
            terms.append(-late_day * round(profile["late_penalty_per_hour"] * 1000 / 60))
            desired_focus = round(int(settings.get("focus_minutes", 50)) * profile["focus_multiplier"])
            focus_preference = (t.get("planning_context") or {}).get("focus_preference", "neutral")
            desired_focus = max(5, desired_focus + {"longer": 10, "shorter": -10, "recovery": -10}.get(focus_preference, 0))
            focus_deviation = model.new_int_var(0, max(maximum, desired_focus), f"focus_deviation_{name}")
            model.add_abs_equality(focus_deviation, d - desired_focus * p)
            terms.append(-focus_deviation * (100 if mode == "deep" else 300))
            # Inactive sessions have zero start, avoiding arbitrary unused values.
            model.add(s == 0).only_enforce_if(p.Not())
            if preference_start is not None:
                early = model.new_int_var(0, max(0, awake_end), f"early_{name}")
                model.add(early >= preference_start - s).only_enforce_if(p)
                terms.append(-early * 30000)
            if preference_end is not None:
                late = model.new_int_var(0, max(0, awake_end), f"late_{name}")
                model.add(late >= e - preference_end).only_enforce_if(p)
                terms.append(-late * 30000)
            task_preference = t.get("preferred_time_of_day", "any")
            energy_window = {"morning": ("08:00", "12:00"), "afternoon": ("12:00", "17:00"),
                             "evening": ("17:00", "22:00")}.get(task_preference if task_preference != "any" else settings.get("energy_preference", "any"))
            explicit_energy_window = energy_window is not None
            difficulty = float((t.get("planning_context") or {}).get("cognitive_demand", t.get("difficulty", 0)))
            if not energy_window and difficulty >= 7:
                energy_window = ("08:00", "12:00")
            if energy_window:
                energy_start, energy_end = (offset(_at(day, clock, tz)) for clock in energy_window)
                if energy_window[0] == "17:00":
                    energy_end = work_end
                early_energy = model.new_int_var(0, max(0, awake_end), f"energy_early_{name}")
                late_energy = model.new_int_var(0, max(0, awake_end), f"energy_late_{name}")
                model.add(early_energy >= energy_start - s).only_enforce_if(p)
                model.add(late_energy >= e - energy_end).only_enforce_if(p)
                # Explicit preferences retain precedence over compactness;
                # inferred cognitive pacing remains a much lighter suggestion.
                placement_weight = (30 + round(difficulty * 5)) * (1000 if explicit_energy_window else 1)
                terms.extend([-early_energy * placement_weight, -late_energy * placement_weight])
        allocated = model.new_int_var(0, max(remaining(t), locked_minutes), f"allocated_{tid}")
        model.add(allocated == sum(durations) + locked_minutes)
        model.add(allocated <= remaining(t))
        done = model.new_bool_var(f"fully_allocated_{tid}")
        model.add(allocated == remaining(t)).only_enforce_if(done)
        model.add(allocated < remaining(t)).only_enforce_if(done.Not())
        terms.append(done * int(t.get("weekly_full_bonus", 20000)))
        allocations[tid], full[tid], task_nodes[tid] = allocated, done, own_nodes
        if needed % grid:
            reasons[tid] = "Work is scheduled on a five-minute grid; adjust the remaining duration to a multiple of five."
        elif needed < minimum and needed:
            reasons[tid] = "Remaining work is shorter than the minimum session; reduce the minimum session length."
        if preparation_cutoff:
            reasons[tid] = (f"Preparation remains unmet before the linked assessment at {preparation_cutoff.isoformat()}. "
                            "Work after that assessment cannot satisfy its preparation; review remaining effort, earlier availability, or the linked assessment.")
    # A daily session is one actual interval, including every split chunk and
    # all fixed historical intervals. Aggregate across logical-session units.
    fixed_counts = {item["task_definition_id"]: item["scheduled_sessions"]
                    for item in daily_session_progress(fixed, tasks, settings) if item["date"] == date}
    for definition_id, policy in _daily_policies(tasks).items():
        presences = [node["p"] for node in nodes if node["task"] is not None
                     and (node["task"].get("task_definition_id") or node["task"]["id"]) == definition_id]
        fixed_count = fixed_counts.get(definition_id, 0)
        maximum_count = policy.get("max_sessions_per_day")
        if maximum_count is not None:
            model.add(sum(presences) + fixed_count <= maximum_count)
        minimum_count = policy.get("min_sessions_per_day", 1)
        if minimum_count > 1 and presences:
            # Bound both the variable domain and total preference independently
            # of arbitrarily large user targets. This favors useful splitting,
            # but cannot buy even five minutes of substantially more urgent work.
            bounded_minimum = min(minimum_count, fixed_count + len(presences))
            active_day = model.new_bool_var(f"daily_active_{definition_id}")
            model.add(sum(presences) + fixed_count >= 1).only_enforce_if(active_day)
            model.add(sum(presences) + fixed_count == 0).only_enforce_if(active_day.Not())
            shortfall = model.new_int_var(0, bounded_minimum, f"daily_shortfall_{definition_id}")
            model.add(shortfall >= bounded_minimum - fixed_count - sum(presences)).only_enforce_if(active_day)
            model.add(shortfall == 0).only_enforce_if(active_day.Not())
            terms.append(-shortfall * max(1, 2500000 // bounded_minimum))
    model.add_no_overlap(intervals)
    # This is an opportunity cost, not a quota: sufficiently valuable or urgent
    # work can exceed the preferred utilization. History contributes exertion
    # without becoming confirmed completion or duplicated work credit.
    fixed_nonwork = sum(max(0, min(work_end, node["e"]) - max(work_start, node["s"]))
                        for node in nodes if node.get("fixed") and node["b"]["kind"] not in WORK_KINDS)
    meal_reserve = sum(node["duration"] for node in nodes if node.get("meal"))
    productive_capacity = max(0, work_end - work_start - fixed_nonwork - meal_reserve)
    preferred_minutes = min(productive_capacity, max(120, round(productive_capacity * profile["preferred_utilization_ratio"])))
    work_durations = [node.get("d", node.get("duration", 0)) for node in nodes
                      if node["b"]["kind"] in WORK_KINDS and node["b"].get("status") != "skipped"]
    total_work = sum(work_durations)
    fatigue = model.new_int_var(0, max(0, awake_end * 2), "workload_fatigue_minutes")
    model.add(fatigue >= total_work - preferred_minutes)
    terms.append(-fatigue * round(profile["fatigue_penalty"] * workload_scale) * 1000)
    # Focus state follows the actual circuit. Adjacent short chunks can share
    # a run; a real rest gap resets it. A longer explicitly allowed session is
    # legal in isolation, then receives recovery before the next activity.
    focus_limit = max(5, int(settings.get("focus_minutes", 50)))
    for index, node in enumerate(nodes):
        node["work"] = node["b"]["kind"] in WORK_KINDS and node["b"].get("status") != "skipped"
        if not node["work"]:
            continue
        duration = node.get("d", node.get("duration", 0))
        focus = model.new_int_var(0, max(0, awake_end), f"focus_run_{index}")
        node["focus"] = focus
        if rest:
            limit = model.new_int_var(focus_limit, max(focus_limit, awake_end), f"focus_limit_{index}")
            model.add_max_equality(limit, [focus_limit, duration])
            model.add(focus <= limit)
            sustained = model.new_bool_var(f"sustained_{index}")
            model.add(focus >= focus_limit).only_enforce_if(sustained)
            model.add(focus < focus_limit).only_enforce_if(sustained.Not())
            node["rest"] = rest * sustained
            node["sustained"], node["focus_bound"] = sustained, limit
        else:
            node["rest"] = 0
    # Dependencies require full prerequisite allocation, then chronological finish.
    for t in active:
        for dep in t.get("dependencies", []):
            predecessor = task_map.get(dep)
            completed = predecessor and (predecessor.get("status") == "completed" or remaining(predecessor) <= 0)
            if completed:
                continue
            for node in task_nodes.get(t["id"], []):
                if predecessor and excluded_preserved.get(dep, 0) >= remaining(predecessor):
                    # Pausing a project does not invalidate work already locked
                    # into this day. Fully preserved prerequisite work can still
                    # release dependents, strictly after its fixed sessions end.
                    for before in nodes:
                        if before["task"] is None and before["b"].get("task_id") == dep and before["b"].get("status") not in {"completed", "skipped"}:
                            model.add(node["s"] >= before["e"]).only_enforce_if(node["p"])
                    continue
                if dep not in full:
                    model.add(node["p"] == 0)
                    reasons[t["id"]] = "A prerequisite is missing, skipped, or unavailable."
                    continue
                model.add(node["p"] <= full[dep])
                for before in task_nodes.get(dep, []) + [n for n in nodes if n["task"] is None and n["b"].get("task_id") == dep and n["b"].get("status") not in {"completed", "skipped"}]:
                    model.add(node["s"] >= before["e"]).only_enforce_if([node["p"], before["p"]])
    # Physical positions are part of the sequence-dependent circuit. Flexible
    # activities have no mandatory destination, but may relocate only through a
    # real travel arc in free time before their interval. Preferred venues may
    # yield only within their verified suitability domain.
    places = sorted({location for n in nodes for location in _locations(n["b"], None) if location}
                    | {location for n in nodes for location in allowed_location_ids(n["b"])}
                    | {location for location in (start_home, end_home) if location}) or [None]
    place_index = {location: index for index, location in enumerate(places)}
    route_table = [_route(a, b, settings, route_minutes) for a in places for b in places]
    max_travel = max(route_table)
    for index, node in enumerate(nodes):
        block = node["b"]
        policy = _location_mode(block)
        if block["kind"] == "travel":
            origin, destination = _locations(block, None)
            node["origin"] = model.new_constant(place_index[origin])
            node["destination"] = model.new_constant(place_index[destination])
        elif _protected_location(block, blocks) and _recorded_venue(block):
            node["origin"] = node["destination"] = model.new_constant(place_index[_recorded_venue(block)])
        elif policy in {"required", "preferred"}:
            permitted = [place_index[location] for location in allowed_location_ids(block)]
            position = model.new_int_var_from_domain(cp_model.Domain.from_values(permitted), f"position_{index}")
            node["origin"] = node["destination"] = position
            if policy == "preferred" and len(permitted) > 1:
                chosen = model.new_bool_var(f"preferred_venue_{index}")
                model.add(position == place_index[block["location_id"]]).only_enforce_if(chosen)
                model.add(position != place_index[block["location_id"]]).only_enforce_if(chosen.Not())
                # Useful work can outweigh a preference only among suitable venues.
                terms.append(-5000 * (1 - chosen))
        else:
            position = model.new_int_var(0, len(places) - 1, f"position_{index}")
            node["origin"] = node["destination"] = position

    def travel_between(origin, destination, name):
        if len(places) == 1:
            return model.new_constant(0)
        pair = model.new_int_var(0, len(route_table) - 1, f"pair_{name}")
        travel = model.new_int_var(0, max_travel, f"travel_{name}")
        model.add(pair == origin * len(places) + destination)
        model.add_element(pair, route_table, travel)
        return travel

    # A circuit with a depot and optional self loops describes one exact route.
    # There can be no disconnected subtours. Time strictly advances on real arcs.
    arcs, arc_metadata, recovery_decisions = [], [], []
    discretionary_idle = []
    empty = model.new_bool_var("empty_day")
    arcs.append((0, 0, empty))
    for n in nodes:
        model.add(n["p"] == 0).only_enforce_if(empty)
    if nodes:
        model.add(sum(n["p"] for n in nodes) >= 1).only_enforce_if(empty.Not())
    for i, left in enumerate(nodes, 1):
        p = left["p"]
        arcs.append((i, i, p.Not()))
        begin = model.new_bool_var(f"first_{i}")
        end = model.new_bool_var(f"last_{i}")
        arcs.extend([(0, i, begin), (i, 0, end)])
        incoming = travel_between(model.new_constant(place_index[start_home]), left["origin"], f"first_{i}") if start_home else model.new_constant(0)
        outgoing = travel_between(left["destination"], model.new_constant(place_index[end_home]), f"last_{i}") if end_home else model.new_constant(0)
        model.add(left["s"] >= awake_start + incoming).only_enforce_if(begin)
        if left["work"]:
            model.add(left["focus"] == left.get("d", left.get("duration", 0))).only_enforce_if(begin)
        # Recovery protects the next activity, including a walk home. Ending
        # the day at the current venue creates no artificial recovery block.
        terminal_recovery = 0
        if end_home and left["work"] and rest:
            going_home = model.new_bool_var(f"return_home_{i}")
            model.add(outgoing > 0).only_enforce_if(going_home)
            model.add(outgoing == 0).only_enforce_if(going_home.Not())
            terminal_recovery = model.new_int_var(0, rest, f"return_recovery_{i}")
            model.add(terminal_recovery == left["rest"]).only_enforce_if(going_home)
            model.add(terminal_recovery == 0).only_enforce_if(going_home.Not())
        model.add(left["e"] + terminal_recovery + outgoing <= awake_end).only_enforce_if(end)
        arc_metadata.extend([(begin, None, left, incoming, 0), (end, left, None, outgoing, terminal_recovery)])
        for j, right in enumerate(nodes, 1):
            if i == j:
                continue
            if left["minimum_end"] > right["maximum_start"]:
                continue
            if left["task"] and right["task"] and left["task"]["id"] == right["task"]["id"] and left["sequence"] > right["sequence"]:
                continue
            edge = model.new_bool_var(f"arc_{i}_{j}")
            arcs.append((i, j, edge))
            travel = travel_between(left["destination"], right["origin"], f"{i}_{j}")
            recovery = left["rest"]
            if right["work"]:
                duration = right.get("d", right.get("duration", 0))
                if left["work"] and rest:
                    reset = model.new_bool_var(f"focus_reset_{i}_{j}")
                    recovery_decisions.append((reset, left, right))
                    model.add(right["focus"] == duration).only_enforce_if([edge, reset])
                    model.add(right["focus"] == left["focus"] + duration).only_enforce_if([edge, reset.Not()])
                    recovery = rest * reset
                else:
                    model.add(right["focus"] == duration).only_enforce_if(edge)
                    recovery = 0
            elif right["b"]["kind"] in {"meal", "break"}:
                duration = right["duration"]
                if duration >= rest and left["work"] and rest:
                    walking = model.new_bool_var(f"walking_{i}_{j}")
                    model.add(travel > 0).only_enforce_if(walking)
                    model.add(travel == 0).only_enforce_if(walking.Not())
                    recovered = model.new_int_var(0, rest, f"meal_recovery_{i}_{j}")
                    model.add(recovered == left["rest"]).only_enforce_if(walking)
                    model.add(recovered == 0).only_enforce_if(walking.Not())
                    recovery = recovered
            model.add(right["s"] >= left["e"] + recovery + travel).only_enforce_if(edge)
            if left["work"] and right["work"]:
                left_task = left["task"] or task_map.get(left["b"].get("task_id"), {})
                right_task = right["task"] or task_map.get(right["b"].get("task_id"), {})
                difficulty = min(float((left_task.get("planning_context") or {}).get("cognitive_demand", left_task.get("difficulty", 0))),
                                 float((right_task.get("planning_context") or {}).get("cognitive_demand", right_task.get("difficulty", 0))))
                if difficulty >= 7:
                    comfortable = model.new_bool_var(f"demanding_recovery_{i}_{j}")
                    model.add(right["s"] >= left["e"] + travel + max(rest, 15)).only_enforce_if([edge, comfortable])
                    terms.append(-edge * round(difficulty * 20000 * profile["recovery_multiplier"]))
                    terms.append(comfortable * round(difficulty * 20000 * profile["recovery_multiplier"]))
                    model.add(comfortable <= edge)
                    visible_recovery = model.new_int_var(0, max(rest, 15), f"visible_recovery_{i}_{j}")
                    model.add_max_equality(visible_recovery, [recovery, max(rest, 15) * comfortable])
                    recovery = visible_recovery
            elif right["work"] and left.get("duration", 0) >= 120:
                context = (right["task"] or {}).get("planning_context") or {}
                if context.get("focus_preference") == "recovery":
                    comfortable = model.new_bool_var(f"commitment_recovery_{i}_{j}")
                    model.add(right["s"] >= left["e"] + travel + max(rest, 15)).only_enforce_if([edge, comfortable])
                    penalty = round(200000 * profile["recovery_multiplier"])
                    terms.extend([-edge * penalty, comfortable * penalty])
                    model.add(comfortable <= edge)
                    recovery = max(rest, 15) * comfortable
            # Cost only selected arcs, rather than every potential transition.
            cost = model.new_int_var(0, max_travel, f"travel_cost_{i}_{j}")
            model.add(cost == travel).only_enforce_if(edge)
            model.add(cost == 0).only_enforce_if(edge.Not())
            terms.append(-cost * 10)
            # Only direct optional-work transitions carry an idle cost. A
            # distant fixed anchor must not attract work late into the day.
            if left["task"] and right["task"]:
                idle = model.new_int_var(0, max(0, awake_end), f"work_idle_{i}_{j}")
                model.add(idle == right["s"] - left["e"] - travel - recovery).only_enforce_if(edge)
                model.add(idle == 0).only_enforce_if(edge.Not())
                discretionary_idle.append(idle)
                terms.append(-idle * round(profile["idle_penalty_per_minute"] * 1000))
            arc_metadata.append((edge, left, right, travel, recovery))
    model.add_circuit(arcs)
    optional_work = [node for node in nodes if node["task"]]
    work_extent, completion_extent = 0, 0
    forced_extent_occupancy, forced_completion_occupancy = [], []
    if optional_work:
        clip_lower = min([0] + [node["s"] for node in nodes if node.get("fixed")])
        clip_upper = max([awake_end] + [node["e"] for node in nodes if node.get("fixed")])
        any_work = model.new_bool_var("any_optional_work")
        model.add_max_equality(any_work, [node["p"] for node in optional_work])
        starts = []
        for index, node in enumerate(optional_work):
            start = model.new_int_var(0, awake_end, f"present_work_start_{index}")
            model.add(start == node["s"]).only_enforce_if(node["p"])
            model.add(start == awake_end).only_enforce_if(node["p"].Not())
            starts.append(start)
        first = model.new_int_var(0, awake_end, "first_optional_work")
        last = model.new_int_var(0, awake_end, "last_optional_work")
        model.add_min_equality(first, starts)
        # Absent sessions have zero duration and start, hence zero end.
        model.add_max_equality(last, [node["e"] for node in optional_work])
        for index, node in enumerate(nodes):
            if node["task"]:
                continue
            clipped_end = model.new_int_var(clip_lower, clip_upper, f"anchor_end_{index}")
            model.add_min_equality(clipped_end, [node["e"], last])
            for label, lower, bucket in (("span", first, forced_extent_occupancy),
                                          ("completion", work_start, forced_completion_occupancy)):
                clipped_start = model.new_int_var(clip_lower, clip_upper, f"anchor_start_{label}_{index}")
                model.add_max_equality(clipped_start, [node["s"], lower])
                overlap = model.new_int_var(0, awake_end, f"anchor_overlap_{label}_{index}")
                model.add_max_equality(overlap, [0, clipped_end - clipped_start])
                bucket.append(overlap)
        work_extent = model.new_int_var(0, awake_end, "optional_work_extent")
        completion_extent = model.new_int_var(0, awake_end, "optional_completion_extent")
        model.add(work_extent == last - first - sum(forced_extent_occupancy)).only_enforce_if(any_work)
        model.add(work_extent == 0).only_enforce_if(any_work.Not())
        model.add(completion_extent == last - work_start - sum(forced_completion_occupancy)).only_enforce_if(any_work)
        model.add(completion_extent == 0).only_enforce_if(any_work.Not())
        terms.extend([-work_extent * round(profile["compactness_penalty_per_minute"] * 1000),
                      -completion_extent * round(profile["completion_penalty_per_minute"] * 1000)])
    model.maximize(sum(terms))
    # Seed an actual feasible-looking route rather than spending the entire time
    # limit discovering optional-node circuit topology. These are hints only:
    # CP-SAT must prove every hard constraint before returning any incumbent.
    # An infeasible hint is discarded by the solver, never returned directly.
    hint_times = {id(n): (n["s"], n["e"]) for n in nodes if n.get("fixed")}
    hint_order = sorted([n for n in nodes if n.get("fixed")], key=lambda n: n["s"])
    for meal_index, meal_node in enumerate(meal_nodes):
        if not meal_node.get("meal"):
            continue
        options = []
        ordered_start = max([awake_start] + [hint_times[id(node)][1] for node in meal_nodes[:meal_index] if id(node) in hint_times])
        ordered_end = min([awake_end] + [hint_times[id(node)][0] for node in meal_nodes[meal_index + 1:] if id(node) in hint_times])
        for position in range(len(hint_order) + 1):
            left = hint_order[position - 1] if position else None
            right = hint_order[position] if position < len(hint_order) else None
            earliest = max(meal_node["earliest"], ordered_start, hint_times[id(left)][1] + (rest if left["work"] else 0) if left else awake_start)
            latest = min(meal_node["latest"], ordered_end, hint_times[id(right)][0] if right else awake_end) - meal_node["duration"]
            start = math.ceil(max(earliest, min(latest, meal_node["preferred"])) / 5) * 5
            if start <= latest:
                options.append((abs(start - meal_node["preferred"]), start, position))
        _, start, position = min(options) if options else (0, math.ceil(meal_node["earliest"] / 5) * 5, len(hint_order))
        hint_times[id(meal_node)] = (start, start + meal_node["duration"])
        hint_order.insert(position, meal_node)
        hint_order.sort(key=lambda node: hint_times[id(node)][0])
        model.add_hint(meal_node["s"], start)
        model.add_hint(meal_node["e"], start + meal_node["duration"])
        model.add_hint(meal_node["grid"], start // 5)
    hint_alloc = dict(fixed_alloc)
    hint_daily_counts = dict(fixed_counts)
    hinted_work_minutes = sum(node["duration"] for node in nodes if node.get("fixed") and node["work"])
    pending = sorted(active, key=lambda t: (-max((n["value"] for n in task_nodes[t["id"]]), default=0), t["id"]))
    for _ in range(len(pending) + 1):
        made_progress, deferred = False, []
        for task in pending:
            dependencies = task.get("dependencies", [])
            if any(dep not in task_map or (task_map[dep].get("status") != "completed" and hint_alloc.get(dep, 0) < remaining(task_map[dep])) for dep in dependencies):
                deferred.append(task)
                continue
            tid = task["id"]
            definition_id = task.get("task_definition_id") or tid
            after = max([work_start] + [hint_times[id(n)][1] for n in hint_order if n["b"].get("task_id") in dependencies])
            for candidate in task_nodes[tid]:
                maximum_count = task.get("max_sessions_per_day")
                if maximum_count is not None and hint_daily_counts.get(definition_id, 0) >= maximum_count:
                    break
                need = remaining(task) - hint_alloc.get(tid, 0)
                opportunity_scale = 1.0 if "weekly_value" in task else workload_scale
                marginal_value = candidate["value"] - profile["opportunity_cost"] * opportunity_scale
                if marginal_value <= 0:
                    break
                # Seed only useful marginal work. These are search hints: the
                # full objective may still favor crossing the soft preference.
                if marginal_value <= profile["fatigue_penalty"] * workload_scale:
                    need = min(need, max(0, preferred_minutes - hinted_work_minutes))
                if need < candidate["minimum"]:
                    break
                location = _locations(candidate["b"], default)[0]
                inserted = False
                for position in range(len(hint_order) + 1):
                    left = hint_order[position - 1] if position else None
                    right = hint_order[position] if position < len(hint_order) else None
                    prev_end = hint_times[id(left)][1] if left else awake_start
                    from_loc = _locations(left["b"], default)[1] if left else start_home
                    next_start = hint_times[id(right)][0] if right else awake_end
                    to_loc = _locations(right["b"], default)[0] if right else end_home
                    earliest = max(after, prev_end + (rest if left and left["work"] else 0) + _route(from_loc, location, settings, route_minutes))
                    start = math.ceil(earliest / 5) * 5
                    travel_after = _route(location, to_loc, settings, route_minutes) if right or end_home else 0
                    recovery_after = rest if right or travel_after else 0
                    limit = min(candidate["deadline"], next_start - recovery_after - travel_after)
                    duration_grid = candidate["duration_grid"]
                    duration = min(need, candidate["maximum"], math.floor((limit - start) / duration_grid) * duration_grid)
                    if duration < candidate["minimum"]:
                        continue
                    hint_times[id(candidate)] = (start, start + duration)
                    hint_order.insert(position, candidate)
                    hint_alloc[tid] = hint_alloc.get(tid, 0) + duration
                    hint_daily_counts[definition_id] = hint_daily_counts.get(definition_id, 0) + 1
                    hinted_work_minutes += duration
                    after = start + duration + rest
                    made_progress, inserted = True, True
                    break
                if not inserted:
                    break
        if not made_progress or not deferred:
            break
        pending = deferred
    for n in nodes:
        if n["task"] is None:
            continue
        present = id(n) in hint_times
        start, end = hint_times.get(id(n), (0, 0))
        for var, value in [(n["p"], int(present)), (n["s"], start), (n["e"], end),
                           (n["d"], end - start), (n["grid"], start // 5), (n["d_grid"], (end - start) // n["duration_grid"])]:
            model.add_hint(var, value)
    for node in nodes:
        if not node["work"]:
            continue
        start, end = hint_times.get(id(node), (0, 0))
        duration = end - start
        model.add_hint(node["focus"], duration)
        if rest:
            model.add_hint(node["sustained"], int(duration >= focus_limit))
            model.add_hint(node["focus_bound"], max(focus_limit, duration))
    selected_pairs = {(id(a) if a else None, id(b) if b else None)
                      for a, b in zip([None] + hint_order, hint_order + [None])}
    for reset, left, right in recovery_decisions:
        model.add_hint(reset, int((id(left), id(right)) in selected_pairs))
    model.add_hint(empty, int(not hint_order))
    for edge, left, right, _, _ in arc_metadata:
        model.add_hint(edge, int((id(left) if left else None, id(right) if right else None) in selected_pairs))
    solver = cp_model.CpSolver()
    challenging_search = len(nodes) >= 10 and len(optional_work) >= 5
    explicit_budget = "solver_seconds" in settings
    solver_budget = max(0, float(settings.get("solver_seconds", 20 if challenging_search else 8)))
    default_workers = min(8, os.cpu_count() or 1) if challenging_search and not explicit_budget else 1
    search_workers = max(1, min(8, int(settings.get("solver_workers", default_workers))))
    budget_policy = "explicit_budget" if explicit_budget else "interactive_portfolio" if challenging_search else "simple_day"
    solver.parameters.max_time_in_seconds = solver_budget
    solver.parameters.num_search_workers = search_workers
    solver.parameters.random_seed = 42
    if len(nodes) > 30:
        # Large optional circuits otherwise spend the short interactive budget
        # probing/linearizing before returning any incumbent. This keeps the
        # same CP-SAT model and hard constraints while favoring a real feasible
        # solution; FEASIBLE is still reported separately from proven OPTIMAL.
        solver.parameters.linearization_level = 0
        solver.parameters.cp_model_probing_level = 0
        solver.parameters.max_presolve_iterations = 2
    result = solver.solve(model)
    status_name = solver.status_name(result)
    if result == cp_model.UNKNOWN:
        return failure([], status_name, "timeout")
    if result == cp_model.MODEL_INVALID:
        return failure(["CP-SAT rejected the scheduling model. Review solver configuration and model diagnostics; this does not establish that the day's commitments are infeasible."], status_name)
    if result not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        order = " then ".join(item["definition"]["name"] for item in meals)
        meal_conflict = ([f"Required meal order ({order}) cannot fit with the fixed commitments, protected meals, recovery breaks, travel and awake windows. Review meal order in Preferences, adjust editable meal durations or commitments, or extend waking hours. Locked and completed meals are preserved."]
                         if meals else ["Fixed commitments, protected meals, recovery breaks, or travel cannot fit. Move a commitment, adjust meals, or extend waking hours."])
        return failure(meal_conflict, status_name)
    output = []
    for node in nodes:
        if not solver.value(node["p"]):
            continue
        b = deepcopy(node["b"])
        start, end = solver.value(node["s"]), solver.value(node["e"])
        if node.get("fixed") and ((b.get("locked") and (node.get("configured_meal") or b.get("task_id") or b.get("meal_id") or b.get("resolved_location_id"))) or b.get("status") in {"completed", "in_progress"}
                                 or b.get("_withdrawn_history") or b.get("_elapsed_work_history")):
            # Historical evidence is immutable, including its original metadata
            # and rationale. Inferred policies belong to solver state only.
            output.append(b)
            continue
        b.update(start=iso(start), end=iso(end), location_mode=_location_mode(b),
                 resolved_location_id=places[solver.value(node["origin"])])
        b.setdefault("rationale", "")
        if node.get("meal") and abs(start - node["preferred"]) >= 60:
            b["rationale"] += f" Placed {abs(start - node['preferred'])} minutes from its preferred timing to preserve feasibility. Review the meal preference or commitments if this is inconvenient."
        if node["task"]:
            context_reasons = (node["task"].get("planning_context") or {}).get("rationale", [])
            if context_reasons:
                b["rationale"] += " " + " ".join(context_reasons[:2])
        if _location_mode(b) == "unspecified" and b["kind"] != "travel":
            b["rationale"] += " Location unspecified: attendance location and route coverage are uncertain."
        elif _location_mode(b) == "preferred":
            suitability = b.get("location_suitability") or {}
            candidate = next((item for item in suitability.get("candidates", [])
                              if item.get("location_id") == b.get("resolved_location_id")), {})
            if b.get("resolved_location_id") != b.get("location_id"):
                source = candidate.get("source")
                basis = "verified suitable" if source == "verified_capabilities" else "explicitly permitted"
                b["rationale"] += f" Scheduled at a {basis} alternative venue; the configured preferred venue remains unchanged. Travel uses the actual venue."
            else:
                b["rationale"] += " Scheduled at the configured preferred venue."
            if candidate.get("evidence"):
                b["rationale"] += " Venue evidence: " + candidate["evidence"].rstrip(".") + "."
            if suitability.get("limitation"):
                b["rationale"] += " " + suitability["limitation"]
            elif len(allowed_location_ids(b)) == 1:
                b["rationale"] += " No other suitable venue is known; add verified place details or confirm an alternative."
        output.append(b)
    # Materialize the exact travel already enforced by selected circuit arcs.
    for edge, left, right, travel, recovery in arc_metadata:
        if not solver.value(edge):
            continue
        travel = solver.value(travel)
        recovery = solver.value(recovery)
        start = solver.value(left["e"]) if left else awake_start
        end = solver.value(right["s"]) if right else start + recovery + travel
        if recovery:
            output.append(_block("Recovery break", "break", iso(start), iso(start + recovery),
                                 location_id=places[solver.value(left["destination"])],
                                 rationale="Meaningful recovery between sustained focus runs; short authorized chunks may share one run."))
        if travel:
            origin = places[solver.value(left["destination"])] if left else start_home
            dest = places[solver.value(right["origin"])] if right else end_home
            output.append(_block("Walk" + (" home" if right is None else " to next activity"), "travel",
                                 iso(end - travel), iso(end), location_id=dest,
                                 origin_id=origin, destination_id=dest, estimated=True,
                                 rationale=f"{travel} minutes reserved by the optimizer, including travel buffer. See Locations for route source."))
    output.sort(key=lambda b: _dt(b["start"], tz).astimezone(UTC))
    progress = daily_session_progress(output, tasks, settings)
    daily_counts = {item["task_definition_id"]: item["scheduled_sessions"]
                    for item in progress if item["date"] == date}
    # These diagnostics describe the returned itinerary, not a second solver.
    # In particular, an empty final gap says nothing about possible rearrangements.
    occupied_nonwork = []
    actual_work_minutes = 0
    tail_start = work_start
    tail_location = start_home
    for block in output:
        start, end = offset(_dt(block["start"], tz)), offset(_dt(block["end"], tz))
        if start < work_end and end > work_start:
            tail_start = max(tail_start, min(work_end, end))
            tail_location = _locations(block, default)[1]
            if block["kind"] not in WORK_KINDS:
                occupied_nonwork.append((max(work_start, start), min(work_end, end)))
            elif block.get("status") != "skipped":
                actual_work_minutes += min(work_end, end) - max(work_start, start)
    merged = []
    for start, end in sorted(occupied_nonwork):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    actual_capacity = max(0, work_end - work_start - sum(end - start for start, end in merged))
    tail_candidates = []
    unallocated = []
    for t in active:
        allocated = solver.value(allocations[t["id"]])
        remaining_minutes = remaining(t) - allocated
        chunk_grid = 1 if t.get("exact_minutes") else 5
        configured_minimum = (max(0, remaining(t) - fixed_alloc.get(t["id"], 0))
                              if not t.get("splittable", True) else
                              max(chunk_grid, math.ceil(t.get("min_session_minutes", 25) / chunk_grid) * chunk_grid))
        minimum = min((node["minimum"] for node in task_nodes[t["id"]]), default=configured_minimum or None)
        maximum = t.get("max_sessions_per_day")
        count = daily_counts.get(t.get("task_definition_id") or t["id"], 0)
        maximum_reached = maximum is not None and count >= maximum
        if remaining_minutes:
            tail_candidates.append({"task_id": t["id"], "remaining_minutes": remaining_minutes,
                                    "minimum_chunk_minutes": minimum,
                                    "daily_maximum_sessions": maximum,
                                    "scheduled_sessions": count,
                                    "daily_maximum_reached": maximum_reached,
                                    "travel_from_tail_location_minutes": (_route(tail_location, _locations(t, default)[0], settings, route_minutes)
                                                                         if tail_location is not None else None)})
        target = min(remaining(t), t.get("weekly_planned_minutes", 0)) if t.get("weekly_opportunity") else remaining(t)
        missing = max(0, target - allocated)
        if missing:
            constraint_detail = (f" The remaining session requires a permitted chunk of at least {minimum} minutes." if minimum is not None else " No permitted session candidate was generated for the remaining work.")
            if maximum_reached:
                constraint_detail += f" This task has reached its daily maximum of {maximum} work blocks."
            unallocated.append({"task_id": t["id"], "title": t["title"], "minutes": missing,
                                "reason": reasons.get(t["id"], f"Remaining work competes with fixed commitments, deadlines, prerequisites, travel, essential recovery and the {level.replace('_', ' ')} workload's preference for useful progress and free time. Review the forecast or adjust preferences.") + constraint_detail})
    # Never publish a feasible status if an independent invariant check fails.
    errors = validate_blocks(output, settings, route_minutes, tasks, protected_blocks=blocks)
    errors.extend(validate_required_meals(output, meals))
    supply_explanation = (
        "All baseline work offered for today is allocated; additional optional weekly work may remain available."
        if not unallocated and tail_candidates else
        "All offered eligible work is allocated; a higher workload cannot invent more work from this finite candidate supply."
        if not unallocated else
        "Remaining work reflects hard constraints and soft value, recovery, timing and workload tradeoffs; unallocated minutes alone do not prove that no additional work can fit."
    )
    if result != cp_model.OPTIMAL:
        supply_explanation += " The search returned a feasible incumbent within its budget; its objective bound reports remaining uncertainty, so similar workload results are not proof of identical optima."
    if search_workers > 1:
        supply_explanation += f" CP-SAT used {search_workers} parallel search workers within a {solver_budget:g}-second budget; parallel incumbent choices may vary between runs despite the fixed seed."
    tail_explanations = []
    if tail_candidates:
        minimum_chunks = [item["minimum_chunk_minutes"] for item in tail_candidates if item["minimum_chunk_minutes"]]
        tail_text = (f"The returned itinerary leaves {max(0, work_end - tail_start)} consecutive free minutes before "
                     f"{iso(work_end)[11:16]}. "
                     + (f"Remaining candidates require permitted chunks of at least {min(minimum_chunks)} minutes. " if minimum_chunks else ""))
        capped = sum(item["daily_maximum_reached"] for item in tail_candidates)
        if capped:
            tail_text += f"{capped} remaining candidate(s) have reached their task's daily maximum. "
        tail_explanations.append(tail_text + "This describes the current placement; travel, recovery and other constraints still apply, and rearranging the day may fit more work.")
    base.update(blocks=output, unallocated=unallocated, conflicts=errors,
                daily_progress=progress,
                status="infeasible" if errors else "partial" if unallocated else "optimal" if result == cp_model.OPTIMAL else "feasible",
                solver_status=status_name,
                explanations=["CP-SAT enforces fixed commitments, no overlap, deadlines, prerequisites and route-dependent travel.",
                              "" + {"balanced": "Balanced mode rewards academic progress and personal projects.", "deadline": "Deadline First increases priority and deadline proximity weights.", "deep": "Deep Work penalizes extra sessions to favor longer uninterrupted work."}.get(mode, "Balanced optimization."),
                              "Unallocated work remains in your task list; generation never marks work completed.",
                              supply_explanation,
                              f"{level.replace('_', ' ').title()} workload uses profile opportunity/fatigue costs of {profile['opportunity_cost']}/{profile['fatigue_penalty']} points per work minute. Fatigue and legacy-task opportunity costs use strategy scale {workload_scale:g}; weekly-unit opportunity costs use scale 1 because their work values already reflect the strategy. Fatigue begins beyond a soft {profile['preferred_utilization_ratio']:.0%} utilization preference with up to 120 minutes of useful-progress allowance. Urgent explicit deadline risk receives 2000 additional points per minute; this may exceed the preference. These are soft objectives, never required hours or time-of-day cutoffs.",
                              "Recovery follows actual sustained focus before subsequent activity or travel home. No automatic recovery is added after the final activity when no journey follows. Short authorized chunks may share a focus run; meals and real rest gaps restore capacity, while walking does not. Difficulty changes pacing and energy placement, not intrinsic task value.",
                              "Workload compactness softly rewards a shorter work envelope and earlier completion relative to configured availability, excluding fixed activities and meals inside those intervals. Direct work-to-work idle excludes reserved travel and recovery. These preferences never change hard availability or required activity order.",
                              "Enabled meals are essential flexible intervals inside awake hours and follow their configured Preferences order, including locked and completed meals. Legacy clock times and ordinary timing remain soft preferences around commitments and travel.",
                              "Remote sessions and meals may use a reachable physical position; any relocation reserves travel before the session. Required venues stay fixed; preferred venues may use explicitly permitted or verified suitable alternatives. Travel uses the actual venue."] + tail_explanations + (["Some activities have unspecified locations: attendance locations are unknown, so their travel coverage cannot be verified."] if any(_location_mode(b) == "unspecified" and b["kind"] not in {"travel", "break", "meal"} for b in output) else []) + project_explanations,
                stats={"allocated_minutes": sum(solver.value(a) for a in allocations.values()),
                       "unallocated_minutes": sum(t["minutes"] for t in unallocated),
                       "travel_minutes": sum(_minutes(_dt(b["start"], tz), _dt(b["end"], tz)) for b in output if b["kind"] == "travel"),
                       "solver_seconds": round(solver.wall_time, 3), "optimal": result == cp_model.OPTIMAL,
                       "objective_value": solver.objective_value, "objective_bound": solver.best_objective_bound,
                       "objective_absolute_gap": max(0, solver.best_objective_bound - solver.objective_value),
                       "objective_relative_gap": max(0, solver.best_objective_bound - solver.objective_value) / max(1, abs(solver.objective_value)),
                       "solver_branches": solver.num_branches, "solver_conflicts": solver.num_conflicts,
                       "termination_reason": "proven_optimal" if result == cp_model.OPTIMAL else "search_limit_with_feasible_incumbent",
                       "candidate_minutes": sum(remaining(t) for t in active),
                       "productive_capacity_estimate_minutes": productive_capacity,
                       "actual_productive_capacity_minutes": actual_capacity,
                       "actual_work_minutes_within_window": actual_work_minutes,
                       "actual_unused_productive_minutes": max(0, actual_capacity - actual_work_minutes),
                       "tail_diagnostics": {"start": iso(tail_start), "end": iso(work_end),
                                            "contiguous_free_minutes": max(0, work_end - tail_start),
                                            "remaining_candidates": tail_candidates,
                                            "scope": "Returned itinerary only; chunk sizes, daily limits and travel are local facts. Feasibility also depends on deadlines, prerequisites, recovery, venues and rearrangement; these diagnostics do not prove that more work cannot fit."},
                       "estimated_unused_productive_minutes": max(0, productive_capacity - solver.value(total_work)),
                       "optional_work_extent_minutes": solver.value(work_extent),
                       "optional_completion_extent_minutes": solver.value(completion_extent),
                       "forced_work_extent_occupancy_minutes": sum(solver.value(value) for value in forced_extent_occupancy),
                       "discretionary_work_idle_minutes": sum(solver.value(value) for value in discretionary_idle),
                       "configured_solver_seconds": solver_budget,
                       "random_seed": 42, "search_workers": search_workers,
                       "solver_budget_policy": budget_policy,
                       "solver_budget_reason": ("At least ten intervals and five optional work candidates use the bounded interactive portfolio."
                                                if challenging_search and not explicit_budget else
                                                "An explicitly supplied time limit is honored; one worker is used unless explicitly overridden."
                                                if explicit_budget else "A simple day uses the shorter single-worker search."),
                       "parallel_search_nondeterministic": search_workers > 1,
                       "hinted_work_minutes": hinted_work_minutes,
                       "workload_profile": profile, "preferred_work_minutes": preferred_minutes,
                       "workload_cost_scale": workload_scale,
                       "weekly_opportunity_cost_scale": 1.0,
                       "effective_work_start": iso(work_start), "effective_work_end": iso(work_end)})
    return base
