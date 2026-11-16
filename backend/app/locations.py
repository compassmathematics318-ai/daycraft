"""Shared location policies, reference integrity and the geographic calendar view."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from . import calendar, schemas, suitability, task_library, task_recurrence
from .database import Configuration, Entity, Occurrence, Schedule, TaskDefinition, TaskWeek


def policy(value):
    return {"location_mode": value.get("location_mode", "required" if value.get("location_id") else "unspecified"), "location_id": value.get("location_id"),
            "allow_alternative_locations": value.get("allow_alternative_locations", False),
            "alternative_location_ids": value.get("alternative_location_ids", []),
            "location_requirements": value.get("location_requirements", [])}


def enrich_blocks(db, blocks, previous=()):
    """Ignore client evidence; use owning activity/task metadata for inference."""
    places = suitability.saved_places(db)
    old = {item["id"]: item for item in previous}
    result = []
    for block in blocks:
        before = old.get(block["id"])
        if before and (before.get("locked") or before.get("status") in {"completed", "in_progress"} or task_library.withdrawn_work(db, before)[2]):
            evidence = before.get("location_suitability")
            result.append({**block, "location_suitability": evidence} if evidence else {key: value for key, value in block.items() if key != "location_suitability"})
            continue
        source = {}
        definition = db.get(TaskDefinition, block.get("task_definition_id") or block.get("task_id")) if block.get("task_definition_id") or block.get("task_id") else None
        if definition:
            source = dict(definition.payload)
            assignment = db.get(TaskWeek, block["task_assignment_id"]) if block.get("task_assignment_id") else None
            if assignment:
                _, source = task_recurrence.effective_value(db, assignment, definition)
            if definition.project_id:
                from .database import Project
                project = db.get(Project, definition.project_id)
                source = {**source, "project": project.payload if project else {}}
        elif block.get("activity_id"):
            from .database import Activity
            activity = db.get(Activity, block["activity_id"])
            source = dict(activity.payload) if activity else {}
            occurrence = db.get(Occurrence, block["occurrence_id"]) if block.get("occurrence_id") else None
            if occurrence:
                source.update(occurrence.location_override or {})
        data = {**block, **source}
        if block.get("location_override") or not source:
            data.update(policy(block))
        enriched = suitability.enrich(data, places)
        result.append({**block, "location_suitability": enriched["location_suitability"]})
    return result


def schedule_view(value, settings, db=None):
    """Flag unsafe pending plans without rewriting saved history or blocks."""
    today = datetime.now(ZoneInfo(settings["timezone"])).date().isoformat()
    if value.get("date", "") < today:
        return value
    if value.get("location_intelligence_version") != suitability.INTELLIGENCE_VERSION and any(
        policy(block)["location_mode"] == "preferred" and block.get("kind") in {"task", "project", "personal"}
        and not block.get("locked") and block.get("status") not in {"completed", "in_progress", "skipped"}
        for block in value.get("blocks", [])
    ):
        message = "This saved plan predates verified venue suitability. Regenerate this day to review flexible preferred locations and current travel."
        return {**value, "status": "stale", "locations_dirty": True, "needs_regeneration": True,
                "conflicts": list(dict.fromkeys([*value.get("conflicts", []), message])),
                "explanations": list(dict.fromkeys([*value.get("explanations", []), message]))}
    blocks = enrich_blocks(db, value.get("blocks", [])) if db is not None else value.get("blocks", [])
    for block in blocks:
        if block.get("locked") or block.get("status") in {"completed", "in_progress", "skipped"}:
            continue
        mode = policy(block)["location_mode"]
        if mode not in {"preferred", "required"}:
            continue
        permitted = {block.get("location_id")}
        if mode == "preferred":
            if db is not None:
                permitted.update(suitability.candidate_ids(block))
            elif block.get("allow_alternative_locations"):
                permitted.update(block.get("alternative_location_ids", []))
        if block.get("resolved_location_id") and block["resolved_location_id"] not in permitted:
            message = "A saved plan uses a venue without current suitability evidence or permission. Regenerate this day to revalidate selected places and alternatives."
            return {**value, "status": "stale", "locations_dirty": True, "needs_regeneration": True,
                    "conflicts": list(dict.fromkeys([*value.get("conflicts", []), message])),
                    "explanations": list(dict.fromkeys([*value.get("explanations", []), message]))}
    return value


def references_place(value, key):
    return key in value.get("alternative_location_ids", []) or any(value.get(field) == key for field in ("location_id", "origin_id", "destination_id", "resolved_location_id"))


def place_in_use(db, key):
    from .database import Activity
    config = db.get(Configuration, "settings")
    if config and any(meal.get("location_id") == key for meal in config.payload.get("meals", [])):
        return True
    if any(references_place(item.payload, key) for item in db.scalars(select(Activity))):
        return True
    if any(references_place(item.payload, key) for item in db.scalars(select(Entity).where(Entity.collection.in_(("tasks", "classes"))))):
        return True
    if any(references_place(item.payload, key) for item in db.scalars(select(TaskDefinition))):
        return True
    if any(references_place(item.payload.get("overrides", {}), key) or references_place(item.payload.get("definition_snapshot", {}), key) for item in db.scalars(select(TaskWeek))):
        return True
    if any(references_place(item.location_override or {}, key) for item in db.scalars(select(Occurrence))):
        return True
    return any(references_place(block, key) for row in db.scalars(select(Schedule)) for block in row.payload.get("blocks", []))


def mark_place_stale(db, key):
    # Routes and coordinates are shared context; keep historical blocks intact.
    for row in db.scalars(select(Schedule)):
        row.payload = {**row.payload, "status": "stale", "locations_dirty": True,
                       "explanations": list(dict.fromkeys([*row.payload.get("explanations", []), "A saved place changed. Regenerate this day to revalidate locations and travel."]))}


def validate_block_locations(db, blocks, previous):
    old = {item["id"]: item for item in previous}
    for block in blocks:
        if any(not db.get(Entity, ("locations", key)) for key in block.get("alternative_location_ids", [])):
            raise HTTPException(422, "An alternative location no longer exists")
        before = old.get(block["id"])
        if before and (before.get("locked") or before.get("status") in ("completed", "in_progress") or before.get("kind") in ("class", "meal")):
            if (policy(before) != policy(block)
                    or bool(before.get("location_override")) != bool(block.get("location_override"))
                    or before.get("resolved_location_id") != block.get("resolved_location_id")):
                raise HTTPException(409, "Locked commitments and started work retain their saved location. Edit the calendar occurrence or unlock unstarted work first.")
        if block.get("kind") not in ("task", "project"):
            continue
        definition = db.get(TaskDefinition, block.get("task_definition_id") or block.get("task_id"))
        if not definition:
            continue
        base = definition.payload
        assignment = db.get(TaskWeek, block.get("task_assignment_id")) if block.get("task_assignment_id") else None
        if assignment:
            _, base = task_recurrence.effective_value(db, assignment, definition)
        if not block.get("location_override") and policy(block) != policy(base):
            # Old saved blocks may carry historical resolved metadata. Keep those
            # unchanged until regeneration while requiring explicit new overrides.
            if not before or policy(block) != policy(before):
                raise HTTPException(422, "Changing a task session location requires an explicit location override")


def resolve_manual_locations(blocks, previous):
    """Manual physical selections commit to the selected venue before validation.

    Generated alternatives already carry a resolved venue. A manual change that
    clears that value selects the configured place; feasibility validation must
    validate that actual place rather than merely some allowed possibility.
    """
    old = {item["id"]: item for item in previous}
    for block in blocks:
        before = old.get(block["id"], {})
        protected = before.get("locked") or before.get("status") in {"completed", "in_progress"} or before.get("kind") in {"class", "meal"}
        if not protected and not block.get("_withdrawn_history") and block.get("kind") != "travel" and policy(block)["location_mode"] in {"preferred", "required"} and not block.get("resolved_location_id"):
            block["resolved_location_id"] = block["location_id"]
    return blocks


def reference(source, value, title, kind, location, start=None, end=None, target=None):
    return {"id": f"{source}:{value}", "source": source, "entity_id": value,
            "title": title, "type": kind, "start": start, "end": end,
            **policy(location), "resolved_location_id": location.get("resolved_location_id"), "category": location.get("category", location.get("task_type", kind)),
            "subtype": location.get("subtype"), "building": location.get("building", ""),
            "room": location.get("room", ""), "floor": location.get("floor", ""),
            "entrance": location.get("entrance", ""), "edit_target": target}


def overview(db, first, settings):
    first = schemas.sunday_of(first)
    last = first + timedelta(days=6)
    places = {row.id: {**schemas.Location.model_validate(row.payload).model_dump(mode="json"), "references": [], "reference_count": 0} for row in db.scalars(select(Entity).where(Entity.collection == "locations").order_by(Entity.id))}
    groups = {}
    activities = {item["id"]: item for item in calendar.activities_list(db)}
    definitions = {item["id"]: item for item in task_library.definitions_list(db)}
    deleted_tasks = {key for row in db.scalars(select(TaskDefinition)) if row.payload.get("deleted_at") for key in (row.id, row.legacy_task_id) if key}
    assignments = {item["task_definition_id"]: item for item in task_library.week_state(db, first.isoformat())["assignments"]}
    zone = ZoneInfo(settings["timezone"])
    today = datetime.now(zone).date()
    schedules = list(db.scalars(select(Schedule).order_by(Schedule.date)))
    views = {row.id: schedule_view(row.payload, settings, db) for row in schedules}
    visits = {}
    for row in schedules:
        valid = views[row.id].get("status") in {"optimal", "feasible", "partial"} and not any(
            views[row.id].get(field) for field in ("calendar_dirty", "projects_dirty", "tasks_dirty", "locations_dirty", "needs_regeneration")
        )
        for block in row.payload.get("blocks", []):
            if not block.get("occurrence_id") or not block.get("resolved_location_id") or block.get("status") == "skipped":
                continue
            ended = (calendar.instant(block["end"]) - timedelta(microseconds=1)).astimezone(zone).date()
            # Calendar blocks are automatically locked to their source times;
            # that flag alone cannot make stale future attendance authoritative.
            recorded = ended < today or block.get("status") in {"completed", "in_progress"}
            current_candidate = False
            if valid:
                current = enrich_blocks(db, [block])[0]
                current_candidate = block["resolved_location_id"] in suitability.candidate_ids(current)
            if current_candidate or recorded:
                key = (block.get("activity_id"), block["occurrence_id"])
                previous = visits.get(key)
                if previous is None or (recorded and not previous[1]):
                    visits[key] = (block, recorded)

    def add(item, identity, canonical):
        key = item.get("resolved_location_id") if item.get("location_mode") in {"preferred", "required"} and item.get("resolved_location_id") else item.get("location_id")
        if item.get("resolved_location_id") and key != item.get("location_id"):
            # These fields describe a visit at its actual venue. The original
            # block keeps the configured place's room for preference editing.
            actual = places.get(key, {})
            item = {**item, **{field: actual.get(field, "") for field in ("building", "room", "floor", "entrance")}}
        # Nonphysical references use a separate policy bucket so a remote weekly
        # visit cannot swallow a reusable unspecified definition.
        bucket = key if key in places else "unlocated:" + item["location_mode"]
        group_key = (bucket, identity)
        if group_key not in groups:
            groups[group_key] = {**canonical, **{field: item.get(field) for field in ("location_id", "location_mode", "allow_alternative_locations", "alternative_location_ids", "resolved_location_id", "room", "building", "floor", "entrance")},
                                 "id": identity if key in places else identity + ":" + item["location_mode"], "start": None, "end": None,
                                 "occurrences": [], "placements": [], "occurrence_count": 0}
        group = groups[group_key]
        if any(existing["id"] == item["id"] for existing in group["placements"]):
            return
        group["placements"].append(item)
        if item.get("start") and item.get("end"):
            group["occurrences"].append(item)
            group["occurrence_count"] += 1

    for key, item in activities.items():
        canonical = reference("activity", key, item["title"], item.get("subtype") or item["category"], item, target={"kind": "activity", "id": key})
        add(canonical, "activity:" + key, canonical)
    for key, definition in definitions.items():
        assignment = assignments.get(key)
        # A selected-week override replaces that week's untimed association;
        # actual saved visits below still retain their own physical location.
        item = assignment["effective_definition"] if assignment else definition
        target = {"kind": "task", "id": key}
        if assignment and {"location_id", "location_mode", "room", "allow_alternative_locations", "alternative_location_ids", "location_requirements"}.intersection(assignment.get("overrides", {})):
            target.update(assignment_id=assignment["id"], week_start=first.isoformat())
        canonical = reference("task_definition", key, item["title"], item["task_type"], item, target=target)
        add(canonical, "task:" + key, canonical)
    for event in calendar.occurrences_between(db, first, last, settings):
        activity = activities[event["activity_id"]]
        location = {**activity, **(event.get("location_override") or {})}
        saved_visit = visits.get((event["activity_id"], event["id"]))
        if saved_visit:
            block, _ = saved_visit
            location = {**location, **policy(block), "resolved_location_id": block["resolved_location_id"],
                        "room": block.get("room", ""), "building": block.get("building", "")}
        item = reference("occurrence", event["id"], activity["title"], activity.get("subtype") or activity["category"], location, event["start"], event["end"], {"kind": "occurrence", "id": event["id"], "activity_id": activity["id"]})
        canonical = reference("activity", activity["id"], activity["title"], item["type"], location, target={"kind": "activity", "id": activity["id"]})
        add(item, "activity:" + activity["id"], canonical)
    for row in schedules:
        for block in task_library.saved_block_metadata(db, row.payload.get("blocks", [])):
            if (block.get("task_definition_id") or block.get("task_id")) in deleted_tasks:
                continue
            if block.get("kind") not in ("task", "project", "personal") or block.get("status") == "skipped":
                continue
            start = calendar.instant(block["start"]).astimezone(zone).date()
            end = (calendar.instant(block["end"]) - timedelta(microseconds=1)).astimezone(zone).date()
            if end < first or start > last:
                continue
            protected = block.get("locked") or block.get("status") in ("completed", "in_progress") or end < today
            if views[row.id].get("status") == "stale" and not protected:
                continue
            item = reference("schedule_block", block["id"], block["title"], block["kind"], block, block["start"], block["end"], {"kind": "schedule", "id": row.id, "date": row.date, "block_id": block["id"]})
            task_id = block.get("task_definition_id") or block.get("task_id")
            activity_id = block.get("activity_id")
            if task_id:
                definition = definitions.get(task_id, block)
                canonical = reference("task_definition", task_id, definition["title"], definition.get("task_type", block["kind"]), definition, target={"kind": "task", "id": task_id})
                identity = "task:" + task_id
            elif activity_id:
                activity = activities.get(activity_id, block)
                canonical = reference("activity", activity_id, activity["title"], activity.get("subtype") or activity.get("category", block["kind"]), activity, target={"kind": "activity", "id": activity_id})
                identity = "activity:" + activity_id
            else:
                canonical, identity = item, "schedule_block:" + block["id"]
            add(item, identity, canonical)
    unlocated = []
    for (bucket, _), group in groups.items():
        group["occurrences"].sort(key=lambda item: (item["start"], item["id"]))
        if bucket in places:
            places[bucket]["references"].append(group)
            places[bucket]["reference_count"] += 1
        else:
            unlocated.append(group)
    return {"week_start": first.isoformat(), "week_end": last.isoformat(), "locations": list(places.values()), "unlocated": unlocated}


def create_router(session_dependency, settings_of):
    router = APIRouter(prefix="/api")

    @router.get("/location-overview")
    def location_overview(week_start: date | None = None, db=Depends(session_dependency)):
        settings = settings_of(db)
        return overview(db, week_start or datetime.now(ZoneInfo(settings["timezone"])).date(), settings)

    @router.get("/location-search")
    def location_search(query: str = Query(min_length=1, max_length=200), db=Depends(session_dependency)):
        words = query.strip().casefold().split()
        matches = []
        for row in db.scalars(select(Entity).where(Entity.collection == "locations").order_by(Entity.id)):
            item = schemas.Location.model_validate(row.payload).model_dump(mode="json")
            text = " ".join(str(item.get(key, "")) for key in ("name", "address", "building", "room", "floor", "entrance", "notes", "aliases")).casefold()
            if all(word in text for word in words):
                matches.append(item)
        return {"results": matches}

    return router
