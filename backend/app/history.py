"""Independent user-requested schedule snapshots and explicit actual-work history.

Only explicit planner actions synchronize an attached snapshot. Library edits,
withdrawals and display refreshes never rewrite archived names or context.
"""
from copy import deepcopy
from datetime import date as Date, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field
from sqlalchemy import select, text

from . import exports, schemas, task_library, work_confirmation
from .database import Activity, CompletedWork, Entity, LogicalSession, Project, Schedule, ScheduleArchive, TaskChunk, TaskDefinition, TaskWeek


class ArchiveSave(schemas.Model):
    schedule_id: str = Field(min_length=1, max_length=80)
    new_version: bool = Field(default=False, strict=True)


def now_stamp():
    return datetime.now(ZoneInfo("UTC")).isoformat()


def revision(schedule):
    return schedule.payload.get("schedule_revision_id") or f"legacy:{schedule.id}"


def attached_archive(db, schedule):
    return db.scalar(select(ScheduleArchive).where(ScheduleArchive.source_schedule_id == schedule.id,
        ScheduleArchive.source_revision_id == revision(schedule), ScheduleArchive.attached == 1))


def schedule_view(db, schedule, payload=None):
    archive = attached_archive(db, schedule)
    return {**(schedule.payload if payload is None else payload), "schedule_revision_id": revision(schedule),
            "archive_id": archive.id if archive else None, "archive_updated_at": archive.updated_at if archive else None}


def snapshot_context(db, settings, previous=None):
    """Freeze existing entity values; add metadata only for newly referenced IDs."""
    previous = previous or {}
    result = {"timezone": previous.get("timezone", settings["timezone"])}
    for key, model in (("locations", Entity), ("task_definitions", TaskDefinition), ("projects", Project), ("activities", Activity)):
        query = select(model)
        if model is Entity:
            query = query.where(Entity.collection == "locations")
        values = {row.id: {**deepcopy(row.payload), "id": row.id} for row in db.scalars(query)}
        values.update({item["id"]: deepcopy(item) for item in previous.get(key, [])})
        result[key] = list(values.values())
    return result


def snapshot_block(db, block, context, previous=None):
    result = deepcopy(block)
    definitions = {item["id"]: item for item in context["task_definitions"]}
    projects = {item["id"]: item for item in context["projects"]}
    activities = {item["id"]: item for item in context["activities"]}
    places = {item["id"]: item for item in context["locations"]}
    definition = definitions.get(block.get("task_definition_id") or block.get("task_id"))
    if not definition and block.get("task_id"):
        row = db.scalar(select(TaskDefinition).where(TaskDefinition.legacy_task_id == block["task_id"]))
        definition = definitions.get(row.id) if row else None
    definition = deepcopy(definition) if definition else None
    if definition and definition.get("deletion_snapshot"):
        definition = {**definition["deletion_snapshot"], "id": definition["id"]}
    project = projects.get(block.get("project_id") or (definition or {}).get("project_id"))
    activity = activities.get(block.get("activity_id") or (definition or {}).get("related_activity_id"))
    place = places.get(block.get("resolved_location_id") or block.get("location_id"))
    result.update(task_snapshot=definition, project_snapshot=deepcopy(project), activity_snapshot=deepcopy(activity),
                  location_snapshot=deepcopy(place), location_label=exports.location_label(block, places))
    if not result.get("description"):
        result["description"] = (definition or activity or {}).get("description", "")
    if previous:
        # A mutable active plan may change title/description after library edits.
        # Preserve its archived presentation; only operational fields follow it.
        for key in ("title", "description", "course", "building", "room", "related_entity", "related_entity_context",
                    "task_snapshot", "project_snapshot", "activity_snapshot"):
            if key in previous:
                result[key] = deepcopy(previous[key])
        if all(block.get(key) == previous.get(key) for key in ("location_id", "resolved_location_id", "location_mode", "origin_id", "destination_id", "building", "room")):
            result["location_snapshot"] = deepcopy(previous.get("location_snapshot"))
            result["location_label"] = previous.get("location_label", "")
    return result


