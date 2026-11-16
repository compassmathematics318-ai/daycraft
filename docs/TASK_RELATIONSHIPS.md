# Task relationships and allocation semantics

Task definitions retain the existing nullable activity foreign key. All activity
categories can be linked through the shared searchable picker, including weekly
overrides. Renames use current activity metadata. Deletion clears live links but
does not delete tasks, assignments or work history. Previously entered course
text remains stored and visible as legacy context; it is not matched to names.

The planning adapter joins the current related activity and canonical weekly
occurrences. Name, category, subtype, description, venue, room and dates remain
available as structured context. Upcoming linked assessments add a bounded soft
urgency term; they do not silently set a task deadline or create a calendar event.
The intelligent scheduler treats an explicitly academic `assessment_preparation`
task differently: preparation must finish before its linked assessment's actual
recorded start. This derived boundary never rewrites the task's stored dates;
ordinary links remain soft context. See `INTELLIGENT_SCHEDULING_CONTRACT.md`.
Class and commitment links add context without invented time restrictions.

Weekly targets describe allocation. One logical session is allocated when its
verified minutes plus pending reserved chunk minutes cover its target. Split
chunks therefore do not inflate weekly session counts. Daily limits still count
actual work blocks. Pending elapsed chunks remain reservations until explicitly
resolved; they are never fabricated completion evidence. Skipping a missed
planner block releases the reservation for replanning.

Task cards show allocated targets, optional future/elapsed reservations and
verified history separately. Manual session logging is removed from cards. The
planner still allows actual work completion to be recorded. Marking the task
itself completed is a separate explicit lifecycle operation, does not synthesize
session credit, and stops new scheduling in every week. Reopening preserves the
ledger and previous estimates. A week-only completed status remains scoped to
that assignment. No elapsed time, deadline or target count closes a task.

The existing soft weekly goals, finite worthwhile extra-session candidates,
conditional daily minimum, hard daily maximum, travel constraints and weekly-goal
dependency ordering remain in place. Completing a prerequisite's weekly goal for
planning purposes does not assert that its underlying task is globally finished.

No migration, new relationship store or model service was required. All semantic
handling in this change is deterministic. Verification details and limitations
are recorded in PROGRESS.md. The isolated personal-data replay is reproducible
with `scripts/verify_task_relationships.py`; it does not generate schedules in the
personal database.
