# Meal ordering

Preferences → Meals & recovery uses the existing ordered `settings.meals` array.
Drag a meal's handle vertically, or use its Move up / Move down buttons, then
choose Save preferences. The order survives reload and application restart.
Reordering moves the existing objects; names, IDs, durations, venues, enabled
states and optional legacy timing preferences remain intact. No database
migration, dependency or separate order field is needed.

For enabled meals M1 … Mn, CP-SAT enforces `Mi.end <= Mi+1.start`. Disabled
definitions do not participate. These are relative constraints, not clock times:
the optimizer still places required meals around fixed commitments, actual
travel, awake hours and existing plausible eating windows. All workload and
weekly-planning objectives remain unchanged.

Completed, started and explicitly locked saved meals retain their original
positions and metadata. If they conflict with the new order, generation reports
the conflict; it does not move or delete those meals. An impossible combination
of order, meal windows, durations, travel and fixed commitments is reported
instead of omitting a required meal. Adjust the preference order or editable
constraints; confirmed history is preserved.

Legacy definitions already receive stable IDs through the existing settings
read path. Save preferences persists those same IDs and the submitted sequence.
Changed array order uses the existing preference invalidation path, leaving old
schedule blocks intact and prompting regeneration.

The independent generated-meal validator also checks chronological order.
Verification results and any interaction limitations are recorded in
[PROGRESS.md](PROGRESS.md).