def snapshot(db, schedule, settings, previous=None):
    value = deepcopy(schedule.payload)
    previous = previous or {}
    context = snapshot_context(db, settings, previous.get("snapshot_context"))
    old_blocks = {item["id"]: item for item in previous.get("blocks", [])}
    value["blocks"] = [snapshot_block(db, block, context, old_blocks.get(block["id"])) for block in value.get("blocks", [])]
    referenced = {"locations": set(), "task_definitions": set(), "projects": set(), "activities": set()}
    for block in value["blocks"]:
        referenced["locations"].update(block.get(field) for field in ("location_id", "resolved_location_id", "origin_id", "destination_id"))
        for collection, field in (("task_definitions", "task_snapshot"), ("projects", "project_snapshot"), ("activities", "activity_snapshot")):
            if block.get(field):
                referenced[collection].add(block[field].get("id"))
    for collection, ids in referenced.items():
        context[collection] = [item for item in context[collection] if item["id"] in ids]
    value["snapshot_context"] = context
    value["schedule_revision_id"] = revision(schedule)
    if previous.get("archive_version_number"):
        value["archive_version_number"] = previous["archive_version_number"]
    return value


def freeze_revision(db, schedule):
    current = attached_archive(db, schedule)
    if current:
        current.attached = 0
    return str(uuid4())


def archive_value(row):
    blocks = row.payload.get("blocks", [])
    work = [item for item in blocks if item.get("kind") in {"task", "project"}]
    completed = [item for item in work if item.get("status") == "completed" and item.get("completion_verified") and item.get("completion_confirmed_at")]
    return {"id": row.id, "source_schedule_id": row.source_schedule_id, "source_revision_id": row.source_revision_id,
            "date": row.date, "created_at": row.created_at, "updated_at": row.updated_at, "attached": bool(row.attached),
            "version_number": row.payload.get("archive_version_number", 1),
            "workload_level": row.payload.get("workload_level"), "mode": row.payload.get("mode"),
            "block_count": len(blocks), "completed_count": len(completed), "completed_minutes": sum(minutes(item) for item in completed),
            "total_minutes": sum(minutes(item) for item in work), "payload": row.payload}


def minutes(block):
    try:
        return max(0, round((datetime.fromisoformat(block["end"]) - datetime.fromisoformat(block["start"])).total_seconds() / 60))
    except (KeyError, TypeError, ValueError):
        return 0


def completion_payload(db, schedule, block, settings, frozen=None):
    context = snapshot_context(db, settings, (frozen or {}).get("snapshot_context"))
    before = next((item for item in (frozen or {}).get("blocks", []) if item["id"] == block["id"]), None)
    saved = snapshot_block(db, block, context, before)
    chunk = db.get(TaskChunk, block["id"])
    logical_id = block.get("logical_session_id") or (chunk.logical_session_id if chunk else None)
    logical = db.get(LogicalSession, logical_id) if logical_id else None
    assignment_id = block.get("task_assignment_id") or (logical.assignment_id if logical else None)
    assignment = db.get(TaskWeek, assignment_id) if assignment_id else None
    task = saved.get("task_snapshot") or {}
    return {"source_type": "scheduled_block", "title": saved["title"], "description": saved.get("description", ""),
        "category": task.get("task_type", "project_work" if block.get("kind") == "project" else "academic"),
        "scheduled_date": schedule.date, "scheduled_start": block["start"], "scheduled_end": block["end"],
        "completed_minutes": minutes(block), "task_definition_id": task.get("id") or block.get("task_definition_id") or block.get("task_id"),
        "task_assignment_id": assignment.id if assignment else block.get("task_assignment_id"),
        "logical_session_id": logical.id if logical else block.get("logical_session_id"),
        "logical_target_minutes": logical.target_minutes if logical else None,
        "logical_completed_minutes": logical.completed_minutes if logical else None,
        "logical_session_complete": logical.completed_minutes >= logical.target_minutes if logical else False,
        "week_start": assignment.week_start if assignment else None,
        "assignment_source": assignment.payload.get("source", "manual") if assignment else None,
        "project_title": (saved.get("project_snapshot") or {}).get("name"),
        "related_activity_title": (saved.get("activity_snapshot") or {}).get("title"),
        "location_label": saved.get("location_label", ""), "block": saved,
        "task_snapshot": saved.get("task_snapshot"), "project_snapshot": saved.get("project_snapshot"),
        "location_snapshot": saved.get("location_snapshot"), "workload_level": schedule.payload.get("workload_level")}


