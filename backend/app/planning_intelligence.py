"""Auditable local planning rules. Text suggestions never create stored facts.

Objective weights use the daily solver's unscaled per-minute value units.
Workload preferences are independent of Balanced/Deadline/Deep Work strategies.
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone


_PROFILES = {
    "very_low": (450, .20, 800, 18, .75, 1.5),
    "low": (250, .40, 700, 12, .90, 1.25),
    "medium": (0, .60, 600, 7, 1.0, 1.0),
    "high": (0, .80, 500, 4, 1.15, .90),
    "very_high": (0, .95, 400, 2, 1.25, .85),
}


def workload_profile(level="medium"):
    """Soft costs only; no profile changes availability or essential recovery."""
    level = level if level in _PROFILES else "medium"
    keys = ("opportunity_cost", "preferred_utilization_ratio", "fatigue_penalty",
            "late_penalty_per_hour", "focus_multiplier", "recovery_multiplier")
    # Values remain soft marginal costs in the daily objective's point units.
    # Compactness never creates a working-hour cutoff or a minimum quota.
    index = tuple(_PROFILES).index(level)
    efficiency = {
        "advance_work_multiplier": (.55, .75, 1.0, 1.3, 1.85),
        "allow_advance_candidates": (False, False, False, True, True),
        "compactness_penalty_per_minute": (8, 6, 4, 2, 1),
        "idle_penalty_per_minute": (12, 9, 6, 3, 1),
        "completion_penalty_per_minute": (12, 9, 6, 3, 1),
        "late_start_ratio": (.50, .55, .65, .80, .90),
    }
    return {"level": level, **dict(zip(keys, _PROFILES[level], strict=True)),
            **{key: values[index] for key, values in efficiency.items()}}


def _instant(value, tz):
    value = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)


def assessment_preparation_cutoff(task, tz):
    """Actual assessment start bounds explicitly declared preparation work.

    This derived eligibility bound is never written into the task's due or
    assessment fields. A generic relationship or text cue supplies no cutoff.
    """
    activity = task.get("related_activity") or {}
    if (task.get("task_type") == "academic"
            and task.get("academic_subtype") == "assessment_preparation"
            and activity.get("category") == "assessment"
            and activity.get("assessment_start")):
        return _instant(activity["assessment_start"], tz)
    return None


def interpret_task_context(task, reference, events=()):
    """Classify supported work cues, with evidence and bounded soft influence.

    Numeric difficulty drives demand. Text adjusts focus/recovery preferences,
    never moral priority, deadlines, locations, dependencies or completion.
    Existing venue suitability remains the sole source of permitted venues.
    """
    demand = max(0, min(10, float(task.get("difficulty", 5))))
    evidence, rationale = [], []
    text_fields = ("title", "description", "academic_subtype", "task_type")
    text = " ".join(str(task.get(field) or "") for field in text_fields).casefold()
    focus = bool(re.search(r"\b(proof|prove|study|studying|reading|read|coding|code|programming|write|writing|derive|analysis|assignment)\b|assessment_preparation", text))
    admin = bool(re.search(r"\b(email|emails|form|forms|invoice|invoices|administrative|registration|booking)\b", text))
    physical = bool(re.search(r"\b(gym|workout|weightlifting|swimming|run|running|exercise|fitness)\b", text))
    # Writing about exercise is cognitive work, not evidence of actual exertion.
    if physical and re.search(r"\b(plan|planning|research|compare|write|writing|review|membership)\b", text):
        physical = False
    project = task.get("project") or {}
    project_focus = False
    if not any((focus, admin, physical)):
        project_text = " ".join(str(project.get(field) or "") for field in ("title", "name", "description", "category")).casefold()
        project_focus = bool(re.search(r"\b(proof|coding|programming|writing|research|analysis)\b", project_text))
        focus = project_focus
    flags = [name for name, matched in (("focus", focus), ("administrative", admin), ("physical", physical)) if matched]
    modality = flags[0] if len(flags) == 1 else "mixed" if flags else "unspecified"
    for field in text_fields:
        if task.get(field):
            evidence.append({"field": field, "value": str(task[field])[:240], "rule": "local work-modality cues; no factual constraints inferred"})
    if flags:
        rationale.append(f"Work cues suggest {modality} work; this adjusts focus and recovery preferences only.")
    if project_focus:
        rationale.append("For this otherwise unspecified task, project work cues suggest a focus preference; no project facts became constraints.")
    focus_preference = "longer" if focus and not physical else "shorter" if admin and not focus else "neutral"
    bonus = 0
    activity = task.get("related_activity") or {}
    occurrences = activity.get("occurrences", [])
    today = reference.date().isoformat()
    same_day = [event for event in occurrences if event.get("start") and _instant(event["start"], reference.tzinfo).date().isoformat() == today]
    if activity.get("category") == "class" and same_day and focus:
        bonus = 10
        rationale.append("Related class occurs today; a small continuity preference supports separate study work.")
        evidence.append({"field": "related_activity", "value": activity.get("id", ""), "rule": "same-day explicitly linked class continuity: +10"})
    recovery_after = []
    if activity.get("category") == "commitment" and same_day:
        long_event = any(event.get("end") and (_instant(event["end"], reference.tzinfo).astimezone(timezone.utc) - _instant(event["start"], reference.tzinfo).astimezone(timezone.utc)).total_seconds() >= 120 * 60 for event in same_day)
        if long_event:
            rationale.append("A related commitment lasts at least two hours today; favor recovery before demanding work.")
            focus_preference = "recovery" if demand >= 6 else focus_preference
            recovery_after = [event["end"] for event in same_day if event.get("end") and (_instant(event["end"], reference.tzinfo).astimezone(timezone.utc) - _instant(event["start"], reference.tzinfo).astimezone(timezone.utc)).total_seconds() >= 120 * 60]
    if project:
        rationale.append("Project importance contributes separately; project status controls eligibility. Its dates do not become task deadlines.")
        for field in ("name", "title", "description", "category", "status", "importance"):
            if project.get(field) is not None:
                evidence.append({"field": "project." + field, "value": str(project[field])[:240], "rule": "project context; no inherited deadline or work duration"})
    course = str(task.get("course") or "").strip().casefold()
    if course and focus and any(str(event.get("course") or "").strip().casefold() == course for event in events if event.get("start") and _instant(event["start"], reference.tzinfo).date().isoformat() == today):
        bonus = max(bonus, 10)
        rationale.append("An exact course match in today's fixed calendar supports study continuity; attendance grants no study credit.")
    return {"version": "rules-v1", "modality": modality, "cognitive_demand": demand,
            "focus_preference": focus_preference, "context_bonus": min(60, bonus),
            "recovery_after": recovery_after,
            "rationale": rationale, "evidence": deepcopy(evidence),
            "limitations": ["Deterministic text cues are suggestions, not inferred deadlines, venues, dependencies or completion."]}
