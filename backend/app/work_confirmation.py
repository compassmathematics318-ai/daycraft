"""Explicit evidence for saved work; elapsed reservations alone never earn credit."""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from . import task_library
from .database import Entity, LogicalSession, Schedule, TaskChunk, TaskWeek


EVIDENCE_FIELDS = ("completion_confirmed_at", "completion_previous_status", "completion_verified", "completion_remaining_minutes_delta")


def fail(message, status=409):
    raise HTTPException(status, message)


def instant(raw):
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        fail("Saved work has an invalid timestamp", 422)
    if value.tzinfo is None or value.utcoffset() is None:
        fail("Saved work timestamps must include timezone offsets", 422)
    return value


def eligible_time(block, now, require_elapsed=True):
    start, end = instant(block["start"]), instant(block["end"])
    if end <= start or start.second or end.second or start.microsecond or end.microsecond:
        fail("Saved work must have a positive whole-minute duration", 422)
    if require_elapsed and end > now:
        fail("Work can only be confirmed after its scheduled end time")


def stamp(before, after, completed, now):
    """Apply only an explicit transition; repeated requests retain audit timestamps."""
    was_complete = before.get("status") == "completed"
    if completed == was_complete:
        return
    if completed:
        after.update(status="completed", completion_confirmed_at=now.isoformat(),
                     completion_previous_status=before.get("status", "todo"), completion_verified=True)
    else:
        after["status"] = before.get("completion_previous_status") or "todo"
        for field in EVIDENCE_FIELDS:
            after.pop(field, None)


def validate_manual_evidence(old, blocks, settings, now=None):
    """Guard general edits before any solver import; never accept client evidence."""
    now = now or datetime.now(ZoneInfo(settings["timezone"]))
    previous = {item["id"]: item for item in old.get("blocks", [])}
    for block in blocks:
        before = previous.get(block["id"], {})
        for field in EVIDENCE_FIELDS:
            default = False if field == "completion_verified" else None
            supplied, trusted = block.get(field, default), before.get(field, default)
            if field == "completion_confirmed_at" and supplied and trusted:
                supplied, trusted = instant(supplied), instant(trusted)
            if supplied != trusted:
                fail("Work confirmation evidence is server-owned", 422)
        if block.get("kind") not in {"task", "project"}:
            continue
        if block.get("status") == "completed" and before.get("status") != "completed":
            if not before:
                fail("Only saved work blocks can be confirmed", 422)
            if any(instant(block[field]) != instant(before[field]) for field in ("start", "end")):
                fail("Save time changes before confirming the saved work block", 422)
            eligible_time(before, now)
            stamp(before, block, True, now)
        elif before.get("status") == "completed" and block.get("status") != "completed":
            desired = block.get("status")
            stamp(before, block, False, now)
            # The general edit API retains its existing explicit status choice.
            block["status"] = desired


def refresh_projections(db, settings, week_start):
    """Refresh display counters from the authoritative ledger, without optimizing."""
    from .progress import daily_session_progress
    from .schemas import sunday_of

    state = task_library.week_state(db, week_start)
    assignments = {item["id"]: item for item in state["assignments"] + state["history_assignments"]}
    for row in db.scalars(select(Schedule)):
        if sunday_of(datetime.fromisoformat(row.date).date()).isoformat() != state["week_start"]:
            continue
        payload = deepcopy(row.payload)
        if "daily_progress" in payload:
            policies = {item["id"]: item for item in payload.get("task_week_context", {}).get("definitions", [])}
            for block in payload.get("blocks", []):
                definition, _, _ = task_library.withdrawn_work(db, block)
                if definition and definition.id not in policies:
                    policies[definition.id] = {**task_library.definition_value(definition), "id": definition.id}
            for item in payload["daily_progress"]:
                key = item["task_definition_id"]
                policies[key] = {**policies.get(key, {}), "id": key, "title": item["title"],
                                 "min_sessions_per_day": item["minimum_sessions"], "max_sessions_per_day": item.get("maximum_sessions")}
            payload["daily_progress"] = daily_session_progress(payload.get("blocks", []), list(policies.values()), settings)
        for item in payload.get("weekly_progress", []):
            assignment = assignments.get(item["assignment_id"])
            if not assignment:
                continue
            item["completed_sessions"] = assignment["completed_sessions"]
            item["expected_sessions"] = assignment["allocated_sessions"]
            item["expected_shortfall"] = max(0, item["minimum_sessions"] - assignment["allocated_sessions"])
            item["planned_today_minutes"] = sum(task_library.length(block["start"], block["end"]) for block in payload.get("blocks", [])
                                                if block.get("task_assignment_id") == assignment["id"] and block.get("status") not in {"completed", "skipped"})
            item.update(forecast=False, solver_status="not_run", projection_basis="verified_and_saved_reservations")
        row.payload = payload


