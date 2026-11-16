"""Canonical reusable tasks, explicit weekly work, and credited logical sessions."""
from copy import deepcopy
from datetime import date as Date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import suitability, task_schemas, task_recurrence
from .database import Activity, Configuration, Entity, LogicalSession, Project, Schedule, TaskChunk, TaskDefinition, TaskWeek
from .schemas import location_edit, sunday_of


def fail(message, status=409):
    raise HTTPException(status, message)


def current_week(settings):
    return sunday_of(datetime.now(ZoneInfo(settings["timezone"])).date()).isoformat()


def definition_value(row):
    return {"recurrence": None, "room": "", "location_requirements": [], "allow_alternative_locations": False, "alternative_location_ids": [], "min_sessions_per_day": 1, "max_sessions_per_day": None, **row.payload, "location_mode": row.payload.get("location_mode", "required" if row.payload.get("location_id") else "unspecified"), "id": row.id, "project_id": row.project_id, "related_activity_id": row.related_activity_id, "legacy_task_id": row.legacy_task_id, "scheduling_model": row.scheduling_model}


def association_summary(db, definition):
    rows = list(db.scalars(select(TaskWeek).where(TaskWeek.task_definition_id == definition.id)))
    active = [row for row in rows if not row.payload.get("removed_from_week")]
    session_weeks = {row.week_start for row in rows if db.scalar(select(LogicalSession.id).where(LogicalSession.assignment_id == row.id).limit(1))}
    config = db.get(Configuration, "settings")
    week = current_week(config.payload if config else {"timezone": "America/Toronto"})
    recurrence = definition.payload.get("recurrence") or {}
    end, stopped = recurrence.get("end_week"), recurrence.get("stopped_from_week")
    return {"assigned_week_starts": sorted(row.week_start for row in active), "stored_assignment_count": len(active), "history_week_starts": sorted(session_weeks),
            "recurring": bool(recurrence) and (not end or end >= week) and (not stopped or stopped > week),
            "repeating_from_week": recurrence.get("start_week"), "repeating_through_week": end, "stopped_from_week": stopped}


def definitions_list(db):
    return [{**definition_value(row), "association_summary": association_summary(db, row)} for row in db.scalars(select(TaskDefinition).order_by(TaskDefinition.id)) if not row.payload.get("deleted_at")]


def chunk_value(row):
    return {"id": row.id, "logical_session_id": row.logical_session_id, "schedule_id": row.schedule_id, "start": row.start, "end": row.end, "status": row.status}


