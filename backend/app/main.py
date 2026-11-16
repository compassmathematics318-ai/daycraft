"""Local API and compiled React host."""
import asyncio
import logging
from copy import deepcopy
from contextlib import asynccontextmanager
from datetime import date as Date, datetime
from importlib import import_module
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import calendar as activity_calendar
from . import exports, history, locations as location_service, projects, schemas, suitability, task_library, task_recurrence, work_confirmation
from .database import Activity, Configuration, Entity, Occurrence, Schedule, TaskDefinition, TaskWeek, build_database
from .migrate import migrate
from .meal_planning import identified_meals
from .solver_health import MESSAGES as SOLVER_MESSAGES, check_solver_health

ROOT = Path(__file__).resolve().parents[2]
MODELS = {"classes": schemas.Class, "tasks": schemas.Task, "locations": schemas.Location}
logger = logging.getLogger(__name__)


def fail(message, status=409):
    raise HTTPException(status, message)


def ensure_scheduler_dependencies():
    """Report dependency load failures before changing any persisted plan.

    Keep application imports and solver execution outside this catch: programming
    errors and solver failures must not be misreported as missing dependencies.
    """
    try:
        import_module("ortools.sat.python.cp_model")
    except (ImportError, OSError) as exc:
        logger.exception("Unable to load the CP-SAT scheduling dependency")
        if "application control" in str(exc).lower():
            message = SOLVER_MESSAGES["windows_policy_blocked"] + " Your saved plan has not changed."
        else:
            message = (
                "Scheduling is unavailable because a required solver dependency could not be loaded. "
                "Your saved plan has not changed. Review the dependency error in the server log "
                "and restore the required dependency before retrying."
            )
        raise HTTPException(503, message) from exc


def documents(db, collection):
    if collection == "tasks":
        return task_library.compatibility_tasks(db, settings_of(db))
    values = [row.payload for row in db.scalars(select(Entity).where(Entity.collection == collection).order_by(Entity.id))]
    if collection == "locations":
        return [schemas.Location.model_validate(value).model_dump(mode="json") for value in values]
    return values


def settings_of(db):
    row = db.get(Configuration, "settings")
    value = row.payload if row else schemas.Settings().model_dump(mode="json")
    return {**value, "meals": identified_meals(value.get("meals", []))}


def mark_preferences_stale(db, date=None):
    """Keep saved blocks/history intact while flagging changed planning inputs."""
    message = "Scheduling preferences changed. Regenerate this day to apply the current workload, availability, meals and recovery."
    for row in db.scalars(select(Schedule)):
        if date is None or row.date == date:
            row.payload = {**row.payload, "preferences_dirty": True, "needs_regeneration": True,
                           "explanations": list(dict.fromkeys([*row.payload.get("explanations", []), message]))}


def generation_mode(value, previous=None):
    """An omitted strategy preserves the selected day's existing strategy."""
    saved = previous.get("mode") if previous else None
    return saved if "mode" not in value.model_fields_set and saved in {"balanced", "deadline", "deep"} else value.mode


def state_of(db):
    return {"settings": settings_of(db), "activities": activity_calendar.activities_list(db), "projects": projects.projects_list(db), "task_definitions": task_library.definitions_list(db), **{name: documents(db, name) for name in MODELS}, "schedules": [history.schedule_view(db, row, location_service.schedule_view(row.payload, settings_of(db), db)) for row in db.scalars(select(Schedule).order_by(Schedule.date.desc()))]}


def validate_references(db, collection, value, entity_id):
    if value.get("location_id") and not db.get(Entity, ("locations", value["location_id"])):
        fail("Selected location no longer exists", 422)
    if any(not db.get(Entity, ("locations", key)) for key in value.get("alternative_location_ids", [])):
        fail("An alternative location no longer exists", 422)
    if collection == "locations":
        for key in value["travel_overrides"]:
            if key != entity_id and not db.get(Entity, ("locations", key)):
                fail("Travel override destination does not exist", 422)
    if collection != "tasks":
        return
    if value.get("project_id"):
        from .database import Project
        if not db.get(Project, value["project_id"]):
            fail("Selected project no longer exists", 422)
    graph = {task["id"]: task.get("dependencies", []) for task in documents(db, "tasks")}
    graph[entity_id] = value["dependencies"]
    if any(item not in graph for item in value["dependencies"]):
        fail("A dependency does not exist", 422)
    visiting, visited = set(), set()

    def walk(key):
        if key in visiting:
            fail("Task dependencies cannot contain a cycle", 422)
        if key in visited:
            return
        visiting.add(key)
        for child in graph[key]:
            walk(child)
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        walk(key)


def normalize_task(value, settings):
    if value.get("deadline"):
        deadline = datetime.fromisoformat(value["deadline"])
        if deadline.tzinfo is None:
            zone = ZoneInfo(settings["timezone"])
            local = deadline.replace(tzinfo=zone)
            if local.astimezone(ZoneInfo("UTC")).astimezone(zone).replace(tzinfo=None) != deadline:
                fail("Deadline is in a daylight-saving time gap; choose a valid local time", 422)
            deadline = local
        value["deadline"] = deadline.isoformat()
    return value


