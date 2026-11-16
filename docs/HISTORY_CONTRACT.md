# Schedule Archive and Completed Tasks

## Ownership and preservation

The active `schedules` table remains the only daily plan source for scheduling.
Archives and completion history are independent historical projections, never
additional scheduler reservations or a second completion-credit ledger.
`TaskChunk`, `LogicalSession`, and the existing finite-task remaining-minute
counter continue to own progress. No elapsed interval implies completion.

Before implementation, an online SQLite backup and source snapshot were made in
`test-results/archive-history/20261113-230123/`. The database contained three
daily plans and six explicitly confirmed blocks. Integrity and foreign-key
checks passed. Destructive verification uses isolated databases.

## Archive lifecycle

`POST /api/schedule-archives` takes `{schedule_id, new_version?: false}`.
The first save captures a self-contained schedule with its generation metadata,
workload, strategy, blocks, explanations and task/project/activity/place context.
Repeated saves of an attached revision return its existing archive identity.
An explicit new version freezes the preceding archive and attaches a new one.
Saved entries have visible version numbers; the active schedule carries a
monotonic version counter and an independent working-revision identity.

The Daily Planner's archive controls sit inside the timeline container directly
after its last activity. **Save to Schedule Archive** names the displayed plan's
date and uses the server's latest successfully persisted schedule, not a browser
copy. Attached plans show **Saved to Archive** with autosync, View in Archive,
and the existing explicit Save New Version action. Saving a stale plan preserves
its current state; it never requests regeneration. Save controls are guarded
against repeated submission and disabled during generation.
The primary button stays in place as a disabled **Saved to Archive** control
after success; version creation appears separately so a fast second save click
cannot create an unintended version.

Successfully validated planner edits and explicit confirmations update the
attached archive in the same transaction as the active schedule and its progress
ledger. The server does not wait for browser unload or process shutdown.
Definition metadata in a historical snapshot is retained independently; library
changes must not rewrite historical titles, descriptions, times or places.
Background stale marking does not replace historical activities.

Regeneration/reoptimization assigns a new working revision and detaches the
previous archive. Old snapshots remain readable and the replacement plan can be
saved separately. Current working plans and historical versions are visibly
distinguished. Deleting an archive deletes only that snapshot, never schedules,
tasks, projects, activities, progress or other archives.

`GET /api/schedule-archives` accepts `q`, `date_from`, `date_to`,
`workload_level`, `limit` and `offset`, returning date-descending entries and
filtered totals. `GET /api/schedule-archives/{id}` returns a complete snapshot;
`DELETE` removes that specific archive. Historical display uses snapshot
metadata rather than live joins.

Each card exposes **Delete from Archive**. The confirmation dialog identifies
the date, version and save time, initially focuses Cancel, supports Escape before
submission, and requires **Delete Permanently**. A pending deletion cannot be
submitted twice. The list refreshes after a successful response; backend errors
retain the record and allow retry. Only the archive row is deleted. The active
schedule's derived archive link then disappears, while its stored plan, blocks,
progress ledger and other archived versions remain untouched.
After deletion, the current page is refilled without skipping records at page
boundaries. Delayed refreshes cannot replace a newly selected filter's results.

## Confirmed work

`GET /api/completed-tasks` accepts `q`, `date_from`, `date_to`, `limit` and
`offset`. Dated results are grouped by the explicit confirmation instant in the
user's configured IANA timezone, independently of the original scheduled date.
Rows identify the original block, weekly assignment and logical session and
retain historical task/project/activity/place metadata. A partial split chunk
contributes only its confirmed minutes; it does not count as a fully completed
logical session or finish the task definition.

Startup recovers existing explicit confirmation evidence without asking the user
to reconfirm work. Repeated confirmations retain identity and timestamp. Explicit
undo removes the item from the current confirmed-work view while retaining audit
metadata. Existing actual-work baselines without a recorded confirmation date
must be disclosed as undated; no completion instant is inferred. Whole-task
lifecycle status and weekly target attainment do not fabricate work events.

The additive `0008_schedule_history` migration creates `schedule_archives` and
`completed_work`. Their source IDs are independent historical references with
no deletion cascades. Unique constraints prevent duplicate revision saves and
duplicate source work records. Nullable confirmation timestamps preserve undated
evidence honestly. Date indexes support historical lookup; list endpoints expose
pagination and totals for the entire matching selection. Source progress tables
and solver inputs remain unchanged.

Schedule API responses add `schedule_revision_id`, `archive_id` and
`archive_updated_at`. Archive responses include `version_number`, save/update
timestamps, attachment status, workload, strategy, summaries and the full
snapshot payload. Completed-work responses include original scheduled bounds,
actual confirmation date, confirmed minutes and historical associations.
`logical_sessions_completed` means currently completed logical sessions associated
with the filtered work, not a fabricated historical whole-session completion date.

New explicitly logged manual work may be shown separately from scheduled chunks;
it has no invented scheduled interval. Historical snapshots survive definition
edits, withdrawal from a week, task deletion and archive deletion. Optional links
to current tasks/plans or archives do not act as cascading ownership references.

## Completion reversal from history (2026-11-14)

`POST /api/completed-tasks/{id}/reverse` uses the stable history record ID and
returns `{id, reversed: true, changed, reopened_at}`. Repeated requests are
idempotent. The transaction withdraws only that record's chunk or manual credit,
reconciles logical-session progress, and restores a linked block's preceding
unconfirmed status. Task lifecycle status and unrelated work remain unchanged.
History retains its audit record but excludes reopened work from confirmed totals.
Affected plans are marked stale; reversal never invokes generation.

Completed Tasks requires an explicit confirmation dialog before calling this
endpoint. It identifies the task and its original scheduled time in the configured
timezone, initially focuses Cancel, traps keyboard focus, and supports Escape to
cancel before submission. Backdrop clicks do not dismiss or confirm. An in-flight
guard and disabled actions prevent duplicate submissions; failed requests leave
the dialog and current progress intact. Success is announced only after the API
confirms the reversal. A subsequent refresh failure is reported separately.

Weekly progress belongs to the original Sunday-based assignment identity, not
the confirmation date. Thus confirming Saturday's work on Sunday displays the
record under Sunday's confirmation date while crediting Saturday's assignment.
Every Week definitions create independent effective assignments for each week;
Week Specific assignments appear only in explicitly assigned weeks. No Sunday
reset job deletes or zeroes history. Reversing earlier work updates that earlier
assignment, preserving other weeks and the underlying task's lifecycle status.

An attached archive follows the explicit change to its current plan. Detached
historical versions retain their recorded completion state. Future generation
reads the corrected existing progress ledger, without new optimization weights.

## Verification

Backend tests cover migration/backfill, transactional archive updates, immutable
metadata, revisions/regeneration/staleness, idempotent completion and reversal,
split-session and weekly accounting, deletion boundaries, filtering and timezone
dates. Browser tests exercise both pages, planner saves, completion, navigation,
themes and responsive layouts. Restart verification uses real server processes
and durable SQLite files. Actual command results are recorded in `PROGRESS.md`
only after execution.