def length(start, end):
    return round((datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds() / 60)


def session_value(row, definition_id=None, chunks=(), now=None):
    own = [chunk_value(item) for item in chunks if item.logical_session_id == row.id]
    planned = sum(length(item["start"], item["end"]) for item in own if item["status"] not in ("completed", "skipped"))
    now = now or datetime.now(ZoneInfo("UTC"))
    elapsed = 0.0
    for item in own:
        if item["status"] in ("completed", "skipped"):
            continue
        start = datetime.fromisoformat(item["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(item["end"].replace("Z", "+00:00"))
        elapsed += max(0, (min(end, now) - start).total_seconds() / 60)
    elapsed = min(planned, round(elapsed))
    return {"id": row.id, "assignment_id": row.assignment_id, "task_definition_id": definition_id, "index": row.index, "target_minutes": row.target_minutes, "completed_minutes": row.completed_minutes, "verified_completed_minutes": row.completed_minutes, "status": row.status, "planned_minutes": planned, "elapsed_scheduled_minutes": elapsed, "future_scheduled_minutes": planned - elapsed, "chunks": own}


def assignment_value(row, sessions, chunks, now=None):
    now = now or datetime.now(ZoneInfo("UTC"))
    own = [session_value(item, row.task_definition_id, chunks, now) for item in sessions if item.assignment_id == row.id]
    required = row.payload["min_sessions_per_week"]
    actual = [item for item in own if item["status"] != "skipped"]
    target = sum(item["target_minutes"] for item in actual) + max(0, required - len(actual)) * row.payload["session_minutes"]
    completed_minutes = sum(item["completed_minutes"] for item in own)
    completed = sum(item["completed_minutes"] >= item["target_minutes"] for item in own)
    scheduled = sum(item["completed_minutes"] < item["target_minutes"] and item["completed_minutes"] + item["planned_minutes"] >= item["target_minutes"] for item in own)
    status = row.payload.get("status", "todo")
    if status not in ("paused", "completed", "skipped"):
        status = "in_progress" if completed_minutes or status == "in_progress" else "todo"
    temporal = {key: sum(item[key] for item in own) for key in ("elapsed_scheduled_minutes", "future_scheduled_minutes")}
    return {**row.payload, "id": row.id, "task_definition_id": row.task_definition_id, "week_start": row.week_start, "status": status, "target_met": completed + scheduled >= required, "target_sessions": required, "target_minutes": target, "completed_sessions": completed, "scheduled_sessions": scheduled, "allocated_sessions": completed + scheduled, "planned_sessions": completed + scheduled, "completed_minutes": completed_minutes, "verified_completed_minutes": completed_minutes, "planned_minutes": sum(item["planned_minutes"] for item in own), **temporal, "remaining_minutes": max(0, target - completed_minutes), "remaining_target_sessions": max(0, required - completed - scheduled), "sessions": own}


def week_state(db, week):
    week = sunday_of(Date.fromisoformat(week)).isoformat()
    rows = task_recurrence.effective_rows(db, week)
    ids = [row.id for row in rows]
    sessions = list(db.scalars(select(LogicalSession).where(LogicalSession.assignment_id.in_(ids)).order_by(LogicalSession.index))) if ids else []
    session_ids = [row.id for row in sessions]
    chunks = list(db.scalars(select(TaskChunk).where(TaskChunk.logical_session_id.in_(session_ids)))) if session_ids else []
    assignments = []
    for row in rows:
        definition = db.get(TaskDefinition, row.task_definition_id)
        payload, effective = task_recurrence.effective_value(db, row, definition)
        view = TaskWeek(id=row.id, task_definition_id=row.task_definition_id, week_start=row.week_start, payload=payload)
        source = "recurring" if payload.get("source") == "recurring" or task_recurrence.applies(definition, row.week_start) else payload.get("source", "explicit")
        assignments.append({**assignment_value(view, sessions, chunks), "source": source, "is_virtual": payload.get("is_virtual", False), "allow_inactive": payload.get("allow_inactive", False), "overrides": payload.get("overrides", {}), "effective_definition": {**effective, "id": definition.id}})
    history = [item for item in assignments if item.get("removed_from_week") or db.get(TaskDefinition, item["task_definition_id"]).payload.get("deleted_at")]
    assignments = [item for item in assignments if item not in history]
    excluded = {item["id"] for item in assignments if item["status"] in ("paused", "skipped", "completed") or item["effective_definition"].get("status") in ("paused", "archived", "completed")}
    demand = ("target_sessions", "target_minutes", "remaining_minutes", "remaining_target_sessions")
    summary = {key: sum(item[key] for item in assignments if key not in demand or item["id"] not in excluded) for key in ("target_sessions", "target_minutes", "completed_sessions", "scheduled_sessions", "allocated_sessions", "planned_sessions", "completed_minutes", "verified_completed_minutes", "planned_minutes", "elapsed_scheduled_minutes", "future_scheduled_minutes", "remaining_minutes", "remaining_target_sessions")}
    summary["excluded_tasks"] = len(excluded)
    summary["assigned_tasks"] = sum(not item.get("removed_from_week") for item in assignments)
    return {"week_start": week, "week_end": (Date.fromisoformat(week) + timedelta(days=6)).isoformat(), "definitions": definitions_list(db), "assignments": assignments, "history_assignments": history, "sessions": [item for assignment in assignments + history for item in assignment["sessions"]], "summary": summary}


def compatibility_tasks(db, settings):
    old = {row.id: row.payload for row in db.scalars(select(Entity).where(Entity.collection == "tasks"))}
    week = week_state(db, current_week(settings))
    by_definition = {row["task_definition_id"]: row for row in week["assignments"]}
    result = []
    for definition in definitions_list(db):
        key = definition["id"]
        if definition["scheduling_model"] == "legacy" and key in old:
            status = "completed" if definition["status"] == "completed" else "skipped" if definition["status"] != "active" else old[key]["status"]
            result.append({"allow_alternative_locations": False, "alternative_location_ids": [], "room": "", "min_sessions_per_day": 1, "max_sessions_per_day": None, **old[key], "status": status, "project_id": definition["project_id"], "task_definition_id": key, "scheduling_model": "legacy"})
            continue
        assignment = by_definition.get(key)
        if assignment:
            definition = {**definition, **assignment["effective_definition"]}
        duration = assignment["target_minutes"] if assignment else definition["session_minutes"]
        remaining = assignment["remaining_minutes"] if assignment else 0
        status = "completed" if definition["status"] == "completed" or assignment and assignment["status"] == "completed" else "skipped" if definition["status"] != "active" or assignment and assignment["status"] in ("paused", "skipped") else "in_progress" if assignment and assignment["completed_minutes"] else "todo"
        result.append({"id": key, "title": definition["title"], "kind": "project" if definition["project_id"] or definition["task_type"] == "project_work" else "academic", "project_id": definition["project_id"], "task_definition_id": key, "scheduling_model": "weekly", "duration_minutes": duration, "remaining_minutes": remaining, "priority": max(1, min(5, round(definition["importance"] / 2))), "deadline": definition.get("due_at") or definition.get("deadline_at"), "hard_deadline": definition["hard_deadline"], "splittable": definition["allow_splitting"], "min_session_minutes": min(definition["session_minutes"], definition["min_chunk_minutes"]), "max_session_minutes": definition["session_minutes"], "dependencies": definition["dependencies"], "room": definition.get("room", ""), "min_sessions_per_day": definition.get("min_sessions_per_day", 1), "max_sessions_per_day": definition.get("max_sessions_per_day"), "location_id": definition["location_id"], "location_requirements": definition.get("location_requirements", []), "allow_alternative_locations": definition.get("allow_alternative_locations", False), "alternative_location_ids": definition.get("alternative_location_ids", []), "location_mode": definition.get("location_mode", "required" if definition.get("location_id") else "unspecified"), "status": status, "preferred_start": definition["preferred_start"], "preferred_end": definition["preferred_end"], "notes": definition["description"]})
    # Direct legacy imports/demo records are synchronized by their write path.
    known = {item["id"] for item in result}
    deleted = {key for row in db.scalars(select(TaskDefinition)) if row.payload.get("deleted_at") for key in (row.id, row.legacy_task_id) if key}
    result.extend(value for key, value in old.items() if key not in known and key not in deleted)
    return result


def mark_stale(db, reason, weeks=None):
    for row in db.scalars(select(Schedule)):
        if weeks is None or sunday_of(Date.fromisoformat(row.date)).isoformat() in weeks:
            explanations = list(row.payload.get("explanations", []))
            if reason not in explanations:
                explanations.append(reason)
            row.payload = {**row.payload, "tasks_dirty": True, "status": "stale", "explanations": explanations}


def normalize_times(value, settings):
    zone = ZoneInfo(settings["timezone"])
    for field in ("due_at", "assessment_at", "deadline_at", "earliest_start"):
        raw = value.get(field)
        if raw:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                localized = parsed.replace(tzinfo=zone)
                if localized.astimezone(ZoneInfo("UTC")).astimezone(zone).replace(tzinfo=None) != parsed:
                    fail(f"{field} is in a daylight-saving gap", 422)
                if localized.replace(fold=0).utcoffset() != localized.replace(fold=1).utcoffset():
                    fail(f"{field} is ambiguous; include an explicit timezone offset", 422)
                parsed = localized
            value[field] = parsed.isoformat()
    return value


def validate_definition_references(db, value, key):
    if value.get("project_id") and not db.get(Project, value["project_id"]):
        fail("Selected project no longer exists", 422)
    if value.get("related_activity_id") and not db.get(Activity, value["related_activity_id"]):
        fail("Related activity no longer exists", 422)
    if value.get("location_id") and not db.get(Entity, ("locations", value["location_id"])):
        fail("Selected location no longer exists", 422)
    if any(not db.get(Entity, ("locations", place)) for place in value.get("alternative_location_ids", [])):
        fail("An alternative location no longer exists", 422)
    graph = {row.id: row.payload.get("dependencies", []) for row in db.scalars(select(TaskDefinition))}
    deleted = {row.id for row in db.scalars(select(TaskDefinition)) if row.payload.get("deleted_at")}
    graph[key] = value["dependencies"]
    if any(dep not in graph or dep in deleted for dep in value["dependencies"]):
        fail("A task dependency no longer exists", 422)
    visiting, done = set(), set()
    def walk(node):
        if node in visiting:
            fail("Task dependencies cannot contain a cycle", 422)
        if node in done:
            return
        visiting.add(node)
        for dep in graph[node]:
            walk(dep)
        visiting.remove(node)
        done.add(node)
    for node in graph:
        walk(node)


def legacy_payload(value):
    duration = value.get("duration_minutes", 60)
    project_id = value.get("project_id")
    return task_schemas.TaskDefinition(id=value["id"], title=value["title"], task_type="project_work" if project_id or value.get("kind") == "project" else "academic", session_minutes=duration, min_sessions_per_week=0 if value.get("status") in ("completed", "skipped") else 1, importance=max(1, min(10, value.get("priority", 3) * 2)), difficulty=5, allow_splitting=value.get("splittable", True), min_chunk_minutes=min(duration, value.get("min_session_minutes", 25)), description=value.get("notes", ""), status="paused" if value.get("status") == "skipped" else "active", project_id=project_id, due_at=value.get("deadline") if value.get("kind", "academic") == "academic" else None, deadline_at=value.get("deadline") if value.get("kind") == "project" else None, hard_deadline=value.get("hard_deadline", True), dependencies=value.get("dependencies", []), room=value.get("room", ""), min_sessions_per_day=value.get("min_sessions_per_day", 1), max_sessions_per_day=value.get("max_sessions_per_day"), location_id=value.get("location_id"), location_requirements=value.get("location_requirements", []), allow_alternative_locations=value.get("allow_alternative_locations", False), alternative_location_ids=value.get("alternative_location_ids", []), location_mode=value.get("location_mode", "required" if value.get("location_id") else "unspecified"), preferred_start=value.get("preferred_start"), preferred_end=value.get("preferred_end")).model_dump(mode="json")


def sync_legacy_task(db, value, explicit_status=False):
    row = db.get(TaskDefinition, value["id"])
    if row and row.payload.get("deleted_at"):
        fail("This task was deleted everywhere and cannot be restored through the legacy API", 404)
    if row and row.payload.get("recurrence"):
        fail("Edit recurring tasks and their weekly progress through the task library; the finite legacy API cannot represent recurrence.")
    converted = legacy_payload(value)
    if explicit_status:
        converted["status"] = "completed" if value.get("status") == "completed" else "paused" if value.get("status") == "skipped" else "active"
    if row:
        lifecycle = converted["status"] if explicit_status else row.payload.get("status", "active")
        if lifecycle != row.payload.get("status", "active"):
            mark_stale(db, "Task completion or availability changed. Regenerate to apply its current status.")
        row.payload = {**row.payload, **converted, "course": row.payload.get("course", ""), "status": lifecycle}
        row.project_id = value.get("project_id")
    else:
        row = TaskDefinition(id=value["id"], project_id=value.get("project_id"), legacy_task_id=value["id"], legacy_snapshot=dict(value), scheduling_model="legacy", payload=converted)
        db.add(row)
    return row


def sync_legacy_alias(db, definition):
    """An old API alias reflects canonical edits without restoring finished work."""
    entity = db.get(Entity, ("tasks", definition.legacy_task_id)) if definition.legacy_task_id else None
    if not entity:
        return
    from .projects import set_task_project
    set_task_project(db, entity.id, definition.project_id)
    if definition.scheduling_model != "legacy":
        entity.payload = {**entity.payload, "project_id": definition.project_id}
        return
    value, old = definition.payload, entity.payload
    done = old["duration_minutes"] - old["remaining_minutes"]
    duration = value["session_minutes"]
    entity.payload = {**old, "title": value["title"], "duration_minutes": duration, "remaining_minutes": max(0, duration - done), "priority": max(1, min(5, round(value["importance"] / 2))), "deadline": (value.get("due_at") or value.get("assessment_at") or value.get("deadline_at")) if value["task_type"] == "academic" else value.get("deadline_at"), "hard_deadline": value["hard_deadline"], "splittable": value["allow_splitting"], "min_session_minutes": min(duration, value["min_chunk_minutes"]), "max_session_minutes": duration, "notes": value["description"], "dependencies": value["dependencies"], "preferred_start": value["preferred_start"], "preferred_end": value["preferred_end"], "room": value.get("room", ""), "min_sessions_per_day": value.get("min_sessions_per_day", 1), "max_sessions_per_day": value.get("max_sessions_per_day"), "location_id": value["location_id"], "location_requirements": value.get("location_requirements", []), "allow_alternative_locations": value.get("allow_alternative_locations", False), "alternative_location_ids": value.get("alternative_location_ids", []), "location_mode": value.get("location_mode", "required" if value.get("location_id") else "unspecified"), "project_id": definition.project_id}


def persist_chunks(db, schedule, candidates=()):
    """A chunk ledger credits transitions exactly once and preserves manual credit."""
    proposed = {item["id"]: item for item in candidates}
    current = {item.id: item for item in db.scalars(select(TaskChunk).where(TaskChunk.schedule_id == schedule.id))}
    kept, touched = set(), set()
    for block in schedule.payload.get("blocks", []):
        sid = block.get("logical_session_id")
        if not sid:
            continue
        logical = db.get(LogicalSession, sid)
        if not logical:
            value = proposed.get(sid)
            if not value:
                fail("A planner chunk references a missing logical session", 422)
            if not task_recurrence.resolve_assignment(db, value["assignment_id"]):
                fail("A planner session references a missing weekly assignment", 422)
            logical = LogicalSession(id=sid, assignment_id=value["assignment_id"], index=value["index"], target_minutes=value["target_minutes"], completed_minutes=value.get("completed_minutes", 0), baseline_completed_minutes=value.get("completed_minutes", 0), status=value.get("status", "todo"))
            db.add(logical)
            db.flush()
        chunk = current.get(block["id"])
        if chunk and chunk.logical_session_id != sid:
            fail("A planner chunk cannot change logical session", 422)
        if not chunk:
            chunk = TaskChunk(id=block["id"], logical_session_id=sid, schedule_id=schedule.id, credited_minutes=0, status="todo")
            db.add(chunk)
        if block.get("status") == "completed" and chunk.status != "completed":
            chunk.credited_minutes = length(block["start"], block["end"])
        elif block.get("status") != "completed":
            chunk.credited_minutes = 0
        chunk.start, chunk.end, chunk.status = block["start"], block["end"], block.get("status", "todo")
        kept.add(chunk.id)
        touched.add(sid)
    for key, chunk in current.items():
        if key not in kept:
            touched.add(chunk.logical_session_id)
            db.delete(chunk)
    db.flush()
    for sid in touched:
        reconcile_session_credit(db, sid)


def reconcile_session_credit(db, sid):
    """Recompute verified work from the existing chunk ledger and manual baseline."""
    logical = db.get(LogicalSession, sid)
    credited = sum(item.credited_minutes for item in db.scalars(select(TaskChunk).where(TaskChunk.logical_session_id == sid)))
    logical.completed_minutes = min(logical.target_minutes, logical.baseline_completed_minutes + credited)
    logical.status = "completed" if logical.completed_minutes == logical.target_minutes else "paused" if logical.status == "paused" else "in_progress" if logical.completed_minutes else "todo"


def saved_block_metadata(db, blocks):
    """Attach migrated ledger references to a regenerated copy, never raw history."""
    output = []
    for block in blocks:
        block = dict(block)
        chunk = db.get(TaskChunk, block["id"])
        if chunk:
            logical = db.get(LogicalSession, chunk.logical_session_id)
            assignment = db.get(TaskWeek, logical.assignment_id)
            definition = db.get(TaskDefinition, assignment.task_definition_id)
            if definition.scheduling_model == "weekly":
                block.update(task_definition_id=definition.id, task_assignment_id=assignment.id, logical_session_id=logical.id, chunk_index=logical.index)
        output.append(block)
    return output


def withdrawn_work(db, block):
    """Resolve canonical and compatibility identities without reviving aliases."""
    definition = db.get(TaskDefinition, block.get("task_definition_id") or block.get("task_id")) if block.get("task_definition_id") or block.get("task_id") else None
    if not definition and block.get("task_id"):
        definition = db.scalar(select(TaskDefinition).where(TaskDefinition.legacy_task_id == block["task_id"]))
    logical = db.get(LogicalSession, block["logical_session_id"]) if block.get("logical_session_id") else None
    assignment = db.get(TaskWeek, logical.assignment_id) if logical else db.get(TaskWeek, block["task_assignment_id"]) if block.get("task_assignment_id") else None
    return definition, assignment, bool(definition and (definition.payload.get("deleted_at") or assignment and assignment.payload.get("removed_from_week")))


def regeneration_blocks(db, blocks, settings, now=None):
    """Preserve started work and elapsed task reservations without inventing credit."""
    now = now or datetime.now(ZoneInfo(settings["timezone"]))
    result = []
    for block in saved_block_metadata(db, blocks):
        _, _, withdrawn = withdrawn_work(db, block)
        elapsed_history = withdrawn and datetime.fromisoformat(block["start"].replace("Z", "+00:00")) <= now
        elapsed_work = block.get("kind") in ("task", "project") and block.get("task_id") and datetime.fromisoformat(block["end"].replace("Z", "+00:00")) <= now
        explicit_meal_lock = block.get("kind") == "meal" and block.get("meal_id") and block.get("locked")
        if elapsed_history or elapsed_work or explicit_meal_lock or block.get("status") in ("completed", "in_progress") or block.get("locked") and block["kind"] not in ("class", "meal"):
            result.append({**block, "_withdrawn_history": True} if withdrawn else {**block, "_elapsed_work_history": True} if elapsed_work else block)
    return result


def restore_history_snapshots(db, blocks, previous):
    """After identity validation, derive trust only from server-owned records."""
    old = {block["id"]: block for block in previous}
    return [{**deepcopy(old[block["id"]]), "_withdrawn_history": True} if block["id"] in old and withdrawn_work(db, old[block["id"]])[2] else block for block in blocks]


def withdrawn_history_units(db, prepared, blocks):
    """Supply validation identities for fixed history; never create candidates.

    Original task and assignment snapshots provide duration/deadline policies;
    the actual saved block owns its historical venue and suitability evidence.
    Legacy units stay outside the weekly adapter, which requires logical IDs.
    """
    groups = {}
    for block in blocks:
        definition, assignment, withdrawn = withdrawn_work(db, block)
        if not withdrawn:
            continue
        sid = block.get("logical_session_id")
        identity = ("session:" + sid) if sid else block["task_id"]
        groups.setdefault(identity, {"definition": definition, "assignment": assignment, "blocks": []})["blocks"].append(block)
    existing = {unit["id"]: unit for unit in prepared["tasks"]}
    legacy = []
    for identity, group in groups.items():
        definition, assignment, own = group["definition"], group["assignment"], group["blocks"]
        block = own[0]
        snapshot = (assignment.payload.get("definition_snapshot") if assignment else None) or definition.payload.get("deletion_snapshot") or definition.payload
        metadata = {**deepcopy(snapshot), **deepcopy(assignment.payload.get("overrides", {}) if assignment else {}), **deepcopy(block)}
        metadata.pop("_withdrawn_history", None)
        minutes = sum(length(item["start"], item["end"]) for item in own if item.get("status") not in ("completed", "skipped"))
        minutes = minutes or sum(length(item["start"], item["end"]) for item in own)
        unit = {**metadata, "id": identity, "task_definition_id": definition.id, "status": "skipped", "history_only": True,
                "duration_minutes": minutes, "remaining_minutes": minutes, "dependencies": [], "exact_minutes": True,
                "splittable": snapshot.get("allow_splitting", snapshot.get("splittable", True)),
                "min_session_minutes": min(minutes, snapshot.get("min_chunk_minutes", snapshot.get("min_session_minutes", 1))),
                "max_session_minutes": max(minutes, snapshot.get("session_minutes", snapshot.get("max_session_minutes", minutes)))}
        if block.get("logical_session_id"):
            unit.update(logical_session_id=block["logical_session_id"], task_assignment_id=assignment.id)
            existing[identity] = unit
        else:
            legacy.append(unit)
    prepared["tasks"] = list(existing.values())
    return legacy


def validate_chunk_identity(db, blocks, old, date):
    before = {item["id"]: item for item in old}
    for block in blocks:
        fields = ("task_definition_id", "task_assignment_id", "logical_session_id", "chunk_index")
        prior = before.get(block["id"])
        if prior and any(block.get(field) != prior.get(field) for field in fields):
            fail("A planner chunk cannot change task, assignment, or logical session identity", 422)
        definition = db.get(TaskDefinition, block.get("task_id")) if block.get("task_id") else None
        history_fields = ("start", "end", "status", "locked", "location_id", "location_mode", "resolved_location_id", "location_override", "allow_alternative_locations", "alternative_location_ids", "location_requirements", "room", "building")
        defaults = {"locked": False, "location_override": False, "allow_alternative_locations": False, "alternative_location_ids": [], "location_requirements": [], "room": "", "building": ""}
        def historical_field(value, field):
            if field in ("start", "end"):
                return datetime.fromisoformat(value[field].replace("Z", "+00:00"))
            if field == "location_mode":
                return value.get(field, "required" if value.get("location_id") else "unspecified")
            return value.get(field, defaults.get(field))
        if withdrawn_work(db, block)[2] and (not prior or any(historical_field(block, field) != historical_field(prior, field) for field in history_fields)):
            fail("Deleted task history cannot introduce or change planned work", 422)
        sid = block.get("logical_session_id")
        if not sid:
            if definition and definition.scheduling_model == "weekly" and block.get("kind") in ("task", "project") and not prior:
                fail("Weekly work must reference an existing assigned logical session", 422)
            continue
        logical = db.get(LogicalSession, sid)
        assignment = db.get(TaskWeek, logical.assignment_id) if logical else None
        if assignment and assignment.payload.get("removed_from_week") and (not prior or any(block.get(field) != prior.get(field) for field in ("start", "end", "status"))):
            fail("Removed weekly work cannot be reintroduced through a saved plan", 422)
        if not logical or not assignment or assignment.task_definition_id != block.get("task_id") or block.get("task_definition_id") != assignment.task_definition_id or block.get("task_assignment_id") != assignment.id:
            fail("Planner chunk task/session/assignment references do not match", 422)
        if assignment.week_start != sunday_of(Date.fromisoformat(date)).isoformat() and not prior:
            fail("A weekly task chunk must stay in its assigned Sunday–Saturday week", 422)
        if not prior or block["start"] != prior["start"]:
            start = datetime.fromisoformat(block["start"].replace("Z", "+00:00"))
            if start.minute % 5:
                fail("New task chunk starts must use the five-minute grid", 422)


def planning_inputs(db, date, settings, preserved, include_inactive=False, now=None):
    """Read the same assignments, calendar source, and saved chunks for planning."""
    from . import calendar
    week = week_state(db, date)
    projects = {item.id: item.payload for item in db.scalars(select(Project))}
    effective = {item["task_definition_id"]: item["effective_definition"] for item in week["assignments"]}
    places = suitability.saved_places(db)
    activities = {item["id"]: item for item in calendar.activities_list(db)}
    first = Date.fromisoformat(date)
    last = first + timedelta(days=13)
    horizon_limit = first + timedelta(days=27)
    # One-week dates live in assignments, not recurring defaults. Read saved
    # overrides across the bounded horizon before deciding which future weeks
    # to forecast; this must not materialize recurring assignments or sessions.
    visible_definition_ids = {item["id"] for item in week["definitions"]}
    date_sources = [*week["definitions"], *effective.values()]
    date_sources.extend(row.payload.get("overrides", {}) for row in db.scalars(
        select(TaskWeek).where(TaskWeek.week_start >= week["week_start"],
                               TaskWeek.week_start <= horizon_limit.isoformat())
    ) if row.task_definition_id in visible_definition_ids and not row.payload.get("removed_from_week"))
    for item in date_sources:
        for field in ("deadline", "deadline_at", "due_at", "assessment_at"):
            if item.get(field):
                due = datetime.fromisoformat(item[field].replace("Z", "+00:00")).astimezone(ZoneInfo(settings["timezone"])).date()
                if first <= due <= horizon_limit:
                    last = max(last, due)
    events = calendar.occurrences_between(db, week["week_start"], last.isoformat(), settings)
    horizon_events = list(events)
    definitions = []
    for item in week["definitions"]:
        merged = {**item, **effective.get(item["id"], {})}
        related = activities.get(merged.get("related_activity_id"))
        related = {**calendar.enrich_related_context(db, related, events), "occurrences": [event for event in events if event["activity_id"] == related["id"]]} if related else None
        definitions.append(suitability.enrich({**merged, "_definition_status": item.get("status"), "related_activity": related, "project": projects.get(item["project_id"]), "schedule_inactive_project": include_inactive}, places))
    definition_ids = {item["id"] for item in definitions if item["scheduling_model"] == "weekly"}
    assignments = [item for item in week["assignments"] if item["task_definition_id"] in definition_ids]
    assignment_ids = {item["id"] for item in assignments}
    sessions = [item for item in week["sessions"] if item["assignment_id"] in assignment_ids]
    session_ids = {item["id"] for item in sessions}
    schedule_map = {row.date: row.payload for row in db.scalars(select(Schedule))}
    block_map = {item["id"]: item for value in schedule_map.values() for item in value.get("blocks", [])}
    preserved_ids = {item["id"] for item in preserved}
    chunks = [{**chunk_value(item), "locked": block_map.get(item.id, {}).get("locked", False), "preserve": item.id in preserved_ids or block_map.get(item.id, {}).get("status") == "in_progress"} for item in db.scalars(select(TaskChunk)) if item.logical_session_id in session_ids]
    zone = ZoneInfo(settings["timezone"])
    days, current = [], Date.fromisoformat(date)
    while current <= last:
        day = current.isoformat()
        start = datetime.fromisoformat(f"{day}T{settings['work_start']}").replace(tzinfo=zone)
        end = datetime.fromisoformat(f"{day}T{settings['work_end']}").replace(tzinfo=zone)
        configured_start = start
        if day == date and now is not None:
            instant = datetime.fromisoformat(now.replace("Z", "+00:00")) if isinstance(now, str) else now
            start = min(end, max(start, instant.astimezone(zone)))
        intervals = []
        events = calendar.occurrences_between(db, current, current, settings)
        commitments = list(events) + (list(preserved) if day == date else schedule_map.get(day, {}).get("blocks", []))
        # Flexible meals have no fixed occupied interval. Reserve their duration
        # conservatively, crediting meals already represented in saved blocks.
        meal_minutes = sum(item["duration_minutes"] for item in settings.get("meals", []) if item.get("enabled", True))
        represented_meals = sum(length(item["start"], item["end"]) for item in commitments if item.get("kind") == "meal" and item.get("status") != "skipped")
        awake_start = datetime.fromisoformat(f"{day}T{settings['wake_time']}").replace(tzinfo=zone)
        awake_end = datetime.fromisoformat(f"{day}T{settings['sleep_time']}").replace(tzinfo=zone)
        if settings["sleep_time"] == "00:00":
            awake_end += timedelta(days=1)
        outside_work = max(0, round(((configured_start - awake_start) + (awake_end - end)).total_seconds() / 60))
        # Only breakfast can reasonably consume morning room; dinner can use
        # evening room. Other meals retain a conservative work-capacity reserve.
        outside_meals = sum(item["duration_minutes"] for item in settings.get("meals", []) if item.get("enabled", True) and item["name"].strip().lower() in {"breakfast", "dinner"})
        meal_reserve = max(0, meal_minutes - represented_meals - min(outside_work, outside_meals))
        for item in commitments:
            if item.get("status") == "skipped":
                continue
            left = max(start.timestamp(), datetime.fromisoformat(item["start"].replace("Z", "+00:00")).timestamp())
            right = min(end.timestamp(), datetime.fromisoformat(item["end"].replace("Z", "+00:00")).timestamp())
            if right > left:
                intervals.append((left, right))
        occupied, cursor = 0, start.timestamp()
        for left, right in sorted(intervals):
            occupied += max(0, right - max(left, cursor))
            cursor = max(cursor, right)
        days.append({"date": day, "available_start": start.isoformat(), "capacity_minutes": max(0, round((end.timestamp() - start.timestamp() - occupied) / 60) - meal_reserve)})
        current += timedelta(days=1)
    legacy = [item for item in compatibility_tasks(db, settings) if item.get("scheduling_model") == "legacy"]
    forecast_assignments, forecast_sessions = [], []
    forecast_week = sunday_of(first)
    while forecast_week <= last:
        forecast = week_state(db, forecast_week.isoformat())
        for assignment in forecast["assignments"]:
            if assignment["task_definition_id"] not in definition_ids:
                continue
            effective_forecast = assignment["effective_definition"]
            related = activities.get(effective_forecast.get("related_activity_id"))
            related = {**calendar.enrich_related_context(db, related, horizon_events), "occurrences": [event for event in horizon_events if event["activity_id"] == related["id"]]} if related else None
            effective_forecast = suitability.enrich({**effective_forecast, "related_activity": related,
                "project": projects.get(effective_forecast.get("project_id")), "schedule_inactive_project": include_inactive}, places)
            forecast_assignments.append({**assignment, "effective_definition": effective_forecast})
        forecast_sessions.extend(forecast["sessions"])
        forecast_week += timedelta(days=7)
    return definitions, assignments, sessions, {"days": days, "chunks": chunks, "legacy_tasks": legacy, "timezone": settings["timezone"], "events": horizon_events, "horizon_start": date, "horizon_end": last.isoformat(), "forecast_only": True, "forecast_assignments": forecast_assignments, "forecast_sessions": forecast_sessions}


def validation_units(db, prepared, blocks, definitions, context):
    """Validate actual saved sessions independently of a new pacing forecast."""
    withdrawn_history_units(db, prepared, blocks)
    existing = {item["logical_session_id"]: item for item in prepared["tasks"]}
    definition_map = {item["id"]: item for item in definitions}
    for block in blocks:
        sid = block.get("logical_session_id")
        if not sid:
            continue
        if withdrawn_work(db, block)[2]:
            continue
        logical = db.get(LogicalSession, sid)
        assignment = db.get(TaskWeek, logical.assignment_id)
        definition = suitability.enrich({**definition_map.get(assignment.task_definition_id, definition_value(db.get(TaskDefinition, assignment.task_definition_id))), **assignment.payload.get("overrides", {})}, suitability.saved_places(db))
        reserved = sum(length(item["start"], item["end"]) for item in context["chunks"] if item["logical_session_id"] == sid and item["status"] not in ("completed", "skipped") and datetime.fromisoformat(item["start"].replace("Z", "+00:00")).astimezone(ZoneInfo(context["timezone"])).date().isoformat() != prepared["date"])
        remaining = max(0, logical.target_minutes - logical.completed_minutes - reserved)
        # Completed snapshots need identity validation, but consume no new work.
        if not remaining:
            remaining = length(block["start"], block["end"])
        existing[sid] = {**definition, **{key: existing[sid][key] for key in ("weekly_planned_minutes", "weekly_opportunity") if sid in existing and key in existing[sid]}, "id": "session:" + sid, "task_definition_id": assignment.task_definition_id, "task_assignment_id": assignment.id, "logical_session_id": sid, "kind": "project" if definition.get("project_id") else "academic", "status": "todo", "duration_minutes": remaining, "remaining_minutes": remaining, "splittable": definition["allow_splitting"], "min_session_minutes": min(remaining, definition["min_chunk_minutes"]), "max_session_minutes": remaining, "dependencies": [], "exact_minutes": True}
    prepared["tasks"] = list(existing.values())
    return prepared


def describe_weekly_exclusions(result, definitions, assignments):
    """Give the planner named, actionable reasons for context-based exclusions."""
    definition_map = {item["id"]: item for item in definitions}
    assignment_map = {item["id"]: item for item in assignments}
    exclusions = list(result.get("excluded_tasks", []))
    existing = {(item["task_id"], item.get("task_assignment_id")) for item in exclusions}
    for progress in result.get("weekly_progress", []):
        definition = definition_map.get(progress["task_definition_id"])
        assignment = assignment_map.get(progress["assignment_id"])
        if not definition or not assignment:
            continue
        progress["title"] = definition["title"]
        if not progress.get("excluded"):
            continue
        project = definition.get("project") or {}
        if assignment.get("status") in ("paused", "completed", "skipped"):
            reason = f"Weekly assignment is {assignment['status']}; automatic scheduling is excluded."
        elif definition.get("status") in ("paused", "archived", "completed"):
            reason = f"Task definition is {definition['status']}; automatic scheduling is excluded."
        elif project.get("status") in ("paused", "archived"):
            reason = f"Project {project.get('name', 'linked project')} is {project['status']}; include inactive projects explicitly to schedule this task."
        else:
            reason = "This weekly task is excluded by its current scheduling eligibility."
        progress["exclusion_reason"] = reason
        key = (definition["id"], assignment["id"])
        if key not in existing:
            exclusions.append({"task_id": definition["id"], "title": definition["title"], "task_assignment_id": assignment["id"], "project_id": definition.get("project_id"), "minutes": max(0, assignment.get("remaining_minutes", 0)), "reason": reason})
            existing.add(key)
    result["excluded_tasks"] = exclusions
    return result


def ensure_sessions(db, assignment):
    """Targets are soft metadata; solver-selected/logged sessions are real work."""


def remove_assignment(db, row):
    sessions = list(db.scalars(select(LogicalSession).where(LogicalSession.assignment_id == row.id)))
    ids = [item.id for item in sessions]
    chunks = list(db.scalars(select(TaskChunk).where(TaskChunk.logical_session_id.in_(ids)))) if ids else []
    if any(item.completed_minutes or item.status in ("in_progress", "completed") for item in sessions):
        fail("This week has started or completed work. Pause it to preserve history.")
    chunk_ids = {item.id for item in chunks}
    for schedule in db.scalars(select(Schedule)):
        own = [block for block in schedule.payload.get("blocks", []) if block.get("id") in chunk_ids]
        if any(block.get("locked") or block.get("status") in ("in_progress", "completed") for block in own):
            fail("This week has locked or started planner work. Preserve it or unlock unstarted work first.")
        if own:
            schedule.payload = {**schedule.payload, "blocks": [block for block in schedule.payload["blocks"] if block.get("id") not in chunk_ids]}
    for chunk in chunks:
        db.delete(chunk)
    db.flush()
    db.delete(row)
    db.flush()
    mark_stale(db, "Weekly task assignments changed. Regenerate to replan remaining work.", {row.week_start})


def withdraw_work(db, definition, rows, settings, deleted=False):
    """Cancel demand and pending work atomically; preserve recorded history."""
    now = datetime.now(ZoneInfo(settings["timezone"]))
    assignment_ids = {row.id for row in rows}
    sessions = list(db.scalars(select(LogicalSession).where(LogicalSession.assignment_id.in_(assignment_ids)))) if assignment_ids else []
    session_ids = {row.id for row in sessions}
    chunks = {row.id: row for row in db.scalars(select(TaskChunk).where(TaskChunk.logical_session_id.in_(session_ids)))} if session_ids else {}
    removed = set()
    for schedule in db.scalars(select(Schedule)):
        blocks = []
        for block in schedule.payload.get("blocks", []):
            matches = bool({block.get("task_definition_id"), block.get("task_id")} & {definition.id, definition.legacy_task_id} - {None}) if deleted else block.get("task_assignment_id") in assignment_ids or block.get("id") in chunks
            started = block.get("status") in ("completed", "in_progress", "skipped") or datetime.fromisoformat(block["start"].replace("Z", "+00:00")) <= now
            if matches and not started:
                removed.add(block["id"])
            else:
                blocks.append(block)
        if len(blocks) != len(schedule.payload.get("blocks", [])):
            schedule.payload = {**schedule.payload, "blocks": blocks, "status": "stale", "tasks_dirty": True}
    for key, chunk in chunks.items():
        if key in removed or chunk.status not in ("completed", "in_progress", "skipped") and not chunk.credited_minutes and datetime.fromisoformat(chunk.start.replace("Z", "+00:00")) > now:
            db.delete(chunk)
    db.flush()
    for session in sessions:
        if not session.completed_minutes and session.status == "todo" and not db.scalar(select(TaskChunk.id).where(TaskChunk.logical_session_id == session.id).limit(1)):
            session.status = "skipped"
    for row in rows:
        row.payload = {**row.payload, "status": "skipped", "removed_from_week": True, "definition_snapshot": row.payload.get("definition_snapshot", dict(definition.payload))}
    mark_stale(db, "Task work was removed. Regenerate to update remaining work.", None if deleted else {row.week_start for row in rows})


def delete_everywhere(db, row, settings):
    if row.payload.get("deleted_at"):
        return
    rows = list(db.scalars(select(TaskWeek).where(TaskWeek.task_definition_id == row.id)))
    withdraw_work(db, row, rows, settings, deleted=True)
    row.payload = {**row.payload, "deletion_snapshot": dict(row.payload), "status": "archived", "deleted_at": datetime.now(ZoneInfo("UTC")).isoformat(), "project_id": None, "related_activity_id": None, "location_id": None, "location_mode": "unspecified", "alternative_location_ids": [], "allow_alternative_locations": False}
    row.project_id, row.related_activity_id = None, None
    deleted_keys = {row.id, row.legacy_task_id} - {None}
    for other in db.scalars(select(TaskDefinition)):
        if deleted_keys.intersection(other.payload.get("dependencies", [])):
            other.payload = {**other.payload, "dependencies": [key for key in other.payload["dependencies"] if key not in deleted_keys]}
    for assignment in db.scalars(select(TaskWeek)):
        overrides = assignment.payload.get("overrides", {})
        if deleted_keys.intersection(overrides.get("dependencies", [])):
            assignment.payload = {**assignment.payload, "overrides": {**overrides, "dependencies": [key for key in overrides["dependencies"] if key not in deleted_keys]}}
    for entity in db.scalars(select(Entity).where(Entity.collection == "tasks")):
        if deleted_keys.intersection(entity.payload.get("dependencies", [])):
            entity.payload = {**entity.payload, "dependencies": [key for key in entity.payload["dependencies"] if key not in deleted_keys]}
    alias = db.get(Entity, ("tasks", row.legacy_task_id)) if row.legacy_task_id else None
    if alias:
        from .projects import set_task_project
        set_task_project(db, alias.id, None)
        alias.payload = {**alias.payload, "status": "skipped", "remaining_minutes": 0, "project_id": None, "location_id": None, "location_mode": "unspecified", "alternative_location_ids": [], "allow_alternative_locations": False}


def create_router(session_dependency, settings_of):
    router = APIRouter(prefix="/api", tags=["weekly tasks"])

    @router.get("/task-definitions")
    def list_definitions(db: Session = Depends(session_dependency)):
        return definitions_list(db)

    @router.get("/task-week")
    def read_week(week_start: Date, db: Session = Depends(session_dependency)):
        return week_state(db, week_start.isoformat())

    def save_definition(value, key, db, old=None):
        payload = normalize_times(value.model_dump(mode="json"), settings_of(db))
        if old:
            payload = location_edit(payload, old.payload, value.model_fields_set)
            for field, default in (("min_sessions_per_day", 1), ("max_sessions_per_day", None), ("course", ""), ("status", "active"), ("project_id", None), ("related_activity_id", None)):
                if field not in value.model_fields_set:
                    payload[field] = old.payload.get(field, default)
        if payload.get("recurrence") and not payload["recurrence"].get("start_week"):
            payload["recurrence"]["start_week"] = (old.payload.get("recurrence") or {}).get("start_week") if old else None
            payload["recurrence"]["start_week"] = payload["recurrence"]["start_week"] or current_week(settings_of(db))
        try:
            task_schemas.TaskDefinition.model_validate(payload)
        except ValueError as error:
            fail(str(error), 422)
        if value.id and value.id != key:
            fail("Task identity cannot be changed", 422)
        payload["id"] = key
        validate_definition_references(db, payload, key)
        if old:
            converting = bool(payload.get("recurrence") and not old.payload.get("recurrence"))
            if converting and old.scheduling_model == "legacy":
                source = db.get(Entity, ("tasks", old.legacy_task_id)) if old.legacy_task_id else None
                if source:
                    target = source.payload["duration_minutes"]
                    done = target - source.payload["remaining_minutes"]
                    if done:
                        week = current_week(settings_of(db))
                        assignment = TaskWeek(id=str(uuid4()), task_definition_id=key, week_start=week, payload={"session_minutes": target, "min_sessions_per_week": payload["min_sessions_per_week"], "status": "todo", "notes": "Prior finite completion retained during recurring conversion.", "source": "recurring", "overrides": {}})
                        db.add(assignment)
                        db.flush()
                        db.add(LogicalSession(id=str(uuid4()), assignment_id=assignment.id, index=0, target_minutes=target, completed_minutes=done, baseline_completed_minutes=done, status="completed" if done == target else "in_progress"))
                old.scheduling_model = "weekly"
            if converting:
                for assignment in db.scalars(select(TaskWeek).where(TaskWeek.task_definition_id == key)):
                    previous = dict(assignment.payload)
                    inherited = [] if previous.get("legacy_finite") or previous.get("source") == "recurring" else ["session_minutes", "min_sessions_per_week"]
                    assignment.payload = {**{name: item for name, item in previous.items() if name != "legacy_finite"}, "source": "recurring", "definition_snapshot": dict(old.payload), "overridden_fields": previous.get("overridden_fields", inherited)}
            old.payload, old.project_id, old.related_activity_id = payload, payload["project_id"], payload["related_activity_id"]
            mark_stale(db, "Task definition changed. Regenerate to apply its current constraints and context.")
            row = old
            sync_legacy_alias(db, row)
        else:
            row = TaskDefinition(id=key, payload=payload, project_id=payload["project_id"], related_activity_id=payload["related_activity_id"], scheduling_model="weekly")
            db.add(row)
            if payload.get("recurrence"):
                mark_stale(db, "A recurring task was added. Regenerate to include its weekly work.")
        db.commit()
        return {**definition_value(row), "association_summary": association_summary(db, row)}

    @router.post("/task-definitions", status_code=201)
    def add_definition(value: task_schemas.TaskDefinition, db: Session = Depends(session_dependency)):
        if value.id:
            fail("New task definitions receive an ID from the server", 422)
        return save_definition(value, str(uuid4()), db)

    @router.put("/task-definitions/{key}")
    def update_definition(key: str, value: task_schemas.TaskDefinition, db: Session = Depends(session_dependency)):
        old = db.get(TaskDefinition, key)
        if not old or old.payload.get("deleted_at"):
            fail("Task definition not found", 404)
        return save_definition(value, key, db, old)

    @router.delete("/task-definitions/{key}", status_code=204)
    def delete_definition(key: str, delete_assignments: bool = Query(default=False), db: Session = Depends(session_dependency)):
        row = db.get(TaskDefinition, key)
        if not row:
            fail("Task definition not found", 404)
        assignments = list(db.scalars(select(TaskWeek).where(TaskWeek.task_definition_id == key)))
        if assignments and not delete_assignments:
            fail("This task has weekly assignments. Confirm delete everywhere to cancel its pending work and retain history.")
        delete_everywhere(db, row, settings_of(db))
        db.commit()
        return Response(status_code=204)

    @router.post("/task-definitions/{key}/stop-repeating")
    def stop_repeating(key: str, value: task_schemas.StopRepeating, db: Session = Depends(session_dependency)):
        row = db.get(TaskDefinition, key)
        if not row or row.payload.get("deleted_at"):
            fail("Task definition not found", 404)
        recurrence = row.payload.get("recurrence")
        if not recurrence:
            fail("This task does not repeat", 422)
        cutoff = value.from_week.isoformat()
        if cutoff < current_week(settings_of(db)):
            fail("Stop repeating from the current week or a future week to preserve historical recurrence", 422)
        rows = list(db.scalars(select(TaskWeek).where(TaskWeek.task_definition_id == key, TaskWeek.week_start >= cutoff)))
        rows = [item for item in rows if item.payload.get("source") == "recurring"]
        withdraw_work(db, row, rows, settings_of(db))
        row.payload = {**row.payload, "recurrence": {**recurrence, "stopped_from_week": cutoff}}
        mark_stale(db, "Task repetition stopped. Regenerate to apply its cutoff.")
        db.commit()
        return {**definition_value(row), "association_summary": association_summary(db, row)}

    def save_week(value, db, row=None):
        definition = db.get(TaskDefinition, value.task_definition_id)
        if not definition or definition.payload.get("deleted_at"):
            fail("Task definition no longer exists", 422)
        if row and (row.task_definition_id != definition.id or row.week_start != value.week_start.isoformat()):
            fail("Assignment identity and week cannot change; assign the definition to another week instead", 422)
        task_recurrence.validate_overrides(value.overrides)
        if {"location_id", "location_mode", "allow_alternative_locations", "alternative_location_ids"}.intersection(value.overrides):
            old_effective = task_recurrence.effective_value(db, row, definition)[1] if row else definition.payload
            edited = location_edit({**old_effective, **value.overrides}, old_effective, value.overrides)
            for field, default in (("room", ""), ("allow_alternative_locations", False), ("alternative_location_ids", [])):
                if field not in value.overrides and edited.get(field, default) != old_effective.get(field, default):
                    value.overrides[field] = edited.get(field, default)
        base = {name: item for name, item in definition_value(definition).items() if name in task_schemas.TaskDefinition.model_fields}
        # Dates are allowed on explicit copies, but recurring defaults stay date-free.
        effective = {**base, **value.overrides, "recurrence": None, "session_minutes": value.session_minutes or (row.payload["session_minutes"] if row else definition.payload["session_minutes"])}
        try:
            effective = task_schemas.TaskDefinition.model_validate(effective).model_dump(mode="json")
        except ValueError as error:
            fail(str(error), 422)
        validate_definition_references(db, effective, definition.id)
        overrides = normalize_times({field: effective[field] for field in value.overrides}, settings_of(db))
        changed = set((row.payload if row else {}).get("overridden_fields", []))
        changed.update(field for field in ("session_minutes", "min_sessions_per_week") if getattr(value, field) is not None)
        payload = {**(row.payload if row else {}), "session_minutes": value.session_minutes or (row.payload["session_minutes"] if row else definition.payload["session_minutes"]), "min_sessions_per_week": value.min_sessions_per_week if value.min_sessions_per_week is not None else row.payload["min_sessions_per_week"] if row else definition.payload["min_sessions_per_week"], "status": value.status, "notes": value.notes, "overrides": overrides, "overridden_fields": sorted(changed), "is_virtual": False}
        payload.pop("removed_from_week", None)
        payload["allow_inactive"] = value.allow_inactive if value.allow_inactive is not None else payload.get("allow_inactive", False)
        if task_recurrence.applies(definition, value.week_start.isoformat()):
            payload["source"] = "recurring"
            payload.setdefault("definition_snapshot", dict(definition.payload))
        elif definition.payload.get("recurrence"):
            payload["source"] = "explicit"
        switching_legacy = definition.scheduling_model == "legacy"
        if switching_legacy and db.scalar(select(TaskWeek).where(TaskWeek.task_definition_id == definition.id).limit(1)):
            switching_legacy = False
        if row:
            row.payload = payload
        else:
            if db.scalar(select(TaskWeek).where(TaskWeek.task_definition_id == definition.id, TaskWeek.week_start == value.week_start.isoformat())):
                fail("This task is already assigned to that week")
            key = task_recurrence.recurring_id(definition.id, value.week_start.isoformat()) if task_recurrence.applies(definition, value.week_start.isoformat()) else str(uuid4())
            row = TaskWeek(id=key, task_definition_id=definition.id, week_start=value.week_start.isoformat(), payload=payload)
            db.add(row)
        definition.scheduling_model = "weekly"
        db.flush()
        if switching_legacy:
            source = db.get(Entity, ("tasks", definition.legacy_task_id))
            if source:
                target = source.payload["duration_minutes"]
                completed = target - source.payload["remaining_minutes"]
                if payload["session_minutes"] != target:
                    fail("Assign the existing finite session length first to preserve its completed work; edit the canonical definition explicitly to change the estimate", 422)
                row.payload = {**row.payload, "legacy_finite": True}
                db.add(LogicalSession(id=str(uuid4()), assignment_id=row.id, index=0, target_minutes=target, completed_minutes=completed, baseline_completed_minutes=completed, status="completed" if completed == target else "in_progress" if completed else "todo"))
        ensure_sessions(db, row)
        mark_stale(db, "Weekly task assignments changed. Regenerate to replan remaining work.", {row.week_start})
        db.commit()
        return next(item for item in week_state(db, row.week_start)["assignments"] if item["id"] == row.id)

    @router.post("/task-weeks/copy")
    def copy_week(value: task_schemas.CopyTaskWeek, db: Session = Depends(session_dependency)):
        source, target = value.source_week.isoformat(), value.target_week.isoformat()
        if source == target:
            fail("Choose a different destination week", 422)
        original = week_state(db, source)
        destination = week_state(db, target)
        existing = {item["task_definition_id"] for item in destination["assignments"]}
        selected = set(value.definition_ids) if value.definition_ids is not None else None
        copied, skipped = [], []
        seen = set()
        for assignment in original["assignments"]:
            key = assignment["task_definition_id"]
            if selected is not None and key not in selected:
                continue
            seen.add(key)
            definition = db.get(TaskDefinition, key)
            if assignment.get("source") == "recurring" or task_recurrence.applies(definition, source):
                skipped.append({"task_definition_id": key, "title": definition.payload["title"], "reason": "Recurring tasks already apply automatically and are excluded from explicit copying."})
                continue
            if task_recurrence.applies(definition, target):
                skipped.append({"task_definition_id": key, "title": definition.payload["title"], "reason": "This task repeats automatically in the destination week; copying would duplicate its recurring work."})
                continue
            if key in existing:
                skipped.append({"task_definition_id": key, "title": definition.payload["title"], "reason": "This task is already assigned in the destination week; it was left unchanged."})
                continue
            if db.scalar(select(TaskWeek).where(TaskWeek.task_definition_id == key, TaskWeek.week_start == target)):
                skipped.append({"task_definition_id": key, "title": definition.payload["title"], "reason": "The destination has a removed assignment with preserved history. Restore it explicitly before copying."})
                continue
            effective = assignment["effective_definition"]
            overrides = {field: effective[field] for field in task_recurrence.OVERRIDE_FIELDS if field in effective}
            # Assignment progress and definition lifecycle are never copied.
            overrides.pop("status", None)
            if value.deadline_policy == "shift":
                overrides = task_recurrence.shifted_dates(overrides, (value.target_week - value.source_week).days, settings_of(db)["timezone"])
            payload = {"session_minutes": assignment["session_minutes"], "min_sessions_per_week": assignment["min_sessions_per_week"], "status": "todo", "notes": assignment.get("notes", ""), "overrides": overrides, "source": "copy", "copied_from_week": source, "deadline_policy": value.deadline_policy}
            row = TaskWeek(id=f"preview:{key}:{target}" if value.preview else str(uuid4()), task_definition_id=key, week_start=target, payload=payload)
            copied.append({**assignment_value(row, [], []), "source": "copy", "is_virtual": value.preview, "min_sessions_per_day": effective.get("min_sessions_per_day", 1), "max_sessions_per_day": effective.get("max_sessions_per_day"), "effective_definition": {**definition_value(definition), **overrides, "session_minutes": payload["session_minutes"], "min_sessions_per_week": payload["min_sessions_per_week"]}})
            if not value.preview:
                db.add(row)
            existing.add(key)
        if selected:
            for key in sorted(selected - seen):
                skipped.append({"task_definition_id": key, "reason": "This task has no assignment in the selected source week."})
        if not value.preview:
            if copied:
                mark_stale(db, "Explicit tasks copied into this week. Regenerate to schedule the new assignments.", {target})
            db.commit()
        return {"copied": copied, "skipped": skipped, "week": destination if value.preview else week_state(db, target), "preview": value.preview, "source_week": source, "target_week": target, "deadline_policy": value.deadline_policy}

    @router.post("/task-weeks", status_code=201)
    def add_week(value: task_schemas.TaskWeek, db: Session = Depends(session_dependency)):
        existing = db.scalar(select(TaskWeek).where(TaskWeek.task_definition_id == value.task_definition_id, TaskWeek.week_start == value.week_start.isoformat()))
        return save_week(value, db, existing if existing and existing.payload.get("removed_from_week") else None)

    @router.put("/task-weeks/{key}")
    def update_week(key: str, value: task_schemas.TaskWeek, db: Session = Depends(session_dependency)):
        row = task_recurrence.resolve_assignment(db, key)
        if not row:
            fail("Weekly assignment not found", 404)
        return save_week(value, db, row)

    @router.delete("/task-weeks/{key}", status_code=204)
    def delete_week(key: str, db: Session = Depends(session_dependency)):
        row = task_recurrence.resolve_assignment(db, key)
        if not row:
            fail("Weekly assignment not found", 404)
        definition = db.get(TaskDefinition, row.task_definition_id)
        withdraw_work(db, definition, [row], settings_of(db))
        db.commit()
        return Response(status_code=204)

    @router.put("/task-sessions/{key}")
    def save_session(key: str, value: task_schemas.SessionProgress, db: Session = Depends(session_dependency)):
        from . import history, work_confirmation
        from sqlalchemy import text
        db.execute(text("BEGIN IMMEDIATE"))
        logical = db.get(LogicalSession, key)
        if not logical:
            fail("Logical session not found", 404)
        previous_baseline = logical.baseline_completed_minutes
        chunks = list(db.scalars(select(TaskChunk).where(TaskChunk.logical_session_id == key)))
        previous_schedules = {row.id: deepcopy(row.payload) for row in db.scalars(select(Schedule))
                              if any(item.get("logical_session_id") == key or item.get("id") in {chunk.id for chunk in chunks} for item in row.payload.get("blocks", []))}
        now = datetime.now(ZoneInfo(settings_of(db)["timezone"]))
        if value.status == "completed":
            for chunk in chunks:
                if work_confirmation.instant(chunk.end) > now:
                    fail("A logical session with future scheduled work cannot be marked completed. Confirm elapsed work blocks individually.", 422)
        completed = logical.target_minutes if value.status == "completed" else 0 if value.status == "todo" and value.completed_minutes is None else value.completed_minutes if value.completed_minutes is not None else logical.completed_minutes
        if completed > logical.target_minutes:
            fail("Completed minutes cannot exceed the logical session", 422)
        logical.completed_minutes = completed
        credited = sum(item.credited_minutes for item in db.scalars(select(TaskChunk).where(TaskChunk.logical_session_id == key)))
        if value.status not in ("completed", "todo") and completed < credited:
            fail("Undo credited planner chunks before reducing total completed minutes below their credit", 422)
        logical.baseline_completed_minutes = max(0, completed - credited)
        logical.status = "completed" if completed == logical.target_minutes else "paused" if value.status == "paused" else "in_progress" if completed else "todo"
        if value.status in ("completed", "todo"):
            ids = {item.id for item in chunks}
            for chunk in chunks:
                chunk.status = value.status
                chunk.credited_minutes = length(chunk.start, chunk.end) if value.status == "completed" else 0
            if value.status == "todo":
                logical.baseline_completed_minutes = 0
            else:
                logical.baseline_completed_minutes = max(0, logical.target_minutes - sum(chunk.credited_minutes for chunk in chunks))
            for schedule in db.scalars(select(Schedule)):
                if any(item["id"] in ids for item in schedule.payload.get("blocks", [])):
                    blocks = deepcopy(schedule.payload["blocks"])
                    for before, after in zip(schedule.payload["blocks"], blocks):
                        if before["id"] in ids:
                            work_confirmation.stamp(before, after, value.status == "completed", now)
                            after["status"] = value.status
                    schedule.payload = {**schedule.payload, "blocks": blocks}
            db.flush()
            reconcile_session_credit(db, key)
        assignment = db.get(TaskWeek, logical.assignment_id)
        mark_stale(db, "Logical session progress changed. Regenerate to update remaining work.", {assignment.week_start})
        db.flush()
        work_confirmation.refresh_projections(db, settings_of(db), assignment.week_start)
        for schedule_id, previous in previous_schedules.items():
            history.sync_schedule(db, db.get(Schedule, schedule_id), settings_of(db), previous)
        history.sync_manual_session(db, logical, settings_of(db),
            record_new=value.status == "completed" or value.completed_minutes is not None, previous_baseline=previous_baseline)
        history.sync_undated(db, settings_of(db))
        db.commit()
        assignment = db.get(TaskWeek, logical.assignment_id)
        return session_value(logical, assignment.task_definition_id, chunks)

    @router.post("/task-sessions", status_code=201)
    def log_session(value: task_schemas.LogSession, db: Session = Depends(session_dependency)):
        from . import history
        assignment = task_recurrence.resolve_assignment(db, value.assignment_id)
        if not assignment:
            fail("Weekly assignment not found", 404)
        definition = db.get(TaskDefinition, assignment.task_definition_id)
        if assignment.payload.get("removed_from_week") or definition.payload.get("deleted_at"):
            fail("Restore the weekly assignment before logging new work", 409)
        target = assignment.payload["session_minutes"]
        completed = value.completed_minutes if value.completed_minutes is not None else target
        if completed > target:
            fail("Completed minutes cannot exceed one logical session", 422)
        index = max((item.index for item in db.scalars(select(LogicalSession).where(LogicalSession.assignment_id == assignment.id))), default=-1) + 1
        logical = LogicalSession(id=str(uuid4()), assignment_id=assignment.id, index=index, target_minutes=target, completed_minutes=completed, baseline_completed_minutes=completed, status="completed" if completed == target else "in_progress")
        db.add(logical)
        db.flush()
        history.sync_manual_session(db, logical, settings_of(db))
        history.sync_undated(db, settings_of(db))
        mark_stale(db, "An actual session was logged. Regenerate to update remaining weekly work.", {assignment.week_start})
        db.commit()
        return session_value(logical, assignment.task_definition_id)

    return router
