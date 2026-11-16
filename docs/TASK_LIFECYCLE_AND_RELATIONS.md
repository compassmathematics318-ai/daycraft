# Task lifecycle, library associations and related entities

## Identity and library labels

The reusable definition remains the task identity. Weekly assignments reference
it rather than cloning it. Definition responses include the read-only
`association_summary` across all stored weeks, not just the currently selected
week. It lists assigned Sunday week keys, historical weeks containing sessions,
and recurrence bounds. These describe associations, never proof of scheduled or
completed work. Library cards show Every Week, a Sunday-Saturday range, expandable
Multiple weeks, or Unassigned. Recurrence cutoffs are shown separately.

## Distinct lifecycle operations

- `DELETE /api/task-weeks/{id}` removes work from that week. The row is retained
  with `removed_from_week: true` and skipped status for identity and audit history.
  It moves out of active assignments into `history_assignments`. Explicitly
  assigning again can reactivate the same identity; a read cannot resurrect it.
- `DELETE /api/task-definitions/{id}?delete_assignments=true` deletes everywhere.
  The definition receives a server-owned `deleted_at` tombstone and audit
  snapshot. Active locations, related activities and projects are detached;
  inbound dependency links are cleaned. Active lists, recurrence expansion,
  planner candidates and map aggregation exclude it. Legacy aliases are covered.
- `POST /api/task-definitions/{id}/stop-repeating` accepts `{from_week}`. The date
  is normalized to Sunday. Recurrence keeps earlier eligibility but stops from
  that week onward, including already-materialized future recurring assignments.
  The UI defaults to the next week and shows the exact cutoff before confirmation.
  Explicit assignments after the cutoff remain Week Specific and can be copied
  into other eligible weeks. Automatic recurrence at either end is excluded from
  copying; stopped recurrence metadata alone does not make a later assignment
  recurring. Historical cutoffs are rejected to avoid rewriting past eligibility.

Each operation is transactional. Future pending work, including locked pending
blocks, is cancelled as described in confirmation. Past, started, skipped and
verified completed evidence stays intact. Shared saved places and other tasks
with the same name are never deleted. Tombstones cannot be reopened by ordinary
edits, weekly overrides or the legacy task API. Existing historical plans are
retained; affected plans are invalidated for regeneration. Deleted task history
is not presented as an active map association.

Regeneration retains withdrawn elapsed work even if it was not locked or marked
completed. Non-schedulable history units provide identity and original venue
metadata to validation without creating new work. A server-derived private marker
pins the saved venue and preserves the original status/rationale; it is stripped
before persistence and responses. Manual edits cannot forge this exception or
change withdrawn history. Ordinary time, overlap, travel and recovery constraints
remain authoritative.

An unassigned library definition is valid data. There is no blanket cleanup of
unassigned tasks. The user-reported temporary `hi` task was separately identified
by stable ID, exact CMH location, lack of assignments/history and lack of inbound
dependencies before repair through the existing API. The reproducible repair
script defaults to read-only and is idempotent; its evidence and backup paths are
recorded in `test-results/task-lifecycle/reported-hi-repair.json`.

## Shared related-entity picker

Tasks continue using their existing `related_activity_id` and `project_id` fields.
The grouped searchable selector exposes both without introducing a second
relationship store. Selecting an activity does not discard project context, or
vice versa; selected links are individually clearable. Existing dual links stay
intact. Project context remains definition-level while activity links can use the
existing one-week override mechanism.

Commitments use optional `related_entity: {kind: 'activity'|'project', id}` in their
existing metadata. The service validates existence, rejects self references and
activity-link cycles, preserves omitted values on older edits, and detaches links
when the target is deleted. Renames resolve against current entities. Only
commitments expose this new organizational relationship; other activities remain
eligible targets. No duplicate class, commitment, assessment or project is made.

Planning receives validated current `related_entity_context` and canonical
occurrences. Fixed blocks carry this context without creating additional events
or changing their time/location constraints. Task project importance/status and
the bounded linked-assessment soft urgency term remain functional. A link never
creates a hard deadline, inferred venue substitution or extra occupied interval.
The core remains deterministic and requires no LLM service.

Generated schedule blocks expose `related_entity` and `related_entity_context`
as read-only snapshots. Manual schedule edits accept these fields unchanged for
round trips, or preserve the saved values when older clients omit them. A client
cannot change or invent that context through a schedule edit; the API rejects
different values with HTTP 422. Edit the library activity and regenerate to
update its relationship context. Unknown block fields remain rejected.

Existing JSON metadata and task foreign keys support this extension; no schema
migration or destructive conversion is needed. See PROGRESS.md for executed tests
and any environment limitations; authored tests are not evidence of execution.
