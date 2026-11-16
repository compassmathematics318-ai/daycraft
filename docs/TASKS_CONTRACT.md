# Weekly task definitions, assignments and logical sessions

Explicit confirmation of saved work blocks, reversal, regeneration preservation
and independent workload preferences are detailed in
[SESSION_COMPLETION_WORKLOAD.md](SESSION_COMPLETION_WORKLOAD.md).

This extension keeps projects contextual and calendar occurrences authoritative.
Explicit weekly assignments and eligible recurring definitions supply schedulable work. Weeks begin
Sunday and end Saturday in the settings IANA timezone, including year boundaries.

## Every Week and copying assignments

The management tabs are Every Week, Week Specific, and Task Library. All three
use the same task definitions. An optional `recurrence` object contains
`kind: weekly`, optional Sunday-normalized `start_week`/`end_week`, and
`interval_weeks` (default 1). Creation/conversion defaults the start to the
current local week. Recurring definitions reject absolute one-time dates.
Relative weekly deadlines are not implemented.

Weekly reads expand eligible definitions in memory, with stable assignment IDs
`recurring:<definition_id>:<Sunday>`. Reads do not insert rows. Only scheduling,
progress or an explicit exception materializes an assignment. Existing explicit
assignments win the unique definition/week identity; recurrence never adds a
second copy. Assignment responses include `source`, `is_virtual`, `overrides`
and `effective_definition`. Per-week skips retain sessions and history. Status
and validated metadata overrides affect only that week. Session credit and
target-minute snapshots remain attached to their original logical sessions.

`POST /api/task-weeks/copy` accepts `source_week`, `target_week`, optional
`definition_ids`, required `deadline_policy: preserve|shift`, and `preview`.
The response includes `copied`, `skipped`, and destination `week`. Preview is
read-only. Copying preserves definition identity and effective weekly settings,
creates no sessions or calendar intervals, resets assignment status to todo,
excludes recurring definitions, and leaves destination duplicates untouched.
Date shifting is an explicit local-calendar week offset, never inferred.

This extension uses the existing JSON metadata columns and foreign-key tables;
no destructive schema change or new independent task store is needed. Migration
0005_task_recurrence records the capability upgrade without changing existing
payloads or tables; 0004 records remain unchanged on upgrade.
Preferred weekdays apply a soft nonpreferred-day penalty in weekly pacing;
task time-of-day preferences guide daily placement ahead of the global energy
preference. Neither is a hard availability restriction.

## Canonical model and API

TaskDefinition stores reusable metadata separately from frequency/progress:
`id,title,task_type,session_minutes,importance,difficulty,description,project_id,
academic_subtype,due_at,assessment_at,deadline_at,related_activity_id,course,
earliest_start,allow_splitting,min_chunk_minutes,dependencies,preferred_start,
preferred_end`. Types are academic, personal, project_work, administrative,
wellness and other. Academic subtypes are studying, assignment,
assessment_preparation, reading and other. Due and assessment timestamps are
independent; no date is inferred from a name or project. A general nonacademic
deadline is optional. Importance uses 1–10, difficulty 0–10, both exact half steps.
Session duration is a positive safe integer, with no arbitrary application cap
or five-minute divisibility requirement. Starts remain on the planner grid;
session work may end at an exact minute.

TaskWeek has `id,task_definition_id,week_start,min_sessions_per_week,status`.
The minimum is an integer >=0 and a best-effort target, never an exact quota or
unconditional feasibility constraint. Assignment status is todo, in_progress,
completed or paused and affects that week only. A definition can be assigned to
several weeks without cloning its metadata or sharing weekly progress.

LogicalSession references one assignment and records a stable identity, target
minutes and completion. TaskChunk references the session and saved schedule and
records the actual block interval/status. Completion is credited exactly once;
a session is complete only when its total credited work reaches its target.
Unfinished sessions never count as full completed/fully scheduled sessions.
All intervals and progress changes are synchronized transactionally with planner
edits/regeneration. Existing scheduled work on other dates reserves that work.
This includes past chunks that remain pending: the app does not assume that
unreported work was missed or completed. Mark a genuinely missed chunk Skipped
to release its reserved minutes for replanning. This prevents old pending work
and new allocations from exceeding one logical session's target.

`/api/task-definitions` supports CRUD. `/api/task-weeks` creates assignments;
`/api/task-weeks/{id}` edits/removes them with protected work retained.
`GET /api/task-week?week_start=YYYY-MM-DD` normalizes any supplied date to Sunday
and returns definitions, assignments, sessions and weekly summary/progress.
`/api/task-sessions/{id}` records explicit completion changes. `/api/state` adds
`task_definitions`. Legacy `/tasks` and state tasks remain compatibility views
over the same canonical definitions/service, not a second scheduling source.
IDs and relationships are FK-validated. Unknown fields are rejected. Deletion
must not silently discard started/completed historical work or project data.

## Migration and compatibility

Migration 0004 preserves original task/project links and immutable legacy
payloads. Existing finite work becomes one current-week assignment/session,
using the original estimate and completed-versus-remaining minutes. Completed
or skipped work has no unmet target. This does not assert a recurring frequency:
no future assignments are invented, and legacy finite work cannot spawn extra
work beyond its original estimate. Existing saved blocks and references remain
intact. The UI explains migrated finite work. Compatibility writes and progress
accounting use the canonical service, so legacy work is never scheduled twice.

## Scheduling policy

Meeting a minimum does not close an assignment or definition. `target_met` is an
allocation indicator, not verified task completion. An explicit Completed week
status stops new work for that week; an explicit completed definition stops new
work in all weeks until reopened. A weekly active override cannot reopen a
completed definition. Raising a met target keeps an open assignment eligible.