async def routes_for(db, settings):
    from .travel import cached_route, estimate_minutes, get_route
    locations = {item["id"]: item for item in documents(db, "locations")}
    active = {item.get("location_id") for name in ("tasks", "classes") for item in documents(db, name)}
    active.update(item.get("location_id") for item in activity_calendar.activities_list(db))
    active.update(item.get("location_id") for item in task_library.definitions_list(db))
    active.update(item.get("location_id") for item in settings.get("meals", []) if item.get("enabled", True))
    active.update(row.location_override.get("location_id") for row in db.scalars(select(Occurrence)) if row.location_override)
    policies = [item for name in ("tasks", "classes") for item in documents(db, name)]
    policies.extend(activity_calendar.activities_list(db))
    policies.extend(task_library.definitions_list(db))
    activity_map = {item["id"]: item for item in activity_calendar.activities_list(db)}
    policies.extend({**activity_map.get(row.activity_id, {}), **row.location_override} for row in db.scalars(select(Occurrence)) if row.location_override)
    for row in db.scalars(select(TaskWeek)):
        definition = db.get(TaskDefinition, row.task_definition_id)
        if definition and not definition.payload.get("deleted_at") and not row.payload.get("removed_from_week"):
            active.add(row.payload.get("overrides", {}).get("location_id"))
            policies.append(task_recurrence.effective_value(db, row, definition)[1])
    for item in policies:
        if item.get("allow_alternative_locations"):
            active.update(item.get("alternative_location_ids", []))
        active.update(suitability.candidate_ids(suitability.enrich(item, locations)))
    if settings.get("start_at_home") or settings.get("end_at_home"):
        active.add(settings.get("home_location_id"))
    # A locked block may retain a location no longer assigned to an activity.
    now = datetime.now(ZoneInfo(settings["timezone"]))
    for schedule in db.scalars(select(Schedule)):
        for item in schedule.payload["blocks"]:
            withdrawn_history = task_library.withdrawn_work(db, item)[2] and activity_calendar.instant(item["start"]) <= now
            elapsed_work = item.get("kind") in {"task", "project"} and item.get("task_id") and activity_calendar.instant(item["end"]) <= now
            if item.get("locked") or item.get("status") in {"completed", "in_progress"} or withdrawn_history or elapsed_work:
                active.update((item.get("location_id"), item.get("resolved_location_id")))
            if item.get("allow_alternative_locations"):
                active.update(item.get("alternative_location_ids", []))
    ids = sorted(item for item in active if item in locations)
    pairs = [(origin, destination) for origin in ids for destination in ids if origin != destination]
    matrix = {}
    for pair in pairs:
        cached = cached_route(locations[pair[0]], locations[pair[1]], settings)
        if cached is not None:
            matrix[pair] = cached
    semaphore = asyncio.Semaphore(3)

    async def fetch(origin, destination):
        async with semaphore:
            matrix[(origin, destination)] = await get_route(locations[origin], locations[destination], settings)

    # Prevent an unexpectedly large location library causing a quadratic network burst.
    if len(pairs) <= 30:
        try:
            await asyncio.wait_for(asyncio.gather(*(fetch(*pair) for pair in pairs if pair not in matrix)), timeout=8)
        except (TimeoutError, OSError):
            pass

    def route_minutes(origin, destination):
        if not origin or not destination or origin == destination:
            return 0
        if origin not in locations or destination not in locations:
            fail("An activity references a missing location")
        route = matrix.get((origin, destination))
        return route["minutes"] if route else estimate_minutes(locations[origin], locations[destination], settings)

    return route_minutes, matrix


def annotate_routes(blocks, matrix):
    for block in blocks:
        if block["kind"] == "travel":
            route = matrix.get((block.get("origin_id"), block.get("destination_id")))
            block["estimated"] = route.get("estimated", True) if route else True
            if block["estimated"] and "Estimated walking time" not in block.get("rationale", ""):
                block["rationale"] = block.get("rationale", "") + " Estimated walking time; includes travel buffer. Verify access and crossings."


def validate_manual(old, new, settings, tasks):
    work_confirmation.validate_manual_evidence(old, new, settings)
    old_by_id = {item["id"]: item for item in old["blocks"]}
    new_by_id = {item["id"]: item for item in new}
    if len(new_by_id) != len(new):
        fail("Schedule blocks must have unique IDs", 422)
    protected = ("start", "end", "kind", "task_id", "class_id", "location_id")

    def same_field(before, after, field):
        if field in ("start", "end"):
            return datetime.fromisoformat(before[field]) == datetime.fromisoformat(after[field])
        return after.get(field) == before.get(field)
    for key, before in old_by_id.items():
        if before.get("locked") or before.get("status") in ("completed", "in_progress") or before["kind"] in ("class", "meal"):
            after = new_by_id.get(key)
            if after is None or any(not same_field(before, after, field) for field in protected):
                fail("Classes, meals, locked blocks and started work cannot be moved or removed. Unlock an unstarted block first.")
    zone = ZoneInfo(settings["timezone"])
    for block in new:
        if datetime.fromisoformat(block["start"]).astimezone(zone).date().isoformat() != old["date"]:
            fail("Blocks must start on the selected schedule date", 422)
        if block.get("task_id") and block["task_id"] not in {task["id"] for task in tasks}:
            prior = old_by_id.get(block["id"])
            history_fields = ("task_id", "kind", "start", "end", "status", "location_id", "location_mode", "resolved_location_id", "logical_session_id", "task_assignment_id", "task_definition_id")
            if not prior or any(not same_field(prior, block, field) for field in history_fields):
                fail("A block references a missing task", 422)
        if block["kind"] in ("task", "project") and not block.get("task_id"):
            fail("Work blocks must reference a task", 422)
        before = old_by_id.get(block["id"])
        if before and any(block.get(field) != before.get(field) for field in ("kind", "task_id", "class_id")):
            fail("A block cannot change activity type or task association", 422)
        if block.get("status") in ("completed", "in_progress") and block.get("task_id"):
            if not before or not same_field(before, block, "start") or not same_field(before, block, "end"):
                fail("Save time changes before marking work started or completed", 422)
        if block["kind"] in ("class", "meal") and block["id"] not in old_by_id:
            fail("Add classes and meals through their dedicated settings", 422)