def sync_completions(db, schedule, settings, frozen=None, allow_reversal=True):
    """Capture only explicit evidence, independently of task/archived-row lifetimes."""
    existing = {row.source_block_id: row for row in db.scalars(select(CompletedWork).where(CompletedWork.source_schedule_id == schedule.id))}
    for block in schedule.payload.get("blocks", []):
        row = existing.get(block["id"])
        verified = block.get("status") == "completed" and block.get("completion_verified") is True and block.get("completion_confirmed_at")
        if verified:
            confirmed = block["completion_confirmed_at"]
            try:
                instant = datetime.fromisoformat(confirmed.replace("Z", "+00:00"))
                if instant.tzinfo is None:
                    continue
            except (TypeError, ValueError):
                continue
            value = completion_payload(db, schedule, block, settings, frozen)
            if row:
                # Keep original display metadata after task/library mutations.
                if row.reopened_at or not row.confirmed_at:
                    row.confirmed_at, row.reopened_at = confirmed, None
                saved_block = deepcopy(row.payload.get("block") or value["block"])
                for field in ("start", "end", "status", "completion_confirmed_at", "completion_previous_status", "completion_verified", "completion_remaining_minutes_delta"):
                    if field in block:
                        saved_block[field] = block[field]
                    else:
                        saved_block.pop(field, None)
                row.payload = {**row.payload, "source_type": "scheduled_block", "block": saved_block,
                    **{key: value[key] for key in ("completed_minutes", "scheduled_start", "scheduled_end", "logical_target_minutes", "logical_completed_minutes", "logical_session_complete")}}
            else:
                db.add(CompletedWork(id=str(uuid4()), source_schedule_id=schedule.id, source_block_id=block["id"],
                    date=schedule.date, confirmed_at=confirmed, reopened_at=None, payload=value))
        elif row and not row.reopened_at and allow_reversal and block.get("status") != "completed":
            row.reopened_at = now_stamp()


def sync_schedule(db, schedule, settings, previous=None):
    archive = attached_archive(db, schedule)
    frozen = archive.payload if archive else None
    sync_completions(db, schedule, settings, frozen)
    if archive:
        value = snapshot(db, schedule, settings, frozen)
        old_active = {item["id"]: item for item in (previous or schedule.payload).get("blocks", [])}
        current = {item["id"]: item for item in schedule.payload.get("blocks", [])}
        fresh = {item["id"]: item for item in value["blocks"]}
        merged = []
        for archived in frozen.get("blocks", []):
            key = archived["id"]
            if key not in old_active:
                # A background definition withdrawal may already have removed
                # this item from active planning. Its archive is independent.
                merged.append(deepcopy(archived))
            elif key in current:
                changed = {field for field in set(old_active[key]) | set(current[key]) if old_active[key].get(field) != current[key].get(field)}
                updated = deepcopy(archived)
                for field in changed:
                    if field in current[key]:
                        updated[field] = deepcopy(current[key][field])
                    else:
                        updated.pop(field, None)
                if changed.intersection({"location_id", "resolved_location_id", "location_mode", "origin_id", "destination_id", "building", "room"}):
                    for field in ("location_snapshot", "location_label"):
                        updated[field] = fresh[key][field]
                merged.append(updated)
        archived_ids = {item["id"] for item in frozen.get("blocks", [])}
        merged.extend(item for item in value["blocks"] if item["id"] not in archived_ids)
        value["blocks"] = sorted(merged, key=lambda item: item["start"])
        archive.payload = value
        archive.updated_at = now_stamp()
    sync_undated(db, settings)


def backfill_completions(db, settings):
    for schedule in db.scalars(select(Schedule)):
        sync_completions(db, schedule, settings, allow_reversal=False)
    sync_undated(db, settings)


