# Saved work confirmation and workload preferences

Implemented 2026-11-12. This extends the existing task/week/session/chunk model.
No new progress table, destructive migration or AI service was introduced.
The subsequent intelligent-scheduling upgrade adds workload objectives while
preserving the completion ledger described below.

## Explicit confirmation

`POST /api/schedules/{schedule_id}/blocks/{block_id}/completion` accepts only
`{"completed": true}` or `{"completed": false}` and returns the updated schedule.
The operation uses a saved task/project work block and its stable task, weekly
assignment, logical session and chunk identities. The server validates the
stored interval, ledger identity and current status before a transaction commits.

New confirmation requires the stored block's end to be at or before the server's
current instant. Timestamps include offsets; settings supply the user's timezone.
The dedicated endpoint cannot change timing, task identity or venue. General
schedule edits also reject future confirmation and simultaneous rescheduling plus
confirmation. Confirmation metadata is server-owned. A repeated confirmation is
idempotent and retains its original timestamp.

Each confirmed chunk credits its actual duration in the existing ledger. Logical
completion follows reconciled confirmed minutes and preserved historical baseline
credit; one partial chunk cannot complete a longer logical session. Undo removes
only that block's credit and restores its preceding status. Original manual
baseline credit is retained. Counts can exceed weekly targets; neither elapsed
time nor attained targets change the underlying task's explicit lifecycle.

Blocks store `completion_confirmed_at`, `completion_previous_status`, and
`completion_verified`. Older confirmed records retain their status without an
invented timestamp. They can be undone, including correction of an old future
completion. Existing finite legacy work without a chunk ledger uses its existing
remaining-minute counter; server-owned `completion_remaining_minutes_delta`
records the exact contribution for reversal, including zero when the estimate
was already exhausted. It does not fabricate historical logical sessions.

The API rejects missing or contradictory weekly ledger identities instead of
inventing credits. Withdrawn/deleted historical work with valid original ledger
identity can be confirmed or undone without restoring the task to active lists,
recurrence, the map or a removed week. Its timing and venue remain protected.

Completion refreshes the saved week's display projections from verified credit
and existing reservations. These are explicitly marked as ledger projections,
not a newly executed capacity forecast. Daily block counts use the same pure
counter as the scheduler. No solver is needed to confirm actual work.

## Regeneration

Completed, started and protected work retains its identity and recorded venue.
Elapsed unconfirmed task blocks also survive regeneration so they remain
available to confirm later. The trusted private `_elapsed_work_history` marker
is derived only from server records and is removed from public results.

Preserved unconfirmed chunks reserve their existing logical-session minutes but
earn no completion credit. Confirmed chunks consume completed minutes; only the
remaining portion of a split session is eligible for new allocation. Extra
logical sessions can still be considered beyond the soft weekly target. Venue,
travel, task priority and daily block-limit constraints remain in the CP-SAT
path. This integration has authored solver regressions; execution is currently
blocked as recorded in `PROGRESS.md`.

## Workload preferences and applied plans

`GET /api/day-preferences/{date}` returns
`{"date":"YYYY-MM-DD","workload_level":"medium"}` when no preference exists.
`PUT` accepts only `workload_level` with one of:

- `very_low` — Very Low
- `low` — Low
- `medium` — Medium
- `high` — High
- `very_high` — Very High

Preferences use the existing Configuration store under `day:YYYY-MM-DD` and can
be saved before a plan exists. They persist across app restarts and synchronize
the Overview and Daily Planner controls for the selected date. Invalid values
and optimization-mode fields are rejected.

These preferences change soft opportunity costs, comfortable productive-day
length, evening costs, focus preferences and optional recovery. They never
relax fixed commitments, required travel, availability or essential recovery.
`balanced`, `deadline` and `deep` remain separate
optimization strategies. Generation preserves an existing saved strategy if
mode is omitted; an explicitly supplied supported mode wins. A new day defaults
to balanced. The frontend passes the selected day's existing strategy and never
sends a workload value as a mode. Generated plans persist their applied
`workload_level`; changes to that date's preference flag the saved plan for
regeneration without changing its blocks or completion history. See
`INTELLIGENT_SCHEDULING_CONTRACT.md` for the implementation contract.

## Manual verification after the dependency block is resolved

1. Open an elapsed task block in Daily Planner and choose **Mark Session
   Completed**. Reload: the checkmark and verified weekly credit should remain.
2. Confirm one chunk of a split session. It credits minutes, not a whole session
   until the logical session's required work is confirmed. Undo reverses it.
3. Open a future task block: positive confirmation is unavailable. A class,
   travel interval or break has no task confirmation action.
4. Select High on Overview, switch to Daily Planner on the same date, then
   switch dates and reload. Each date retains its own choice, with Medium for
   an unset date. Generate equivalent inputs at all five levels and compare
   meaningful work, recovery and free time while checking identical hard anchors.
5. Reoptimize: confirm that past reserved and completed blocks remain, no
   completed logical work is duplicated, and selected venues/travel are valid.

Automated browser evidence uses an isolated real backend/database with explicit
saved-plan fixtures labelled `SEEDED_QA_FIXTURE_NOT_GENERATED`. It is not evidence
that CP-SAT generation succeeded. Personal-data replay uses only a database copy
and an explicit later test clock for confirmation; no real work is asserted as
completed and no personal record is changed.
