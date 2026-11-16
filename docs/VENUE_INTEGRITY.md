# Venue integrity and suitability

The initial whitelist-only preferred-place policy has been superseded by
[SEMANTIC_LOCATIONS.md](SEMANTIC_LOCATIONS.md). This document retains the data
integrity guarantees and the original defect investigation.

Physical location policy is shared by definitions, weekly overrides, occurrences,
solver inputs and stored blocks. `location_id` is the configured venue;
`resolved_location_id` is the recorded/planned physical position. They must not
be conflated in the UI.

- Required: only the configured venue is allowed.
- Preferred: the configured venue remains the first choice. Alternatives may
  come from matching verified capabilities with confirmed access, or explicit
  activity-specific user confirmations. The semantic layer supplies evidence
  before optimization. Neither proximity nor a place name proves suitability.
- Remote: no required destination; retain feasible physical continuity.
- Unspecified: attendance position is unknown. Internal continuity variables do
  not establish a verified venue or verified travel coverage.

Missing capability and explicit-confirmation fields remain empty for existing
records. Activity text can conservatively identify needs; it never proves place
capabilities or access. Required venues never become flexible through these fields.
Travel uses the actual permitted destination and remains a hard constraint.
Manual physical-location edits resolve to the selected venue before travel
validation and persistence. Validation cannot accept one venue and then export
another. Existing explicit, authorized actual alternatives retain their IDs.

Protected historical blocks retain their actual recorded positions. Their
preservation requires trusted prior server records, not a client assertion that
a new block is locked. Current/future plans with unlocked, unstarted blocks containing an unauthorized legacy
substitution must be marked stale and request regeneration without rewriting
historical source data or silently changing the saved preference.
Locked blocks keep their recorded physical position and expose an unauthorized
venue warning instead of being silently moved during regeneration.

Observed original defect: live Gym definition and effective weekly assignment
both selected PAC, while the persisted 2026-11-13 block retained PAC as
`location_id` and selected MC as `resolved_location_id`. The solver offered every
known venue to any preferred task with only a small soft penalty. Thus the fault
was optimizer permission semantics, rather than an incorrect PAC association.
Evidence: `test-results/venue-integrity-before.json`; backup:
`data/backups/pre-venue-integrity-20261112.sqlite`.

Executed final checks and remaining limitations are recorded in PROGRESS.md.
