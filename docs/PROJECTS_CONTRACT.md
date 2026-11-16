# Contextual projects and schedulable tasks

Projects describe long-term goals. Tasks remain the only units of project work
that consume planner time. New project definitions never create tasks or calendar
blocks automatically.

## API and persistence

`GET /api/state` adds `projects`. `/api/projects` supports list/create and
`/api/projects/{id}` supports update/delete.

Project fields: `id`, required nonblank `name`, `affiliations: string[]`, optional
`start_date` and `end_date`, `contributors` (positive integer, default 1),
`importance` (1–10, step 0.5, default 5), `difficulty` (0–10, step 0.5, default 5),
`status` (`planning|active|paused|completed|archived`, default active), `category`
(`academic|software|research|extracurricular|personal|other`, default personal),
`description`, `goals`, and `links: string[]`. Dates are inclusive planning
context; end cannot precede start. Links use HTTP(S). Unknown input fields are
rejected. Server-owned migration provenance is excluded from edit payloads.

Task adds nullable `project_id`, validated against existing projects and backed
by a database foreign-key relationship. Unlinking retains the task. Deleting a
linked project is rejected unless `?detach_tasks=true` is explicitly requested;
that operation unlinks and retains every task. No project deletion cascades to
task deletion.

Migration 0003 separates every legacy `kind=project` work item into a contextual
project plus its **existing** linked task. Task identity, estimates, remaining
work, deadlines, dependencies, location, notes and saved schedule references
remain intact. An immutable legacy snapshot preserves the original payload.
No additional work estimates or tasks are fabricated. The UI explains the
preserved legacy work. New legacy-kind task writes remain tasks; they do not
create containers implicitly.

Legacy project importance starts at the old task priority × 2, clamped to 1–10;
other contextual fields receive documented defaults. The original task's own
priority and deadline remain intact. Legacy dates are not guessed from task
deadlines. Project/context edits and association changes mark saved plans
`projects_dirty`/stale while retaining their blocks; regenerate before manual
planner editing. An omitted `project_id` on an existing task PUT preserves the
association, while explicit null unlinks it.

## Optimization

Weekly task definitions use the combined objective and session model in
[TASKS_CONTRACT.md](TASKS_CONTRACT.md). The 1–5 task-priority comparison below
describes the retained finite-task compatibility path; weekly task importance
and soft-target weights are documented in that newer contract.

The pure scheduler signature is unchanged. The backend joins each task's project
into `task.project`, exposing the complete metadata to the scheduling adapter.
Project importance adds `round((importance - 1) * 10)` to the per-minute objective
value, a bounded 0–90 bonus. One task-priority level contributes at least 100;
existing mode-specific urgency terms remain. The old bonus based solely on
`kind=project` is replaced. This is a soft objective preference: hard deadlines,
availability, dependencies, travel, breaks and fixed commitments remain hard
constraints. Existing balanced, deadline and deep-work modes remain available.

Paused and archived project tasks are normally excluded from new automatic work.
`POST /api/schedules/generate` accepts `include_inactive_projects: boolean=false`
for an explicit override; the adapter sets `task.schedule_inactive_project`.
Locked and started historical work remains protected. Excluded work is reported
separately with a reason rather than silently disappearing. A completed project
does not automatically complete, delete or suppress its unfinished tasks.

Difficulty supplies context and an effort cue; it never changes task durations.
Project dates never replace task deadlines. Contributors and affiliations never
imply another person's availability. Descriptions and goals are persisted and
exposed as context; no semantic interpretation or AI recommendations are claimed.

## User interface

Projects have a separate compact contextual form, search/filter/sort cards, a
detail view, linked task navigation and completion progress. Task forms own all
duration, session, deadline and availability controls and can link/unlink projects.
All actual tasks, including preserved legacy work, appear in Tasks & Deadlines.
Project progress derives from explicitly completed linked tasks, with no progress
percentage for a project that has no tasks. All four existing themes and narrow
viewports must remain accessible.