def sync_manual_session(db, logical, settings, *, record_new=True, previous_baseline=0):
    """Persist a new explicitly logged manual amount without dating old baselines."""
    row = db.scalar(select(CompletedWork).where(CompletedWork.source_schedule_id == "", CompletedWork.source_block_id == logical.id))
    amount = logical.baseline_completed_minutes
    if not amount:
        if row:
            row.reopened_at = row.reopened_at or now_stamp()
            row.payload = {**row.payload, "undated_baseline_minutes": 0}
        return
    if not row and not record_new:
        return
    if row:
        undated = min(amount, row.payload.get("undated_baseline_minutes", 0))
        credited = amount - undated
        row.payload = {**row.payload, "completed_minutes": credited, "undated_baseline_minutes": undated}
        if row.reopened_at and credited:
            row.reopened_at, row.confirmed_at = None, now_stamp()
        elif not credited:
            row.reopened_at = row.reopened_at or now_stamp()
        return
    undated = min(amount, previous_baseline)
    if amount <= undated:
        return
    assignment = db.get(TaskWeek, logical.assignment_id)
    task = db.get(TaskDefinition, assignment.task_definition_id)
    definition = deepcopy(task.payload.get("deletion_snapshot") or task.payload)
    project = db.get(Project, task.project_id) if task.project_id else None
    activity = db.get(Activity, task.related_activity_id) if task.related_activity_id else None
    location = db.get(Entity, ("locations", definition["location_id"])) if definition.get("location_id") else None
    timestamp = now_stamp()
    payload = {"source_type": "manual_session", "title": definition["title"], "description": definition.get("description", ""),
        "category": definition.get("task_type", "academic"), "completed_minutes": amount - undated, "undated_baseline_minutes": undated,
        "scheduled_date": None, "scheduled_start": None, "scheduled_end": None,
        "task_definition_id": task.id, "task_assignment_id": assignment.id, "logical_session_id": logical.id,
        "logical_target_minutes": logical.target_minutes, "logical_completed_minutes": logical.completed_minutes,
        "logical_session_complete": logical.completed_minutes >= logical.target_minutes, "week_start": assignment.week_start,
        "assignment_source": assignment.payload.get("source", "manual"), "project_title": project.payload.get("name") if project else None,
        "related_activity_title": activity.payload.get("title") if activity else None,
        "location_label": location.payload.get("name", "") if location else "", "block": None,
        "task_snapshot": definition, "project_snapshot": deepcopy(project.payload) if project else None,
        "location_snapshot": deepcopy(location.payload) if location else None, "workload_level": None}
    db.add(CompletedWork(id=str(uuid4()), source_schedule_id="", source_block_id=logical.id,
        date=datetime.fromisoformat(timestamp).astimezone(ZoneInfo(settings["timezone"])).date().isoformat(), confirmed_at=timestamp, reopened_at=None, payload=payload))


def completed_value(db, row, settings):
    archive_id = None
    for archive in db.scalars(select(ScheduleArchive).order_by(ScheduleArchive.created_at.desc())):
        if archive.source_schedule_id == row.source_schedule_id and any(block.get("id") == row.source_block_id for block in archive.payload.get("blocks", [])):
            archive_id = archive.id
            break
    completion_date = datetime.fromisoformat(row.confirmed_at.replace("Z", "+00:00")).astimezone(ZoneInfo(settings["timezone"])).date().isoformat() if row.confirmed_at else None
    value = deepcopy(row.payload)
    logical = db.get(LogicalSession, value.get("logical_session_id")) if value.get("logical_session_id") else None
    if logical:
        value.update(logical_target_minutes=logical.target_minutes, logical_completed_minutes=logical.completed_minutes,
                     logical_session_complete=logical.completed_minutes >= logical.target_minutes)
    return {**value, "id": row.id, "source_schedule_id": row.source_schedule_id, "source_block_id": row.source_block_id,
        "date": completion_date, "completion_date": completion_date, "confirmed_at": row.confirmed_at, "archive_id": archive_id}


