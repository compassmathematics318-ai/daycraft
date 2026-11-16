# API / scheduling contract

Saved-block completion/undo and per-date workload metadata are specified in
[SESSION_COMPLETION_WORKLOAD.md](SESSION_COMPLETION_WORKLOAD.md). Workload levels
remain separate from optimization strategies and now affect soft scheduling objectives.
Flexible meals, rolling forecasts and auditable contextual priorities follow
[INTELLIGENT_SCHEDULING_CONTRACT.md](INTELLIGENT_SCHEDULING_CONTRACT.md).

The canonical weekly task definition, assignment, logical-session and chunk APIs
are specified in [TASKS_CONTRACT.md](TASKS_CONTRACT.md). New task UI and daily
planning use those records. The `/tasks` payload below remains an explicitly
labeled compatibility API for older clients; it is not a second work source.

Stable activity relationships, allocation versus verified work, and explicit
task lifecycle semantics are detailed in [TASK_RELATIONSHIPS.md](TASK_RELATIONSHIPS.md).
Marking a task completed never synthesizes work evidence; elapsed reservations
and met weekly targets do not complete the task.

Removal versus deletion, stopped recurrence, library association summaries and
typed commitment links are specified in
[TASK_LIFECYCLE_AND_RELATIONS.md](TASK_LIFECYCLE_AND_RELATIONS.md).

Daily work-block limits, grouped map activities and conditional room fields are
specified in [DAILY_BLOCKS_CONTRACT.md](DAILY_BLOCKS_CONTRACT.md). Daily limits
count split chunks separately; weekly session targets retain logical accounting.

Physical venue permissions, explicit suitable alternatives, configured versus
actual venues and stale-plan protections are specified in
[VENUE_INTEGRITY.md](VENUE_INTEGRITY.md).
Verified capabilities, activity requirements, server-derived suitable candidates,
and flexible-node travel are specified in
[SEMANTIC_LOCATIONS.md](SEMANTIC_LOCATIONS.md).

The activity definition/occurrence extension and preserved legacy class semantics are documented in [CALENDAR_CONTRACT.md](CALENDAR_CONTRACT.md). The `/classes` API below remains available for legacy weekly series. New library definitions use `/activities`; actual dated meetings use `/occurrences` and `/calendar`.

All JSON. API prefix `/api`. IDs strings UUID. Times local `HH:mm`, dates `YYYY-MM-DD`; datetime ISO with offset or local interpreted using settings.timezone. All entity payloads include `id` assigned by server. Frontend fetch errors show meaningful detail.

GET `/health` => `{status:'ok',app:'schedule-builder'}`. GET `/api/state` => `{settings,classes,tasks,locations,schedules}`. GET/POST `/api/{classes,tasks,locations}`; PUT/DELETE `/api/{collection}/{id}`. PUT `/api/settings`. POST `/api/demo` explicit additive sample. GET `/api/schedules?date=...`; POST `/api/schedules/generate` body `{date,mode:'balanced'|'deadline'|'deep',reoptimize:false}` => schedule. PUT `/api/schedules/{id}` body `{blocks:[...]}` validates edits and saves. GET `/api/schedules/{id}/export?format=ics|csv`. POST `/api/geocode` body `{query}` => `{results:[{name,lat,lon}]}`. POST `/api/route` body `{origin_id,destination_id}` => `{minutes,distance_m,estimated,source,coordinates:[[lat,lon],...]}`.

Settings: `{timezone:'America/Toronto',wake_time:'07:00',sleep_time:'23:00',work_start:'08:00',work_end:'22:00',focus_minutes:50,break_minutes:10,travel_buffer_minutes:5,walking_speed_kmh:4.5,default_location_id:null,theme:'light',meals:[{id:'breakfast',name:'Breakfast',duration_minutes:30},{id:'lunch',name:'Lunch',duration_minutes:45},{id:'dinner',name:'Dinner',duration_minutes:30}]}`. Meals default to enabled; optional `location_id` names an actual required venue. Legacy optional `time` values round-trip as soft timing preferences. Existing profiles retain their saved meal definitions and durations.

Settings also includes `energy_preference:'any'|'morning'|'afternoon'|'evening'` (default any), a soft work placement preference.

Location: `{id,name,lat,lon,notes:'',travel_overrides:{destinationId:minutes}}`.

Class: `{id,title,class_type:'Lecture',date:null,weekdays:[0,2],start_time:'09:00',end_time:'10:00',start_date:null,end_date:null,exceptions:[],location_id:null,building:'',room:''}`. Weekdays Monday=0. A specific date takes precedence over weekdays. Recurrence dates inclusive.

Task: `{id,title,kind:'academic'|'project',project_id:null,duration_minutes:120,remaining_minutes:120,priority:3,deadline:null,hard_deadline:true,splittable:true,min_session_minutes:25,max_session_minutes:90,dependencies:[],location_id:null,status:'todo'|'in_progress'|'completed'|'skipped',preferred_start:null,preferred_end:null,notes:''}`. Priority 1..5. Remaining tracks work not completed, schedule allocation does not mark completed. `kind=project` remains a compatible work-task type; contextual projects now have their own `/api/projects` collection. See [PROJECTS_CONTRACT.md](PROJECTS_CONTRACT.md) for metadata, associations, migration and scheduling policy.

Block: `{id,title,kind:'class'|'task'|'project'|'break'|'meal'|'travel'|'personal',start:'ISO',end:'ISO',location_id:null,task_id:null,class_id:null,locked:false,status:'todo'|'in_progress'|'completed'|'skipped',rationale:'',estimated:false}`. Travel block may include origin_id/destination_id. Schedule `{id,date,mode,status:'optimal'|'feasible'|'partial'|'infeasible'|'timeout',solver_status,blocks:[],unallocated:[{task_id,title,minutes,reason}],conflicts:[],explanations:[],stats:{}}`. Schedule date local, blocks timezone-aware.

Scheduler pure function signature:
`generate_schedule(date: str, settings: dict, classes: list[dict], tasks: list[dict], blocks: list[dict], route_minutes: Callable[[str|None,str|None],int], mode: str='balanced', now: str|None=None) -> dict`
Input blocks are preserved locked/completed/in_progress commitments from previous schedule (backend filters), completed/skipped task minutes reconciled by backend on status transition. Default location fills nulls for travel. Route duration includes settings buffer added by scheduler. Return no ID needed; backend assigns ID. Return partial schedule only when all returned blocks satisfy hard constraints; detect fixed conflicts explicitly without pretending they are feasible.

Backend manual validation may reuse `validate_blocks(blocks, settings, route_minutes, tasks=None)` exported from scheduler returning list of strings. Travel blocks cover route time between commitments; must not double-count travel. Future locked blocks survive regeneration. No location means remote/default.
