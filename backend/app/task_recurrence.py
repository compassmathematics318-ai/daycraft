"""Lazy recurrence identities and explicit weekly metadata overrides.

Reads produce transient ORM-shaped values; only planner/progress/override writes
materialize a row. No recurrence expansion writes future assignments.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from .database import Activity, Configuration, TaskDefinition, TaskWeek
from .schemas import sunday_of

OVERRIDE_FIELDS = {
    "title", "task_type", "importance", "difficulty", "description",
    "academic_subtype", "due_at", "assessment_at", "deadline_at", "course",
    "hard_deadline", "related_activity_id", "earliest_start", "allow_splitting",
    "min_chunk_minutes", "dependencies", "preferred_days", "preferred_time_of_day",
    "preferred_start", "preferred_end", "location_id", "location_mode", "room", "status",
    "min_sessions_per_day", "max_sessions_per_day", "allow_alternative_locations", "alternative_location_ids", "location_requirements",
}
DATE_FIELDS = ("due_at", "assessment_at", "deadline_at", "earliest_start")


def recurring_id(definition_id, week):
    return f"recurring:{definition_id}:{week}"


def applies(definition, week):
    recurrence = definition.payload.get("recurrence")
    if not recurrence or definition.scheduling_model != "weekly" or definition.payload.get("deleted_at"):
        return False
    if recurrence.get("stopped_from_week") and week >= recurrence["stopped_from_week"]:
        return False
    start, end = recurrence.get("start_week"), recurrence.get("end_week")
    if start and week < start or end and week > end:
        return False
    return not start or ((date.fromisoformat(week) - date.fromisoformat(start)).days // 7) % recurrence.get("interval_weeks", 1) == 0


def virtual_row(definition, week):
    return TaskWeek(id=recurring_id(definition.id, week), task_definition_id=definition.id, week_start=week, payload={
        "session_minutes": definition.payload["session_minutes"],
        "min_sessions_per_week": definition.payload["min_sessions_per_week"],
        "status": "todo", "notes": "", "overrides": {}, "source": "recurring",
        "is_virtual": True, "definition_snapshot": dict(definition.payload),
    })


def effective_rows(db, week):
    rows = list(db.scalars(select(TaskWeek).where(TaskWeek.week_start == week).order_by(TaskWeek.id)))
    assigned = {row.task_definition_id for row in rows}
    for definition in db.scalars(select(TaskDefinition).order_by(TaskDefinition.id)):
        if definition.id not in assigned and applies(definition, week):
            rows.append(virtual_row(definition, week))
    return rows


def resolve_assignment(db, key):
    row = db.get(TaskWeek, key)
    if row:
        definition = db.get(TaskDefinition, row.task_definition_id)
        payload, _ = effective_value(db, row, definition)
        row.payload = payload
        return row
    if not key.startswith("recurring:"):
        return None
    try:
        definition_id, week = key[len("recurring:"):].rsplit(":", 1)
        parsed = date.fromisoformat(week)
        if sunday_of(parsed).isoformat() != week:
            return None
    except ValueError:
        return None
    definition = db.get(TaskDefinition, definition_id)
    if not definition or not applies(definition, week):
        return None
    existing = db.scalar(select(TaskWeek).where(TaskWeek.task_definition_id == definition_id, TaskWeek.week_start == week))
    if existing:
        return existing if existing.id == key else None
    row = virtual_row(definition, week)
    row.payload = {**row.payload, "is_virtual": False}
    db.add(row)
    db.flush()
    return row


def effective_value(db, row, definition):
    """Defaults flow forward; materialized session snapshots never change."""
    payload = dict(row.payload)
    source = payload.get("source", "explicit")
    config = db.get(Configuration, "settings")
    timezone = config.payload.get("timezone", "America/Toronto") if config else "America/Toronto"
    current = sunday_of(datetime.now(ZoneInfo(timezone)).date()).isoformat()
    future = row.week_start >= current
    if source == "recurring" and future:
        changed = payload.get("overridden_fields", [])
        for field in ("session_minutes", "min_sessions_per_week"):
            if field not in changed:
                payload[field] = definition.payload[field]
        payload["definition_snapshot"] = dict(definition.payload)
    base = payload.get("definition_snapshot", definition.payload) if source == "recurring" and not future else definition.payload
    effective = {"allow_alternative_locations": False, "alternative_location_ids": [], "room": "", "min_sessions_per_day": 1, "max_sessions_per_day": None, **base, **payload.get("overrides", {}), "session_minutes": payload["session_minutes"], "min_sessions_per_week": payload["min_sessions_per_week"]}
    # The FK owns the live link. Historical payload snapshots cannot resurrect a
    # deleted activity; per-week overrides still resolve against today's library.
    related = payload.get("overrides", {}).get("related_activity_id", definition.related_activity_id)
    effective["related_activity_id"] = related if related and db.get(Activity, related) else None
    # Lifecycle always reflects the live definition unless explicitly opted in.
    lifecycle = definition.payload.get("status", "active")
    effective["status"] = "completed" if lifecycle == "completed" else payload.get("overrides", {}).get("status", lifecycle)
    if payload.get("allow_inactive") and lifecycle != "completed" and not definition.payload.get("deleted_at"):
        effective["status"] = "active"
    payload.update({field: effective[field] for field in ("min_sessions_per_day", "max_sessions_per_day")})
    return payload, effective


def validate_overrides(value):
    unknown = set(value) - OVERRIDE_FIELDS
    if unknown:
        raise HTTPException(422, "Unknown or protected weekly override fields: " + ", ".join(sorted(unknown)))


def shifted_dates(value, days, timezone):
    output = dict(value)
    for field in DATE_FIELDS:
        if output.get(field):
            parsed = datetime.fromisoformat(output[field].replace("Z", "+00:00"))
            zone = ZoneInfo(timezone)
            shifted = parsed.astimezone(zone) + timedelta(days=days)
            if shifted.astimezone(ZoneInfo("UTC")).astimezone(zone).replace(tzinfo=None) != shifted.replace(tzinfo=None):
                raise HTTPException(422, f"Shifted {field} falls in a daylight-saving gap; choose preserve dates or adjust the source date")
            output[field] = shifted.isoformat()
    return output