def undated_candidates(db, settings):
    result = []
    recorded_sessions = {row.source_block_id: row.payload["completed_minutes"] for row in db.scalars(select(CompletedWork).where(CompletedWork.reopened_at.is_(None))) if row.payload.get("source_type") == "manual_session"}
    for logical in db.scalars(select(LogicalSession)):
        undated_minutes = max(0, logical.baseline_completed_minutes - recorded_sessions.get(logical.id, 0))
        if not undated_minutes:
            continue
        assignment = db.get(TaskWeek, logical.assignment_id)
        task = db.get(TaskDefinition, assignment.task_definition_id) if assignment else None
        if not task:
            continue
        value = task.payload.get("deletion_snapshot") or task.payload
        result.append({"id": f"undated:{logical.id}", "source_type": "legacy_undated", "source_schedule_id": "", "source_block_id": logical.id,
            "date": None, "completion_date": None, "confirmed_at": None, "scheduled_date": None, "scheduled_start": None, "scheduled_end": None,
            "title": value.get("title", "Historical work"), "description": value.get("description", ""), "category": value.get("task_type", "academic"),
            "completed_minutes": undated_minutes, "task_definition_id": task.id, "task_assignment_id": assignment.id,
            "logical_session_id": logical.id, "logical_target_minutes": logical.target_minutes, "logical_completed_minutes": logical.completed_minutes,
            "logical_session_complete": logical.completed_minutes >= logical.target_minutes, "week_start": assignment.week_start,
            "assignment_source": assignment.payload.get("source", "manual"), "task_snapshot": deepcopy(value), "block": None,
            "project_snapshot": None, "location_snapshot": None, "project_title": None, "related_activity_title": None, "location_label": "", "archive_id": None})
    # Prior completed chunks without an explicit confirmation timestamp remain
    # factual undated work; they are never assigned their scheduled end as proof.
    for schedule in db.scalars(select(Schedule)):
        for block in schedule.payload.get("blocks", []):
            if block.get("status") != "completed" or block.get("completion_verified") and block.get("completion_confirmed_at"):
                continue
            chunk = db.get(TaskChunk, block["id"])
            if not chunk or not chunk.credited_minutes:
                continue
            result.append({**completion_payload(db, schedule, block, settings), "id": f"undated:{block['id']}", "source_type": "legacy_undated",
                "source_schedule_id": schedule.id, "source_block_id": block["id"], "date": None, "completion_date": None,
                "confirmed_at": None, "completed_minutes": chunk.credited_minutes, "archive_id": None})
    return result


def sync_undated(db, settings):
    """Freeze prior factual credit without assigning a completion timestamp.

    Reconcile only known credit/reversal fields. Missing source records never
    erase the independent snapshot.
    """
    existing = {(row.source_schedule_id, row.source_block_id): row for row in db.scalars(select(CompletedWork))}
    seen = set()
    for value in undated_candidates(db, settings):
        block_id = value["source_block_id"] if value["source_schedule_id"] else "baseline:" + str(uuid5(NAMESPACE_URL, value["logical_session_id"]))
        key = (value["source_schedule_id"], block_id)
        seen.add(key)
        row = existing.get(key)
        if row:
            if row.confirmed_at:
                continue
            row.reopened_at = None
            row.payload = {**row.payload, **{field: value[field] for field in ("completed_minutes", "logical_target_minutes", "logical_completed_minutes", "logical_session_complete")}}
        else:
            payload = {key: item for key, item in value.items() if key not in {"id", "source_schedule_id", "source_block_id", "date", "completion_date", "confirmed_at", "archive_id"}}
            db.add(CompletedWork(id=str(uuid4()), source_schedule_id=key[0], source_block_id=key[1], date=value.get("scheduled_date") or "",
                confirmed_at=None, reopened_at=None, payload=payload))
    for key, row in existing.items():
        if row.confirmed_at or key in seen or row.reopened_at:
            continue
        logical_id = row.payload.get("logical_session_id")
        logical = db.get(LogicalSession, logical_id) if logical_id else None
        chunk = db.get(TaskChunk, row.source_block_id) if row.source_schedule_id else None
        if (not row.source_schedule_id and logical and logical.baseline_completed_minutes == 0) or (chunk and (not chunk.credited_minutes or chunk.status != "completed")):
            row.reopened_at = now_stamp()


def search_text(value):
    fields = ("title", "name", "description", "course", "project_title", "related_activity_title", "location_label", "date", "mode", "category", "rationale", "notes", "address", "building", "room")
    texts = [str(value.get(field) or "") for field in fields]
    for field in ("task_snapshot", "project_snapshot", "activity_snapshot", "location_snapshot"):
        if isinstance(value.get(field), dict):
            texts.append(search_text(value[field]))
    texts.extend(search_text(block) for block in value.get("blocks", []))
    return " ".join(texts).casefold()