def account_progress(tasks, old_blocks, new_blocks):
    old = {item["id"]: item for item in old_blocks}
    updated = []
    for task in tasks:
        task = dict(task)
        changed = False
        for block in new_blocks:
            if block.get("task_id") != task["id"]:
                continue
            before = old.get(block["id"], {})
            was_complete, is_complete = before.get("status") == "completed", block.get("status") == "completed"
            if was_complete == is_complete:
                continue
            changed = True
            source = before if was_complete else block
            length = round((datetime.fromisoformat(source["end"]) - datetime.fromisoformat(source["start"])).total_seconds() / 60)
            prior_delta = before.get("completion_remaining_minutes_delta")
            amount = min(length, task["remaining_minutes"]) if is_complete else prior_delta if prior_delta is not None else length
            if is_complete:
                block["completion_remaining_minutes_delta"] = amount
            task["remaining_minutes"] = max(0, min(task["duration_minutes"], task["remaining_minutes"] + (-amount if is_complete else amount)))
        if changed:
            # Crediting a planner block exhausts its finite work estimate; the
            # underlying task remains open until explicitly marked completed.
            if task["status"] != "completed":
                task["status"] = "in_progress"
        updated.append(task)
    return updated


def summarize(schedule, tasks):
    allocated = {}
    excluded = {item["task_id"] for item in schedule.get("excluded_tasks", [])}
    for block in schedule["blocks"]:
        if block.get("task_id") and block.get("status") not in ("completed", "skipped"):
            allocated[block["task_id"]] = allocated.get(block["task_id"], 0) + round((datetime.fromisoformat(block["end"]) - datetime.fromisoformat(block["start"])).total_seconds() / 60)
    def planned_minutes(task):
        return task.get("weekly_planned_minutes", task["remaining_minutes"]) if task.get("weekly_opportunity") else task["remaining_minutes"]
    schedule["unallocated"] = [{"task_id": task["id"], "title": task["title"], "minutes": planned_minutes(task) - allocated.get(task["id"], 0), "reason": "Not allocated on this day. Reduce work, extend availability or choose another day."} for task in tasks if task["id"] not in excluded and task["status"] not in ("completed", "skipped") and planned_minutes(task) > allocated.get(task["id"], 0)]
    if schedule["unallocated"]:
        schedule["status"] = "partial"
    elif schedule["status"] == "partial":
        schedule["status"] = "feasible"
    schedule["stats"] = {**schedule.get("stats", {}), "allocated_minutes": sum(allocated.values()), "unallocated_minutes": sum(item["minutes"] for item in schedule["unallocated"])}
    if schedule.get("calendar_dirty") or schedule.get("projects_dirty") or schedule.get("tasks_dirty"):
        schedule["status"] = "stale"
    return schedule