`allocated_sessions` (also `planned_sessions`) counts logical sessions whose
verified work plus pending reserved chunks cover the session target. It equals
`completed_sessions + scheduled_sessions`, with each logical session counted
once. `remaining_target_sessions` is the allocation shortfall. For compatibility,
`remaining_minutes` remains target minutes minus verified minutes; it is not an
allocation shortfall. Partial logical sessions do not count as full sessions.
`elapsed_scheduled_minutes` and `future_scheduled_minutes` partition pending
reservations at the current instant without creating verified completion credit.
Time passing, deadlines and target attainment never complete a task. Explicit
completion/reopening preserves the session ledger and remaining estimates,
including through the legacy API. Planner work-block completion and historical
session APIs remain separate from whole-task lifecycle actions. Task cards no
longer offer manual session credit.

Task relationships use the existing nullable `related_activity_id` foreign key.
The searchable picker includes all classes, assessments and commitments. Old
`course` values remain stored and readable, without an editable Course input or
automatic name-based linking. Planning joins current activity metadata and the
week's canonical calendar occurrences; a linked assessment's upcoming date adds
a bounded 0..60 per-minute soft urgency bonus within seven days. This never
creates a hard task deadline, changes its explicit dates, adds occupied time, or
copies the activity's location onto the task. Classes and commitments provide
context only. Activity changes invalidate affected linked plans; deletion clears
the relationship while retaining tasks, course text and historical session data.
No LLM interpretation is used.

Form targets are labeled by context: Every Week uses "Minimum sessions each
week"; Week Specific uses "Minimum sessions for selected week"; Task Library
uses "Default minimum sessions when assigned to a week". Week Specific creation
uses the page's selected week, and edits retain the original assignment week.

An explicitly labeled compatibility exception supports older `/api/tasks`
clients: newly written finite legacy tasks retain their original date-independent
planning behavior until explicitly assigned through `/api/task-weeks`. Their
canonical definition has `scheduling_model=legacy`; it is never also submitted
as weekly work. Existing real records upgraded by migration instead use the
finite current-week assignment described above. An explicit assignment switches
compatibility work to weekly mode while preserving its completion credit.

The existing daily generate endpoint and balanced/deadline/deep modes remain.
For its selected date, the backend supplies the entire containing week: target
shortfalls, full/partial session progress, other dates' scheduled work, future
calendar commitments, cutoff dates and feasible daily capacity. Daily pacing
uses remaining eligible days/capacity and urgency rather than putting every
remaining weekly target into the selected day. Expected infeasible shortfall is
reported explicitly. This is a daily optimization with weekly context, not a
claim of global optimality for all seven days.

Minimum shortfalls have finite weighted objective penalties. Allocating useful
sessions reduces that penalty; urgent competing work can justify fewer sessions.
Finite additional candidates are bounded by actual time capacity. Additional
sessions have diminishing value and require meaningful task importance/urgency;
there is no generic reward for filling every available minute or inflating counts.
Difficulty affects cognitive placement/session fragmentation preference and
workload distribution, not intrinsic value or invented duration. Deterministic
importance, bounded project context, urgency, target shortfall and placement
terms are documented in the scheduling adapter and tested independently.

Hard constraints win: occupied calendar time, travel, recovery, working hours,
dependencies, earliest start and the applicable task cutoff. Preparation cannot
extend past its assessment; due and assessment dates stay separate in storage.
Paused tasks/assignments and paused/archived projects normally exclude new work;
existing explicit project inclusion and protected locked/started work remain.
Deterministic local rules interpret conservative description cues for pacing
and explain their evidence; they never invent dates, durations or completion.

Internal solver units may identify logical sessions, but public block `task_id`
remains the definition ID. Blocks additionally carry logical-session and weekly
assignment IDs. The persistence adapter translates IDs consistently, including
manual validation and preserved blocks. Proposed sessions are only materialized
when actual work is selected; empty candidates are not fictitious task records.

## Deterministic objective terms

Task importance is 1–10 and the bounded project bonus remains 0–90. Urgency is
derived from the applicable explicit due/assessment/deadline proximity over a
14-day gradient, while actual allocation remains inside the assignment week.
Required work has per-minute marginal value
`300 + importance*30 + urgency*40 + project_bonus`; Deadline First uses
`urgency*80`. Extra session index `k` has marginal value
`(importance-6)*20 + urgency*20 + project_bonus/5 - k*30`; Deadline First uses
`urgency*30`. Only positive extra values create candidates, and finite migrated
work never creates extras. Existing generic completion bonuses are disabled for
weekly work so they cannot inflate these explicit preferences.

The weekly model penalizes each attainable missing full target session by
`4000 + importance*600 + urgency*600`. This is finite, and all capacity/deadline
constraints remain hard. Candidate counts are bounded by physical capacity;
unreachable target constants are omitted from solver arithmetic and still appear
in reported shortfalls. Recovery and start-grid overhead inform capacity.
Difficulty changes pacing/placement penalties, not these intrinsic work values.
Bounded linked-assessment context (up to 60), course continuity (up to 10), and
forecast congestion now also inform priorities; linked-assessment and preparation
urgency share a combined 60-point allowance. Recurring missed targets use a
best-effort remaining-week allocation rather than automatic catch-up; the original
target and unmet amount remain visible. Explicit cutoffs retain urgency. See
`INTELLIGENT_SCHEDULING_CONTRACT.md` for workload and rolling-horizon behavior.

## Ownership

Backend owns schema/database/migrations/API/persistence and main integration;
scheduling owns scheduler.py, weekly_scheduler.py and focused algorithm tests;
frontend owns frontend/**; independent QA owns e2e/** after a slot frees. Lead
owns this contract, backup/audits, launcher verification, final integration and
executed results in PROGRESS.md.