def matches(value, q, date_from, date_to, workload_level, category=None):
    if date_from and (not value.get("date") or value["date"] < date_from.isoformat()):
        return False
    if date_to and (not value.get("date") or value["date"] > date_to.isoformat()):
        return False
    searchable = value
    if "payload" in value:
        searchable = {"date": value.get("date"), "mode": value.get("mode"), "blocks": value["payload"].get("blocks", [])}
    return (not q or q.casefold() in search_text(searchable)) and (not workload_level or value.get("workload_level") == workload_level) and (not category or value.get("category") == category)


def reverse_completion(db, row, settings):
    """Withdraw this evidence once, preserving independent archive snapshots."""
    if row.reopened_at:
        return False
    value = row.payload
    logical_id = value.get("logical_session_id")
    logical = db.get(LogicalSession, logical_id) if logical_id else None
    assignment = db.get(TaskWeek, logical.assignment_id) if logical else None
    if assignment and (value.get("task_assignment_id") not in {None, assignment.id} or value.get("task_definition_id") not in {None, assignment.task_definition_id}):
        raise HTTPException(409, "Completion history and its original assignment disagree")
    schedule = db.get(Schedule, row.source_schedule_id) if row.source_schedule_id else None
    block = next((item for item in schedule.payload.get("blocks", []) if item["id"] == row.source_block_id), None) if schedule else None
    if not row.source_schedule_id:
        if logical:
            amount = value["completed_minutes"]
            if amount > logical.baseline_completed_minutes:
                raise HTTPException(409, "Completion credit changed; refresh history before reversing it")
            logical.baseline_completed_minutes -= amount
            db.flush()
            task_library.reconcile_session_credit(db, logical.id)
    elif block:
        previous = deepcopy(schedule.payload)
        work_confirmation.confirm_block(db, schedule, row.source_block_id, False, settings)
        sync_schedule(db, schedule, settings, previous)
    else:
        # The completion snapshot survives removed source plans. If its ledger
        # still exists, remove only this chunk's contribution.
        chunk = db.get(TaskChunk, row.source_block_id)
        if chunk:
            if chunk.schedule_id != row.source_schedule_id or logical_id and chunk.logical_session_id != logical_id:
                raise HTTPException(409, "Completion history and its original chunk disagree")
            chunk.status = (value.get("block") or {}).get("completion_previous_status") or "todo"
            chunk.credited_minutes = 0
            db.flush()
            task_library.reconcile_session_credit(db, chunk.logical_session_id)
        elif not logical and (value.get("block") or {}).get("completion_remaining_minutes_delta") is not None:
            saved = value["block"]
            definition = db.get(TaskDefinition, value.get("task_definition_id"))
            entity = db.get(Entity, ("tasks", definition.legacy_task_id or definition.id)) if definition else None
            if entity:
                entity.payload = {**entity.payload, "remaining_minutes": min(entity.payload["duration_minutes"], entity.payload["remaining_minutes"] + saved["completion_remaining_minutes_delta"])}
    row.reopened_at = now_stamp()
    db.flush()
    week = assignment.week_start if assignment else value.get("week_start")
    if week or row.date:
        work_confirmation.refresh_projections(db, settings, week or row.date)
    task_library.mark_stale(db, "Completion history changed. Regenerate to update remaining work.", {week} if week else None)
    sync_undated(db, settings)
    return True