def create_app(db_path=None):
    engine, session_factory = build_database(db_path)

    @asynccontextmanager
    async def lifespan(application):
        try:
            migrate(engine)
            with session_factory() as db:
                if not db.get(Configuration, "settings"):
                    db.add(Configuration(id="settings", payload=schemas.Settings().model_dump(mode="json")))
                activity_calendar.sync_legacy(db, settings_of(db))
                history.backfill_completions(db, settings_of(db))
                db.commit()
            yield
        finally:
            # Release pooled SQLite handles even if startup or lifespan fails.
            engine.dispose()

    application = FastAPI(title="Schedule Builder", version="1.0.0", lifespan=lifespan)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    application.state.engine = engine
    application.state.session_factory = session_factory

    def session():
        with session_factory() as db:
            yield db

    application.include_router(location_service.create_router(session, settings_of))
    application.include_router(activity_calendar.create_router(session, settings_of))
    application.include_router(projects.create_router(session))
    application.include_router(task_library.create_router(session, settings_of))
    application.include_router(history.create_router(session, settings_of))

    @application.get("/health")
    def health():
        return {"status": "ok", "app": "schedule-builder"}

    @application.get("/api/solver-health")
    async def solver_health():
        # Process liveness above is deliberately separate from real solver readiness.
        result = await run_in_threadpool(check_solver_health)
        return JSONResponse(result, status_code=200 if result["status"] == "operational" else 503)

    @application.get("/api/state")
    def state(db: Session = Depends(session)):
        return state_of(db)

    @application.put("/api/settings")
    def save_settings(value: schemas.Settings, db: Session = Depends(session)):
        if value.default_location_id and not db.get(Entity, ("locations", value.default_location_id)):
            fail("Default location does not exist", 422)
        if value.home_location_id and not db.get(Entity, ("locations", value.home_location_id)):
            fail("Home location does not exist", 422)
        if any(meal.location_id and not db.get(Entity, ("locations", meal.location_id)) for meal in value.meals):
            fail("A meal location no longer exists", 422)
        row = db.get(Configuration, "settings")
        payload = value.model_dump(mode="json")
        payload["meals"] = identified_meals(payload["meals"])
        cosmetic = {"theme", "map_center_lat", "map_center_lon", "map_default_region"}
        before = schemas.Settings.model_validate(settings_of(db)).model_dump(mode="json")
        if any(before.get(key) != item for key, item in payload.items() if key not in cosmetic):
            mark_preferences_stale(db)
        if any(row.payload.get(key, False) != payload[key] for key in ("start_at_home", "end_at_home")) or ((payload["start_at_home"] or payload["end_at_home"]) and row.payload.get("home_location_id") != payload["home_location_id"]):
            location_service.mark_place_stale(db, payload.get("home_location_id"))
        row.payload = payload
        db.commit()
        return row.payload

    @application.get("/api/schedules")
    def schedules(date: str | None = Query(default=None), db: Session = Depends(session)):
        query = select(Schedule).order_by(Schedule.date.desc())
        if date:
            query = query.where(Schedule.date == date)
        return [history.schedule_view(db, row, location_service.schedule_view(row.payload, settings_of(db), db)) for row in db.scalars(query)]

    @application.get("/api/day-preferences/{date}")
    def day_preferences(date: Date, db: Session = Depends(session)):
        row = db.get(Configuration, f"day:{date.isoformat()}")
        return {"date": date.isoformat(), **(row.payload if row else schemas.DayPreferences().model_dump())}

    @application.put("/api/day-preferences/{date}")
    def save_day_preferences(date: Date, value: schemas.DayPreferences, db: Session = Depends(session)):
        key, payload = f"day:{date.isoformat()}", value.model_dump()
        row = db.get(Configuration, key)
        previous = row.payload if row else schemas.DayPreferences().model_dump()
        if previous != payload:
            mark_preferences_stale(db, date.isoformat())
        if row:
            row.payload = payload
        else:
            db.add(Configuration(id=key, payload=payload))
        db.commit()
        return {"date": date.isoformat(), **payload}

    @application.post("/api/schedules/{schedule_id}/blocks/{block_id}/completion")
    def confirm_work(schedule_id: str, block_id: str, value: schemas.BlockCompletion, db: Session = Depends(session)):
        db.execute(text("BEGIN IMMEDIATE"))
        row = db.get(Schedule, schedule_id)
        if not row:
            fail("Schedule not found", 404)
        previous = deepcopy(row.payload)
        work_confirmation.confirm_block(db, row, block_id, value.completed, settings_of(db))
        history.sync_schedule(db, row, settings_of(db), previous)
        db.commit()
        return history.schedule_view(db, row, location_service.schedule_view(row.payload, settings_of(db), db))

    @application.post("/api/schedules/generate")
    async def generate(value: schemas.Generate, db: Session = Depends(session)):
        ensure_scheduler_dependencies()
        db.execute(text("BEGIN IMMEDIATE"))
        from .calendar_scheduler import fixed_blocks_for_day
        from .scheduler import generate_schedule
        from .weekly_scheduler import finalize_weekly_result, internalize_weekly_blocks, prepare_weekly_tasks
        settings = settings_of(db)
        old = db.scalar(select(Schedule).where(Schedule.date == value.date.isoformat()))
        mode = generation_mode(value, old.payload if old else None)
        # Generated classes and meals are fixed in the planner, but their source
        # records remain authoritative when the user edits recurrence or settings.
        preserved = task_library.regeneration_blocks(db, old.payload["blocks"], settings) if old else []
        activities = activity_calendar.activities_list(db)
        occurrences = activity_calendar.occurrences_between(db, value.date, value.date, settings)
        activities = [activity_calendar.enrich_related_context(db, item, occurrences) for item in activities]
        fixed = location_service.enrich_blocks(db, fixed_blocks_for_day(value.date.isoformat(), settings, activities, occurrences))
        activity_map = {item["id"]: item for item in activities}
        started = [item for item in preserved if item.get("status") in ("completed", "in_progress")]
        def already_started(block):
            legacy = activity_map[block["activity_id"]].get("legacy_class_id")
            return any(item.get("occurrence_id") == block["occurrence_id"] or item.get("class_id") == block["class_id"] or (legacy and block.get("calendar_source") != "manual" and item.get("class_id") == legacy) for item in started)
        preserved.extend(item for item in fixed if not already_started(item))
        preserved = task_library.saved_block_metadata(db, preserved)
        route_minutes, matrix = await routes_for(db, settings)
        now = datetime.now(ZoneInfo(settings["timezone"])).isoformat() if value.reoptimize else None
        assessment_ids = set(db.scalars(select(Occurrence.activity_id).where(Occurrence.source == "assessment")))
        upcoming = [{"id": item["id"], "title": item["title"], "course": item.get("course"), "start": item["assessment_start"], "end": item["assessment_end"], "description": item["description"]} for item in activities if item["id"] in assessment_ids and item["category"] == "assessment" and activity_calendar.instant(item["assessment_end"]).astimezone(ZoneInfo(settings["timezone"])).date() >= value.date]
        day_config = db.get(Configuration, f"day:{value.date.isoformat()}")
        workload = (day_config.payload if day_config else {}).get("workload_level", "medium")
        solver_settings = {**settings, "upcoming_assessments": upcoming, "workload_level": workload}
        tasks = documents(db, "tasks")
        legacy_tasks = [item for item in tasks if item.get("scheduling_model") == "legacy"]
        definition_map = {item["id"]: item for item in task_library.definitions_list(db)}
        legacy_tasks = [{**item, "exact_minutes": True, "status": "skipped" if definition_map[item["id"]]["status"] in ("paused", "archived", "completed") else item["status"]} for item in legacy_tasks]
        solver_tasks = [suitability.enrich(item, suitability.saved_places(db)) for item in projects.enrich_tasks(db, legacy_tasks, value.include_inactive_projects)]
        definitions, assignments, sessions, context = task_library.planning_inputs(db, value.date.isoformat(), settings, preserved, value.include_inactive_projects, now=now)
        prepared = await run_in_threadpool(prepare_weekly_tasks, value.date.isoformat(), solver_settings, definitions, assignments, sessions, context, mode)
        solver_tasks.extend(task_library.withdrawn_history_units(db, prepared, preserved))
        result = await run_in_threadpool(generate_schedule, value.date.isoformat(), solver_settings, [], solver_tasks + prepared["tasks"] + prepared.get("_daily_task_limits", []), internalize_weekly_blocks(preserved, prepared), route_minutes, mode, now)
        result = finalize_weekly_result(result, prepared)
        result["workload_level"] = workload
        result["planning_intelligence_version"] = 1
        result["blocks"] = [{key: item for key, item in block.items() if key not in {"_withdrawn_history", "_elapsed_work_history"}} for block in result.get("blocks", [])]
        result = task_library.describe_weekly_exclusions(result, definitions, assignments)
        result["calendar_context"] = {"upcoming_assessments": upcoming, "interpretation": "Assessment metadata is available as context. Preparation remains explicitly scheduled through tasks; descriptions are not interpreted by an AI model."}
        result["project_context"] = projects.context_for(db, tasks)
        result["include_inactive_projects"] = value.include_inactive_projects
        result["task_week_context"] = {"week_start": prepared["week_start"], "week_end": prepared["week_end"], "definitions": definitions, "capacity_days": context["days"]}
        result.update(id=old.id if old else str(uuid4()), date=value.date.isoformat(), mode=mode)
        result["location_intelligence_version"] = suitability.INTELLIGENCE_VERSION
        annotate_routes(result["blocks"], matrix)
        if old:
            result["archive_version_counter"] = old.payload.get("archive_version_counter", 0)
            result["schedule_revision_id"] = history.freeze_revision(db, old)
            old.payload = result
        else:
            result["schedule_revision_id"] = str(uuid4())
            old = Schedule(id=result["id"], date=result["date"], payload=result)
            db.add(old)
        db.flush()
        task_library.persist_chunks(db, old, prepared["sessions"])
        db.commit()
        return history.schedule_view(db, old)

    @application.put("/api/schedules/{schedule_id}")
    async def edit_schedule(schedule_id: str, value: schemas.EditSchedule, db: Session = Depends(session)):
        db.execute(text("BEGIN IMMEDIATE"))
        row = db.get(Schedule, schedule_id)
        if not row:
            fail("Schedule not found", 404)
        previous_payload = deepcopy(row.payload)
        if location_service.schedule_view(row.payload, settings_of(db), db).get("locations_dirty"):
            fail("Saved places changed. Regenerate this day before editing the saved plan.")
        if row.payload.get("calendar_dirty"):
            fail("Calendar commitments changed. Regenerate this day before editing the saved plan.")
        if row.payload.get("projects_dirty"):
            fail("Project context or task associations changed. Regenerate this day before editing the saved plan.")
        if row.payload.get("tasks_dirty"):
            fail("Weekly tasks changed. Regenerate this day before editing the saved plan.")
        if row.payload.get("preferences_dirty"):
            fail("Scheduling preferences changed. Regenerate this day before editing the saved plan.")
        settings = {**settings_of(db), "workload_level": row.payload.get("workload_level", "medium")}
        new_blocks = [block.model_dump(mode="json", exclude_none=True) for block in value.blocks]
        previous_blocks = {item["id"]: item for item in row.payload["blocks"]}
        for model, block in zip(value.blocks, new_blocks):
            # Calendar relationship context is a server-owned snapshot. Permit
            # unchanged round trips and older clients that omit these fields.
            previous = previous_blocks.get(block["id"], {})
            for field in ("related_entity", "related_entity_context", "meal_id"):
                expected = previous.get(field)
                if field in model.model_fields_set and block.get(field) != expected:
                    fail("Calendar relationship context is read-only; edit the library activity instead.", 422)
                if expected is not None:
                    block[field] = expected
                else:
                    block.pop(field, None)
            if "location_requirements" not in model.model_fields_set:
                block["location_requirements"] = previous_blocks.get(block["id"], {}).get("location_requirements", [])
        location_ids = {item["id"] for item in documents(db, "locations")}
        if any(block.get(field) and block[field] not in location_ids for block in new_blocks for field in ("location_id", "origin_id", "destination_id", "resolved_location_id")):
            fail("A block references a missing location", 422)
        tasks = documents(db, "tasks")
        task_library.validate_chunk_identity(db, new_blocks, row.payload["blocks"], row.date)
        new_blocks = task_library.restore_history_snapshots(db, new_blocks, row.payload["blocks"])
        location_service.validate_block_locations(db, new_blocks, row.payload["blocks"])
        new_blocks = location_service.resolve_manual_locations(new_blocks, row.payload["blocks"])
        new_blocks = location_service.enrich_blocks(db, new_blocks, row.payload["blocks"])
        validate_manual(row.payload, new_blocks, settings, tasks)
        ensure_scheduler_dependencies()
        from .scheduler import daily_session_progress
        from .weekly_scheduler import finalize_weekly_result, internalize_weekly_blocks, prepare_weekly_tasks, validate_weekly_blocks
        task_library.validate_chunk_identity(db, new_blocks, row.payload["blocks"], row.date)
        # Old saved JSON stays untouched by migration. Its FK ledger supplies
        # references only when the user actually edits/regenerates the plan.
        new_blocks = task_library.saved_block_metadata(db, new_blocks)
        task_library.validate_chunk_identity(db, new_blocks, task_library.saved_block_metadata(db, row.payload["blocks"]), row.date)
        route_minutes, matrix = await routes_for(db, settings)
        legacy_tasks = [item for item in tasks if item.get("scheduling_model") == "legacy"]
        legacy_tasks = [suitability.enrich(item, suitability.saved_places(db)) for item in account_progress(legacy_tasks, row.payload["blocks"], new_blocks)]
        preserved = [item for item in row.payload["blocks"] if item.get("locked") or item.get("status") in ("completed", "in_progress")]
        definitions, assignments, sessions, context = task_library.planning_inputs(db, row.date, settings, preserved, row.payload.get("include_inactive_projects", False))
        prepared = await run_in_threadpool(prepare_weekly_tasks, row.date, settings, definitions, assignments, sessions, context, row.payload.get("mode", "balanced"))
        prepared = task_library.validation_units(db, prepared, new_blocks, definitions, context)
        legacy_tasks.extend(task_library.withdrawn_history_units(db, prepared, new_blocks))
        trusted_previous = task_library.regeneration_blocks(db, row.payload["blocks"], settings)
        conflicts = validate_weekly_blocks(new_blocks, settings, route_minutes, prepared, legacy_tasks, trusted_previous)
        if conflicts:
            fail({"message": "Schedule changes are not feasible", "conflicts": conflicts})
        new_blocks.sort(key=lambda block: datetime.fromisoformat(block["start"]))
        for task in legacy_tasks:
            if task.get("history_only"):
                continue
            db.get(Entity, ("tasks", task["id"])).payload = {key: item for key, item in task.items() if key not in ("task_definition_id", "scheduling_model", "location_suitability")}
            task_library.sync_legacy_task(db, task)
        internal = internalize_weekly_blocks(new_blocks, prepared)
        result = summarize({**row.payload, "blocks": internal, "conflicts": []}, legacy_tasks + prepared["tasks"])
        result["daily_progress"] = daily_session_progress(internal, legacy_tasks + prepared["tasks"] + prepared.get("_daily_task_limits", []), settings)
        result = finalize_weekly_result(result, prepared)
        # A validated manual edit is not a new optimization result. Do not leave
        # generated tail/capacity facts or optimality bounds attached to new times.
        timing_fields = ("id", "start", "end", "kind", "task_id", "logical_session_id", "status",
                         "location_id", "resolved_location_id", "origin_id", "destination_id")
        def timing_signature(items):
            return sorted((tuple(str(item.get(key, "")) for key in timing_fields) for item in items))
        if timing_signature(new_blocks) != timing_signature(row.payload["blocks"]):
            diagnostic_keys = {"tail_diagnostics", "actual_productive_capacity_minutes", "actual_work_minutes_within_window",
                "actual_unused_productive_minutes", "objective_value", "objective_bound", "objective_absolute_gap",
                "objective_relative_gap", "optional_work_extent_minutes", "optional_completion_extent_minutes",
                "forced_work_extent_occupancy_minutes", "discretionary_work_idle_minutes"}
            result["stats"] = {key: val for key, val in result.get("stats", {}).items() if key not in diagnostic_keys}
            result["stats"].update(optimal=False, termination_reason="manual_edit_validated_without_optimization")
            result["solver_status"] = "NOT_RUN"
            if result["status"] in {"optimal", "feasible"}:
                result["status"] = "feasible"
            result["explanations"] = [line for line in result.get("explanations", [])
                                      if not line.startswith("The returned itinerary leaves ")]
            result["explanations"].append("This edited plan passed constraint validation; it has not been optimized again. Generated tail and optimality diagnostics were cleared.")
        result["blocks"] = [{key: item for key, item in block.items() if key not in {"_withdrawn_history", "_elapsed_work_history"}} for block in result.get("blocks", [])]
        result = task_library.describe_weekly_exclusions(result, definitions, assignments)
        annotate_routes(result["blocks"], matrix)
        row.payload = result
        task_library.persist_chunks(db, row, prepared["sessions"])
        history.sync_schedule(db, row, settings_of(db), previous_payload)
        db.commit()
        return history.schedule_view(db, row)

    @application.get("/api/schedules/{schedule_id}/export")
    def export(schedule_id: str, format: str = Query(default="ics", pattern="^(ics|csv)$"), db: Session = Depends(session)):
        row = db.get(Schedule, schedule_id)
        if not row:
            fail("Schedule not found", 404)
        if location_service.schedule_view(row.payload, settings_of(db), db).get("locations_dirty"):
            fail("Regenerate this day before exporting: its saved venues or travel require validation.")
        content = exports.ics(row.payload, documents(db, "locations")) if format == "ics" else exports.csv_export(row.payload, documents(db, "locations"))
        return Response(content, media_type="text/calendar" if format == "ics" else "text/csv", headers={"Content-Disposition": f'attachment; filename="schedule-{row.date}.{format}"'})

    @application.post("/api/geocode")
    async def geocode(value: schemas.Geocode, db: Session = Depends(session)):
        from .travel import geocode_search
        try:
            settings = settings_of(db)
            places = documents(db, "locations")
            home = next((place for place in places if place["id"] == settings.get("home_location_id")), None)
            center = (home["lat"], home["lon"]) if home else (
                (settings["map_center_lat"], settings["map_center_lon"]) if settings.get("map_center_lat") is not None else None)
            result = await geocode_search(value.query, places, settings.get("map_default_region", "Waterloo, Ontario"), center)
        except (RuntimeError, OSError, ValueError) as exc:
            fail({"results": [], "status": "unavailable", "message": "Place search is unavailable. Check the local service logs and retry.",
                  "diagnostics": [{"stage": "local", "outcome": "unavailable", "reason": type(exc).__name__}]}, 503)
        if result["status"] not in ("ok", "no_results"):
            fail(result, 422 if result["status"] == "invalid_query" else 503)
        return result

    @application.post("/api/route")
    async def route(value: schemas.Route, db: Session = Depends(session)):
        from .travel import get_route
        origin = db.get(Entity, ("locations", value.origin_id))
        destination = db.get(Entity, ("locations", value.destination_id))
        if not origin or not destination:
            fail("Route locations not found", 404)
        return await get_route(origin.payload, destination.payload, settings_of(db))

    @application.post("/api/demo")
    def demo(db: Session = Depends(session)):
        from .demo import seed_demo
        seed_demo(db, settings_of(db))
        for entity in db.scalars(select(Entity).where(Entity.collection == "tasks")):
            if not db.get(TaskDefinition, entity.id):
                task_library.sync_legacy_task(db, entity.payload)
        activity_calendar.sync_legacy(db, settings_of(db))
        db.commit()
        return state_of(db)

    @application.get("/api/{collection}")
    def list_entities(collection: str, db: Session = Depends(session)):
        if collection not in MODELS:
            fail("Collection not found", 404)
        return documents(db, collection)

    def save_entity(collection, payload, entity_id, db):
        if collection not in MODELS:
            fail("Collection not found", 404)
        from pydantic import ValidationError
        explicit_status = collection == "tasks" and "status" in payload
        if collection == "tasks":
            if payload.get("task_definition_id") not in (None, entity_id):
                fail("Task definition identity cannot be changed", 422)
            payload.pop("task_definition_id", None)
            payload.pop("scheduling_model", None)
        if collection == "tasks" and "project_id" not in payload:
            # An older client editing an existing task must not detach it.
            payload["project_id"] = projects.task_project_ids(db).get(entity_id)
        previous_entity = db.get(Entity, (collection, entity_id))
        if collection == "tasks" and "remaining_minutes" not in payload:
            payload["remaining_minutes"] = previous_entity.payload["remaining_minutes"] if previous_entity else payload.get("duration_minutes", 60)
        if previous_entity and collection == "locations":
            for field, default in (("verified_capabilities", []), ("access_confirmed", False), ("verification_notes", "")):
                payload.setdefault(field, previous_entity.payload.get(field, default))
        if previous_entity and collection in ("tasks", "classes"):
            payload = schemas.location_edit(payload, previous_entity.payload, payload)
            if collection == "tasks":
                payload.setdefault("status", previous_entity.payload.get("status", "todo"))
                for field, default in (("min_sessions_per_day", 1), ("max_sessions_per_day", None)):
                    payload.setdefault(field, previous_entity.payload.get(field, default))
        try:
            value = MODELS[collection].model_validate(payload).model_dump(mode="json")
        except ValidationError as exc:
            fail([{k: v for k, v in item.items() if k != "ctx"} for item in exc.errors()], 422)
        if value.get("id") and value["id"] != entity_id:
            fail("Entity ID cannot be changed", 422)
        value["id"] = entity_id
        if collection == "tasks":
            normalize_task(value, settings_of(db))
        if collection == "classes" and value.get("date"):
            zone = ZoneInfo(settings_of(db)["timezone"])
            try:
                for field in ("start_time", "end_time"):
                    activity_calendar.localize(datetime.fromisoformat(f"{value['date']}T{value[field]}"), zone)
            except ValueError as exc:
                fail(str(exc), 422)
        validate_references(db, collection, value, entity_id)
        row = db.get(Entity, (collection, entity_id))
        location_changed = row and collection == "tasks" and any(row.payload.get(field) != value.get(field) for field in ("title", "notes", "location_id", "location_mode", "location_requirements", "allow_alternative_locations", "alternative_location_ids"))
        if row:
            if collection == "locations" and row.payload != value:
                location_service.mark_place_stale(db, entity_id)
            row.payload = value
        else:
            db.add(Entity(collection=collection, id=entity_id, payload=value))
            if collection == "locations" and value.get("access_confirmed") and value.get("verified_capabilities"):
                location_service.mark_place_stale(db, entity_id)
        if collection == "tasks":
            # Insert the task before its FK-backed optional association.
            db.flush()
            projects.set_task_project(db, entity_id, value.get("project_id"))
            task_library.sync_legacy_task(db, value, explicit_status=explicit_status)
            if location_changed:
                task_library.mark_stale(db, "Task location changed. Regenerate to apply its selected venues and travel.")
        if collection == "classes":
            activity_calendar.sync_legacy(db, settings_of(db))
            mirror = db.scalar(select(Activity).where(Activity.legacy_class_id == entity_id))
            activity_calendar._mark_activity_stale(db, mirror, settings_of(db))
        db.commit()
        return next((item for item in documents(db, "tasks") if item["id"] == entity_id), value) if collection == "tasks" else value

    @application.post("/api/{collection}", status_code=201)
    def add_entity(collection: str, payload: dict, db: Session = Depends(session)):
        if payload.get("id"):
            fail("New entities receive an ID from the server", 422)
        return save_entity(collection, payload, str(uuid4()), db)

    @application.put("/api/{collection}/{entity_id}")
    def update_entity(collection: str, entity_id: str, payload: dict, db: Session = Depends(session)):
        if not db.get(Entity, (collection, entity_id)):
            fail("Entity not found", 404)
        return save_entity(collection, payload, entity_id, db)

    @application.delete("/api/{collection}/{entity_id}", status_code=204)
    def delete_entity(collection: str, entity_id: str, db: Session = Depends(session)):
        row = db.get(Entity, (collection, entity_id))
        if not row:
            fail("Entity not found", 404)
        if collection == "locations":
            if location_service.place_in_use(db, entity_id):
                fail("Location is referenced by a task, occurrence, weekly override or saved plan. Reassign it before deleting.")
            if settings_of(db).get("home_location_id") == entity_id:
                fail("Location is your saved home. Choose another home location before deleting.")
            if settings_of(db).get("default_location_id") == entity_id or any(item.get("location_id") == entity_id for name in ("tasks", "classes") for item in documents(db, name)):
                fail("Location is in use. Reassign activities and the default location first.")
            if any(item.get("location_id") == entity_id for item in activity_calendar.activities_list(db)):
                fail("Location is used by a library block. Reassign the block's location first.")
            if any(block.get("location_id") == entity_id for schedule in db.scalars(select(Schedule)) for block in schedule.payload["blocks"]):
                fail("Location is used by a saved schedule. Keep it to preserve travel validation.")
            for origin in db.scalars(select(Entity).where(Entity.collection == "locations")):
                if entity_id in origin.payload.get("travel_overrides", {}):
                    origin.payload = {**origin.payload, "travel_overrides": {key: value for key, value in origin.payload["travel_overrides"].items() if key != entity_id}}
        if collection == "tasks":
            definition = db.get(TaskDefinition, entity_id)
            definition = definition or db.scalar(select(TaskDefinition).where(TaskDefinition.legacy_task_id == entity_id))
            if definition:
                task_library.delete_everywhere(db, definition, settings_of(db))
                db.commit()
                return Response(status_code=204)
        if collection == "classes":
            mirror = db.scalar(select(Activity).where(Activity.legacy_class_id == entity_id))
            if mirror:
                activity_calendar._mark_activity_stale(db, mirror, settings_of(db))
        db.delete(row)
        if collection == "classes":
            db.flush()
            activity_calendar.sync_legacy(db, settings_of(db))
        db.commit()
        return Response(status_code=204)

    frontend = ROOT / "frontend" / "dist"
    if (frontend / "assets").is_dir():
        application.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @application.get("/{path:path}")
    def frontend_app(path: str):
        if path.startswith("api/"):
            fail("API route not found", 404)
        index = frontend / "index.html"
        if not index.is_file():
            fail("Frontend is not built. Run the Windows launcher to install and build it.", 503)
        return FileResponse(index)

    return application


app = create_app()