def confirm_block(db, schedule, block_id, completed, settings, now=None):
    """Update one trusted block and its existing ledger without solving a new plan.

    This narrow status-only operation also permits withdrawn historical work.
    It never edits timing, venue, task lifecycle or assignment eligibility.
    """
    now = now or datetime.now(ZoneInfo(settings["timezone"]))
    saved = schedule.payload.get("blocks", [])
    matches = [block for block in saved if block.get("id") == block_id]
    if not matches:
        fail("Saved work block not found", 404)
    if len(matches) != 1:
        fail("Saved work block identity is ambiguous", 422)
    before = matches[0]
    if before.get("kind") not in {"task", "project"} or not before.get("task_id"):
        fail("Only task work blocks can be confirmed", 422)
    eligible_time(before, now, require_elapsed=completed)
    # IDs are unique across ledger rows; also reject corrupt duplicate JSON IDs.
    if any(other.id != schedule.id and any(item.get("id") == block_id for item in other.payload.get("blocks", []))
           for other in db.scalars(select(Schedule))):
        fail("Saved work block identity is ambiguous", 422)
    chunk = db.get(TaskChunk, block_id)
    definition, assignment, withdrawn = task_library.withdrawn_work(db, before)
    if not definition:
        fail("Saved work references a missing task", 422)
    if before["task_id"] not in {definition.id, definition.legacy_task_id}:
        fail("Saved work task identity does not match its definition", 422)
    if chunk:
        logical = db.get(LogicalSession, chunk.logical_session_id)
        assignment = db.get(TaskWeek, logical.assignment_id) if logical else None
        if not logical or not assignment or chunk.schedule_id != schedule.id or assignment.task_definition_id != definition.id:
            fail("Saved work ledger references do not match", 422)
        if instant(chunk.start) != instant(before["start"]) or instant(chunk.end) != instant(before["end"]) or chunk.status != before.get("status", "todo"):
            fail("Saved work and its ledger disagree; review the saved plan", 409)
        checks = {"logical_session_id": logical.id, "task_assignment_id": assignment.id, "task_definition_id": definition.id}
        if any(before.get(key) and before[key] != value for key, value in checks.items()):
            fail("Saved work ledger identity does not match", 422)
    elif definition.scheduling_model == "weekly" or before.get("logical_session_id") or withdrawn:
        fail("Saved weekly or withdrawn work requires its original chunk ledger", 422)
    if completed == (before.get("status") == "completed"):
        return schedule.payload
    updated = deepcopy(schedule.payload)
    after = next(block for block in updated["blocks"] if block["id"] == block_id)
    stamp(before, after, completed, now)
    if chunk:
        chunk.status = after["status"]
        chunk.credited_minutes = task_library.length(chunk.start, chunk.end) if completed else 0
        db.flush()
        task_library.reconcile_session_credit(db, chunk.logical_session_id)
    else:
        # Compatibility finite tasks already own their remaining-minute counter.
        entity = db.get(Entity, ("tasks", definition.legacy_task_id or definition.id))
        if not entity:
            fail("Saved work references a missing finite task", 422)
        duration = task_library.length(before["start"], before["end"])
        remaining = entity.payload["remaining_minutes"]
        prior_delta = before.get("completion_remaining_minutes_delta")
        delta = min(duration, remaining) if completed else prior_delta if prior_delta is not None else duration
        if completed:
            after["completion_remaining_minutes_delta"] = delta
        remaining = max(0, min(entity.payload["duration_minutes"], remaining + (-delta if completed else delta)))
        entity.payload = {**entity.payload, "remaining_minutes": remaining}
        # Do not change the canonical task's explicit lifecycle.
    schedule.payload = updated
    db.flush()
    refresh_projections(db, settings, assignment.week_start if assignment else schedule.date)
    return updated