def create_router(session_dependency, settings_of):
    router = APIRouter(prefix="/api", tags=["history"])

    @router.post("/completed-tasks/{key}/reverse")
    def reverse_completed(key: str, db=Depends(session_dependency)):
        db.execute(text("BEGIN IMMEDIATE"))
        row = db.get(CompletedWork, key)
        if not row:
            raise HTTPException(404, "Completed work not found")
        changed = reverse_completion(db, row, settings_of(db))
        db.commit()
        return {"id": row.id, "reversed": True, "changed": changed, "reopened_at": row.reopened_at}

    @router.post("/schedule-archives")
    def save_archive(value: ArchiveSave, db=Depends(session_dependency)):
        # Serialize read/decide/write on SQLite so concurrent Save requests
        # deduplicate rather than racing the unique revision constraint.
        db.execute(text("BEGIN IMMEDIATE"))
        schedule = db.get(Schedule, value.schedule_id)
        if not schedule:
            raise HTTPException(404, "Schedule not found")
        settings = settings_of(db)
        current = attached_archive(db, schedule)
        if current and not value.new_version:
            # Repeated save is idempotent, including after unrelated library edits.
            return {**archive_value(current), "created": False}
        if value.new_version:
            schedule.payload = {**schedule.payload, "schedule_revision_id": freeze_revision(db, schedule)}
        previous_versions = [row.payload.get("archive_version_number", 1) for row in db.scalars(select(ScheduleArchive).where(ScheduleArchive.source_schedule_id == schedule.id))]
        version_number = max([schedule.payload.get("archive_version_counter", 0), *previous_versions]) + 1
        schedule.payload = {**schedule.payload, "archive_version_counter": version_number}
        timestamp = now_stamp()
        row = ScheduleArchive(id=str(uuid4()), source_schedule_id=schedule.id, source_revision_id=revision(schedule), date=schedule.date,
            created_at=timestamp, updated_at=timestamp, attached=1, payload=snapshot(db, schedule, settings))
        row.payload = {**row.payload, "archive_version_number": version_number}
        sync_completions(db, schedule, settings, row.payload, allow_reversal=False)
        db.add(row)
        db.commit()
        return {**archive_value(row), "created": True}

    @router.get("/schedule-archives")
    def list_archives(q: str = Query(default="", max_length=300), date_from: Date | None = None, date_to: Date | None = None,
                      workload_level: str | None = None, limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0), db=Depends(session_dependency)):
        values = [archive_value(row) for row in db.scalars(select(ScheduleArchive).order_by(ScheduleArchive.date.desc(), ScheduleArchive.created_at.desc()))]
        values = [value for value in values if matches(value, q, date_from, date_to, workload_level)]
        return {"items": values[offset:offset + limit], "total": len(values), "limit": limit, "offset": offset,
                "summary": {"archive_count": len(values), "total_minutes": sum(value["total_minutes"] for value in values), "completed_minutes": sum(value["completed_minutes"] for value in values)}}

    @router.get("/schedule-archives/{key}")
    def read_archive(key: str, db=Depends(session_dependency)):
        row = db.get(ScheduleArchive, key)
        if not row:
            raise HTTPException(404, "Archived schedule not found")
        return archive_value(row)

    @router.delete("/schedule-archives/{key}", status_code=204)
    def delete_archive(key: str, db=Depends(session_dependency)):
        row = db.get(ScheduleArchive, key)
        if not row:
            raise HTTPException(404, "Archived schedule not found")
        db.delete(row)
        db.commit()
        return Response(status_code=204)

    @router.get("/completed-tasks")
    def list_completed(q: str = Query(default="", max_length=300), date_from: Date | None = None, date_to: Date | None = None,
                       workload_level: str | None = None, category: str | None = None, limit: int = Query(default=25, ge=1, le=100),
                       offset: int = Query(default=0, ge=0), db=Depends(session_dependency)):
        settings = settings_of(db)
        values = [completed_value(db, row, settings) for row in db.scalars(select(CompletedWork).where(CompletedWork.reopened_at.is_(None), CompletedWork.confirmed_at.is_not(None)).order_by(CompletedWork.confirmed_at.desc()))]
        values.sort(key=lambda value: datetime.fromisoformat(value["confirmed_at"].replace("Z", "+00:00")).timestamp(), reverse=True)
        values = [value for value in values if matches(value, q, date_from, date_to, workload_level, category)]
        undated = [completed_value(db, row, settings) for row in db.scalars(select(CompletedWork).where(CompletedWork.reopened_at.is_(None), CompletedWork.confirmed_at.is_(None)))]
        undated = [value for value in undated if matches(value, q, date_from, date_to, workload_level, category)]
        return {"items": values[offset:offset + limit], "total": len(values), "limit": limit, "offset": offset,
            "undated_items": undated, "legacy_undated_count": len(undated),
            "summary": {"completed_count": len(values), "completed_minutes": sum(value["completed_minutes"] for value in values),
                "logical_sessions_completed": len({value["logical_session_id"] for value in values if value.get("logical_session_id") and value.get("logical_session_complete")}),
                "undated_completed_minutes": sum(value["completed_minutes"] for value in undated)}}

    return router
