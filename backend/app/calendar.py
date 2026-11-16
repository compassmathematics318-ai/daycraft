"""One calendar source shared by the block library, weekly grid and optimizer.

Existing class recurrence remains an explicit compatibility series. Individual
overrides add an exception to that series and persist an ordinary occurrence.
"""
from copy import deepcopy
from datetime import date as Date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import schemas
from .database import Activity, Entity, Occurrence, Project, Schedule, TaskDefinition, TaskWeek

UTC = timezone.utc


def fail(message, status=409):
    raise HTTPException(status, message)


def instant(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Calendar timestamps must include a timezone offset")
    return result.astimezone(UTC)


def iso(value):
    return instant(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def day(value):
    return value if isinstance(value, Date) else Date.fromisoformat(value)


def localize(value, zone):
    result = value.replace(tzinfo=zone)
    if result.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != value.replace(tzinfo=None):
        raise ValueError("The target local time does not exist because of daylight saving time")
    return result


def activity_document(row):
    return {"allow_alternative_locations": False, "alternative_location_ids": [], "location_requirements": [], **row.payload, "location_mode": row.payload.get("location_mode", "required" if row.payload.get("location_id") else "unspecified"), "id": row.id, "legacy_class_id": row.legacy_class_id}


def activities_list(db):
    return [activity_document(row) for row in db.scalars(select(Activity).order_by(Activity.id))]


def validate_related_entity(db, value, key):
    relation = value.get("related_entity")
    if not relation:
        return
    target = db.get(Activity if relation["kind"] == "activity" else Project, relation["id"])
    if not target:
        fail("Related entity no longer exists", 422)
    graph = {row.id: row.payload.get("related_entity") for row in db.scalars(select(Activity))}
    graph[key] = relation
    visited, cursor = set(), key
    while cursor in graph:
        if cursor in visited:
            fail("Commitment relationships cannot refer to themselves or form a cycle", 422)
        visited.add(cursor)
        link = graph[cursor]
        if not link or link["kind"] != "activity":
            break
        cursor = link["id"]


def detach_related_entity(db, kind, key):
    for row in db.scalars(select(Activity)):
        if row.payload.get("related_entity") == {"kind": kind, "id": key}:
            row.payload = {**row.payload, "related_entity": None}
            from .task_library import mark_stale
            mark_stale(db, "A commitment's related entity was deleted. Regenerate to update context.")


def enrich_related_context(db, activity, events):
    relation = activity.get("related_entity")
    if not relation:
        return activity
    row = db.get(Activity if relation["kind"] == "activity" else Project, relation["id"])
    if not row:
        return {**activity, "related_entity": None}
    context = {**row.payload, "kind": relation["kind"], "id": row.id}
    context.pop("related_entity", None)
    if relation["kind"] == "activity":
        context["occurrences"] = [event for event in events if event["activity_id"] == row.id]
    else:
        context["title"] = row.payload.get("name", "")
    return {**activity, "related_entity_context": context}


def occurrence_document(row):
    return {"id": row.id, "activity_id": row.activity_id, "start": row.start, "end": row.end, "source": row.source, "location_override": row.location_override}


def _legacy_payload(raw, settings, previous=None):
    previous = previous or {}
    subtype = raw.get("class_type", "Lecture")
    assessment = subtype.casefold() in {"exam", "assessment", "quiz", "midterm", "final"} and bool(raw.get("date"))
    category = "assessment" if assessment else "class" if subtype in {"Lecture", "Tutorial", "Lab"} else "commitment"
    commitment_subtype = previous.get("subtype") if previous.get("category") == "commitment" and previous.get("subtype") in {"Personal", "Groupwork"} else "Personal"
    zone = ZoneInfo(settings["timezone"])
    start = iso(localize(datetime.fromisoformat(f"{raw['date']}T{raw['start_time']}"), zone)) if assessment else None
    end = iso(localize(datetime.fromisoformat(f"{raw['date']}T{raw['end_time']}"), zone)) if assessment else None
    return {"related_entity": previous.get("related_entity"), "id": raw["id"], "title": raw["title"], "category": category, "subtype": None if assessment else subtype if category == "class" else commitment_subtype, "description": previous.get("description", "" if category == "class" or assessment else f"Imported {subtype} commitment."), "course": previous.get("course"), "location_id": raw.get("location_id"), "location_requirements": raw.get("location_requirements", []), "allow_alternative_locations": raw.get("allow_alternative_locations", False), "alternative_location_ids": raw.get("alternative_location_ids", []), "location_mode": raw.get("location_mode", "required" if raw.get("location_id") else "unspecified"), "building": raw.get("building", ""), "room": raw.get("room", ""), "start_date": raw.get("start_date"), "end_date": raw.get("end_date"), "assessment_start": start, "assessment_end": end, "legacy_class_id": raw["id"]}


def _set_assessment_occurrence(db, row):
    value = row.payload
    existing = list(db.scalars(select(Occurrence).where(Occurrence.activity_id == row.id, Occurrence.source == "assessment")))
    excluded = row.legacy_snapshot and row.legacy_snapshot.get("date") in row.legacy_snapshot.get("exceptions", [])
    if value["category"] != "assessment" or excluded:
        for occurrence in existing:
            db.delete(occurrence)
        return
    target = existing[0] if existing else Occurrence(id=f"assessment:{row.id}", activity_id=row.id, source="assessment")
    target.start, target.end = iso(value["assessment_start"]), iso(value["assessment_end"])
    db.add(target)
    for occurrence in existing[1:]:
        db.delete(occurrence)


def sync_legacy(db, settings):
    originals = {row.id: row for row in db.scalars(select(Entity).where(Entity.collection == "classes"))}
    mirrors = {row.legacy_class_id: row for row in db.scalars(select(Activity).where(Activity.legacy_class_id.is_not(None)))}
    for key, entity in originals.items():
        raw = entity.payload
        row = mirrors.get(key)
        if row and row.legacy_snapshot == raw:
            continue
        value = _legacy_payload(raw, settings, row.payload if row else None)
        if not row:
            row = Activity(id=key, legacy_class_id=key, payload=value)
        row.payload, row.legacy_snapshot = value, deepcopy(raw)
        db.add(row)
        db.flush()
        _set_assessment_occurrence(db, row)
    for key, row in mirrors.items():
        if key not in originals:
            _detach_task_links(db, row.id)
            db.delete(row)
    db.flush()


def _legacy_active(raw, date):
    text = date.isoformat()
    if text in raw.get("exceptions", []):
        return False
    if raw.get("date"):
        return raw["date"] == text
    return date.weekday() in raw.get("weekdays", []) and (not raw.get("start_date") or raw["start_date"] <= text) and (not raw.get("end_date") or text <= raw["end_date"])


def occurrences_between(db, start_date, end_date, settings):
    """Return intersecting occurrences for an inclusive range of local dates."""
    first, last = day(start_date), day(end_date)
    zone = ZoneInfo(settings["timezone"])
    start = datetime.combine(first, time(), zone)
    end = datetime.combine(last + timedelta(days=1), time(), zone)
    values = [occurrence_document(row) for row in db.scalars(select(Occurrence).where(Occurrence.start < iso(end), Occurrence.end > iso(start)))]
    mirrors = {row.legacy_class_id: row for row in db.scalars(select(Activity).where(Activity.legacy_class_id.is_not(None)))}
    for source in db.scalars(select(Entity).where(Entity.collection == "classes")):
        mirror = mirrors.get(source.id)
        if not mirror or mirror.payload["category"] == "assessment":
            continue
        raw = source.payload
        current = first
        while current <= last:
            if _legacy_active(raw, current):
                try:
                    s = localize(datetime.fromisoformat(f"{current.isoformat()}T{raw['start_time']}"), zone)
                    e = localize(datetime.fromisoformat(f"{current.isoformat()}T{raw['end_time']}"), zone)
                except ValueError as exc:
                    fail(f"Existing legacy block {raw['title']} has an invalid local time on {current.isoformat()}. Edit its legacy repeat or add an exception: {exc}", 422)
                values.append({"id": f"legacy:{source.id}:{current.isoformat()}", "activity_id": mirror.id, "start": iso(s), "end": iso(e), "source": "legacy"})
            current += timedelta(days=1)
    return sorted(values, key=lambda item: (instant(item["start"]), item["id"]))


def _bounds(value, start, end, settings):
    zone = ZoneInfo(settings["timezone"])
    first = instant(start).astimezone(zone).date().isoformat()
    last = (instant(end) - timedelta(microseconds=1)).astimezone(zone).date().isoformat()
    if value.get("start_date") and first < value["start_date"]:
        fail("This occurrence starts before the block's permitted start date")
    if value.get("end_date") and last > value["end_date"]:
        fail("This occurrence extends past the block's permitted end date")


def _validate_occurrence(db, value, start, end, settings, exclude=()):
    start, end = instant(start), instant(end)
    if end <= start:
        fail("Occurrence end must be later than start", 422)
    _bounds(value, start, end, settings)
    zone = ZoneInfo(settings["timezone"])
    first, last = start.astimezone(zone).date(), (end - timedelta(microseconds=1)).astimezone(zone).date()
    activities = {item["id"]: item for item in activities_list(db)}
    for other in occurrences_between(db, first, last, settings):
        if other["id"] not in exclude and start < instant(other["end"]) and end > instant(other["start"]):
            title = activities[other["activity_id"]]["title"]
            fail(f"Conflicts with {title} ({instant(other['start']).astimezone(zone).strftime('%a %b %d, %H:%M')}–{instant(other['end']).astimezone(zone).strftime('%H:%M')}). Choose a different time.")


def _mark_stale(db, settings, start=None, end=None, activity_id=None, legacy_id=None):
    zone = ZoneInfo(settings["timezone"])
    first = instant(start).astimezone(zone).date().isoformat() if start else None
    last = (instant(end) - timedelta(microseconds=1)).astimezone(zone).date().isoformat() if end else None
    for schedule in db.scalars(select(Schedule)):
        relevant = first is not None and first <= schedule.date <= last
        relevant |= any((activity_id and block.get("activity_id") == activity_id) or (legacy_id and block.get("class_id") == legacy_id) for block in schedule.payload["blocks"])
        if relevant:
            message = "Calendar commitments changed. Regenerate this day to revalidate time and travel."
            conflicts = [item for item in schedule.payload.get("conflicts", []) if item != message] + [message]
            schedule.payload = {**schedule.payload, "status": "stale", "calendar_dirty": True, "conflicts": conflicts}


def _mark_linked_tasks_stale(db, activity_id):
    """A related event can change task urgency on a different planning day."""
    linked = any(row.related_activity_id == activity_id for row in db.scalars(select(TaskDefinition)))
    linked |= any(row.payload.get("overrides", {}).get("related_activity_id") == activity_id for row in db.scalars(select(TaskWeek)))
    linked |= any(row.payload.get("related_entity") == {"kind": "activity", "id": activity_id} for row in db.scalars(select(Activity)))
    if linked:
        from .task_library import mark_stale
        mark_stale(db, "A related calendar activity changed. Regenerate to apply current task context.")


def _detach_task_links(db, activity_id):
    """Clear live relations while retaining task, session and history records."""
    _mark_linked_tasks_stale(db, activity_id)
    detach_related_entity(db, "activity", activity_id)
    for definition in db.scalars(select(TaskDefinition).where(TaskDefinition.related_activity_id == activity_id)):
        definition.related_activity_id = None
        definition.payload = {**definition.payload, "related_activity_id": None}
    for assignment in db.scalars(select(TaskWeek)):
        overrides = assignment.payload.get("overrides", {})
        if overrides.get("related_activity_id") == activity_id:
            assignment.payload = {**assignment.payload, "overrides": {**overrides, "related_activity_id": None}}


def _mark_activity_stale(db, row, settings):
    _mark_linked_tasks_stale(db, row.id)
    for schedule in db.scalars(select(Schedule)):
        events = occurrences_between(db, schedule.date, schedule.date, settings)
        if any(item["activity_id"] == row.id for item in events):
            start = datetime.combine(Date.fromisoformat(schedule.date), time(), ZoneInfo(settings["timezone"]))
            _mark_stale(db, settings, start, start + timedelta(days=1))
    _mark_stale(db, settings, activity_id=row.id, legacy_id=row.legacy_class_id)


def _legacy_exception(db, occurrence, settings):
    row = db.get(Activity, occurrence["activity_id"])
    original = db.get(Entity, ("classes", row.legacy_class_id))
    date = instant(occurrence["start"]).astimezone(ZoneInfo(settings["timezone"])).date().isoformat()
    original.payload = {**original.payload, "exceptions": sorted(set(original.payload.get("exceptions", []) + [date]))}
    row.legacy_snapshot = deepcopy(original.payload)


def _find_occurrence(db, occurrence_id, settings):
    row = db.get(Occurrence, occurrence_id)
    if row:
        return occurrence_document(row), row
    if occurrence_id.startswith("legacy:"):
        try:
            date = Date.fromisoformat(occurrence_id.rsplit(":", 1)[1])
        except ValueError:
            fail("Calendar occurrence not found", 404)
        result = next((item for item in occurrences_between(db, date, date, settings) if item["id"] == occurrence_id), None)
        if result:
            return result, None
    fail("Calendar occurrence not found", 404)


def _location_exists(db, value):
    if value.get("location_id") and not db.get(Entity, ("locations", value["location_id"])):
        fail("Selected location no longer exists", 422)
    if any(not db.get(Entity, ("locations", place)) for place in value.get("alternative_location_ids", [])):
        fail("An alternative location no longer exists", 422)


def _validate_existing_bounds(db, row, value, settings):
    for event in db.scalars(select(Occurrence).where(Occurrence.activity_id == row.id)):
        if event.source != "assessment":
            _bounds(value, event.start, event.end, settings)


def create_router(session_dependency, settings_of):
    router = APIRouter(prefix="/api")

    @router.get("/activities", response_model=list[schemas.Activity])
    def list_activities(db: Session = Depends(session_dependency)):
        return activities_list(db)

    @router.post("/activities", response_model=schemas.Activity, status_code=201)
    def add_activity(value: schemas.Activity, db: Session = Depends(session_dependency)):
        if value.id or value.legacy_class_id:
            fail("New blocks receive their identity from the server", 422)
        settings = settings_of(db)
        payload = value.model_dump(mode="json")
        _location_exists(db, payload)
        key = str(uuid4())
        validate_related_entity(db, payload, key)
        payload.update(id=key, legacy_class_id=None)
        if payload["category"] == "assessment":
            payload.update(assessment_start=iso(value.assessment_start), assessment_end=iso(value.assessment_end))
            _validate_occurrence(db, payload, payload["assessment_start"], payload["assessment_end"], settings)
        row = Activity(id=key, payload=payload)
        db.add(row)
        db.flush()
        _set_assessment_occurrence(db, row)
        if payload["category"] == "assessment":
            _mark_stale(db, settings, payload["assessment_start"], payload["assessment_end"])
        db.commit()
        return activity_document(row)

    @router.put("/activities/{activity_id}", response_model=schemas.Activity)
    def update_activity(activity_id: str, value: schemas.Activity, db: Session = Depends(session_dependency)):
        row = db.get(Activity, activity_id)
        if not row:
            fail("Block not found", 404)
        if value.id and value.id != activity_id or value.legacy_class_id and value.legacy_class_id != row.legacy_class_id:
            fail("Block identities cannot be changed", 422)
        settings = settings_of(db)
        payload = schemas.location_edit(value.model_dump(mode="json"), row.payload, value.model_fields_set)
        if "related_entity" not in value.model_fields_set:
            payload["related_entity"] = row.payload.get("related_entity")
        validate_related_entity(db, payload, row.id)
        payload.update(id=row.id, legacy_class_id=row.legacy_class_id)
        _location_exists(db, payload)
        if value.category != row.payload["category"] and (row.legacy_class_id or db.scalar(select(Occurrence).where(Occurrence.activity_id == row.id))):
            fail("A block's category cannot change while it has placements or a legacy series. Create a new block instead.")
        _validate_existing_bounds(db, row, payload, settings)
        if value.category == "assessment":
            payload.update(assessment_start=iso(value.assessment_start), assessment_end=iso(value.assessment_end))
            excluded = [event.id for event in db.scalars(select(Occurrence).where(Occurrence.activity_id == row.id))]
            assessment_changed = payload["assessment_start"] != iso(row.payload["assessment_start"]) or payload["assessment_end"] != iso(row.payload["assessment_end"])
            was_cancelled = row.legacy_snapshot and row.legacy_snapshot.get("date") in row.legacy_snapshot.get("exceptions", [])
            if not was_cancelled or assessment_changed:
                _validate_occurrence(db, payload, payload["assessment_start"], payload["assessment_end"], settings, excluded)
        _mark_activity_stale(db, row, settings)
        row.payload = payload
        if row.legacy_class_id:
            original = db.get(Entity, ("classes", row.legacy_class_id))
            updated = {**original.payload, **{key: payload[key] for key in ("title", "location_id", "location_mode", "allow_alternative_locations", "alternative_location_ids", "location_requirements", "building", "room", "start_date", "end_date")}}
            if value.category == "class":
                updated["class_type"] = value.subtype
            if value.category == "assessment":
                start_local, end_local = instant(payload["assessment_start"]).astimezone(ZoneInfo(settings["timezone"])), instant(payload["assessment_end"]).astimezone(ZoneInfo(settings["timezone"]))
                if start_local.date() == end_local.date():
                    updated.update(date=start_local.date().isoformat(), start_time=start_local.strftime("%H:%M"), end_time=end_local.strftime("%H:%M"))
                if assessment_changed:
                    updated["exceptions"] = [date for date in updated.get("exceptions", []) if date not in {updated.get("date"), original.payload.get("date")}]
            original.payload = updated
            row.legacy_snapshot = deepcopy(updated)
        _set_assessment_occurrence(db, row)
        if value.category == "assessment":
            _mark_stale(db, settings, payload["assessment_start"], payload["assessment_end"])
        db.commit()
        return activity_document(row)

    @router.delete("/activities/{activity_id}", status_code=204)
    def delete_activity(activity_id: str, db: Session = Depends(session_dependency)):
        row = db.get(Activity, activity_id)
        if not row:
            fail("Block not found", 404)
        _mark_activity_stale(db, row, settings_of(db))
        _detach_task_links(db, row.id)
        if row.legacy_class_id:
            original = db.get(Entity, ("classes", row.legacy_class_id))
            if original:
                db.delete(original)
        db.delete(row)
        db.commit()

    @router.get("/calendar")
    def calendar_week(week_start: Date, db: Session = Depends(session_dependency)):
        week_start = schemas.sunday_of(week_start)
        end = week_start + timedelta(days=6)
        return {"week_start": week_start.isoformat(), "week_end": end.isoformat(), "activities": activities_list(db), "occurrences": occurrences_between(db, week_start, end, settings_of(db))}

    @router.post("/occurrences", response_model=schemas.CalendarOccurrence, status_code=201)
    def add_occurrence(value: schemas.OccurrenceInput, db: Session = Depends(session_dependency)):
        row = db.get(Activity, value.activity_id)
        if not row:
            fail("Block not found", 404)
        if row.payload["category"] == "assessment":
            fail("Assessments already have one fixed occurrence. Edit the assessment's date and time explicitly.")
        settings = settings_of(db)
        _validate_occurrence(db, row.payload, value.start, value.end, settings)
        override = value.location_override.model_dump(mode="json") if value.location_override else None
        _location_exists(db, override or {})
        event = Occurrence(id=str(uuid4()), activity_id=row.id, start=iso(value.start), end=iso(value.end), source="manual", location_override=override)
        db.add(event)
        _mark_stale(db, settings, event.start, event.end)
        _mark_linked_tasks_stale(db, row.id)
        db.commit()
        return occurrence_document(event)

    @router.put("/occurrences/{occurrence_id}", response_model=schemas.CalendarOccurrence)
    def update_occurrence(occurrence_id: str, value: schemas.OccurrenceInput, db: Session = Depends(session_dependency)):
        settings = settings_of(db)
        previous, event = _find_occurrence(db, occurrence_id, settings)
        if value.activity_id != previous["activity_id"]:
            fail("Moving a placement cannot change its activity identity", 422)
        row = db.get(Activity, value.activity_id)
        if row.payload["category"] == "assessment":
            fail("Edit the assessment's date and time explicitly in its block definition.")
        _validate_occurrence(db, row.payload, value.start, value.end, settings, [occurrence_id])
        _mark_stale(db, settings, previous["start"], previous["end"])
        if not event:
            _legacy_exception(db, previous, settings)
            event = Occurrence(id=str(uuid4()), activity_id=row.id, source="manual")
        event.start, event.end = iso(value.start), iso(value.end)
        if "location_override" in value.model_fields_set:
            override = value.location_override.model_dump(mode="json") if value.location_override else None
            if override:
                before = previous.get("location_override") or row.payload
                override = schemas.location_edit(override, before, value.location_override.model_fields_set)
                override.pop("building", None)
            _location_exists(db, override or {})
            event.location_override = override
        db.add(event)
        _mark_stale(db, settings, event.start, event.end)
        _mark_linked_tasks_stale(db, row.id)
        db.commit()
        return occurrence_document(event)

    @router.delete("/occurrences/{occurrence_id}", status_code=204)
    def delete_occurrence(occurrence_id: str, db: Session = Depends(session_dependency)):
        settings = settings_of(db)
        previous, event = _find_occurrence(db, occurrence_id, settings)
        if db.get(Activity, previous["activity_id"]).payload["category"] == "assessment":
            fail("Delete the assessment block, or explicitly edit its scheduled time.")
        _mark_stale(db, settings, previous["start"], previous["end"])
        _mark_linked_tasks_stale(db, previous["activity_id"])
        if event:
            db.delete(event)
        else:
            _legacy_exception(db, previous, settings)
        db.commit()

    @router.post("/calendar/copy-previous-week")
    def copy_week(value: schemas.CopyWeek, db: Session = Depends(session_dependency)):
        settings = settings_of(db)
        zone = ZoneInfo(settings["timezone"])
        target = value.week_start
        originals = occurrences_between(db, target - timedelta(days=7), target - timedelta(days=1), settings)
        activities = {item["id"]: item for item in activities_list(db)}
        result = {"created": 0, "duplicates": 0, "skipped": [], "occurrences": []}
        for original in originals:
            activity = activities[original["activity_id"]]
            if activity["category"] == "assessment":
                continue
            source_date = instant(original["start"]).astimezone(zone).date()
            if not target - timedelta(days=7) <= source_date < target:
                continue
            try:
                old_start, old_end = instant(original["start"]), instant(original["end"])
                start_local = old_start.astimezone(zone).replace(tzinfo=None) + timedelta(days=7)
                end_local = old_end.astimezone(zone).replace(tzinfo=None) + timedelta(days=7)
                start, end = localize(start_local, zone), localize(end_local, zone)
                if instant(end) - instant(start) != old_end - old_start:
                    raise ValueError("Daylight saving time changes the duration; schedule this occurrence explicitly")
                existing = occurrences_between(db, start.date(), end.date(), settings)
                if any(item["activity_id"] == activity["id"] and instant(item["start"]) == instant(start) and instant(item["end"]) == instant(end) for item in existing):
                    result["duplicates"] += 1
                    continue
                _validate_occurrence(db, activity, start, end, settings)
                event = Occurrence(id=str(uuid4()), activity_id=activity["id"], start=iso(start), end=iso(end), source="manual", location_override=deepcopy(original.get("location_override")))
                db.add(event)
                db.flush()
                _mark_stale(db, settings, start, end)
                _mark_linked_tasks_stale(db, activity["id"])
                result["created"] += 1
                result["occurrences"].append(occurrence_document(event))
            except (HTTPException, ValueError) as exc:
                result["skipped"].append({"activity_id": activity["id"], "title": activity["title"], "date": (instant(original["start"]).astimezone(zone).date() + timedelta(days=7)).isoformat(), "reason": str(exc.detail) if isinstance(exc, HTTPException) else str(exc)})
        db.commit()
        return result

    return router
