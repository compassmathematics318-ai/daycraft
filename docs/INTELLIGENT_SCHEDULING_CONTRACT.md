# Intelligent scheduling implementation contract

## Advanced availability and opportunity contract (2026-11-13)

High/Very High may expose positive-value, eligible, unreserved logical work forecast for later days as optional daily candidates. `weekly_planned_minutes` retains today's original forecast; `weekly_opportunity` distinguishes expanded capacity from today's baseline demand. Actual allocation reduces the same session's future forecast contribution without mutating future schedules or confirming completion. Original chunk minima, daily limits, dependencies and venue rules remain authoritative. Public tail diagnostics resolve definition and logical-session IDs.

Complex daily models default to a bounded 20-second parallel CP-SAT portfolio; simple models retain eight seconds/one worker. Explicit diagnostic budgets and bounded worker settings remain honored. Returned capacity/tail diagnostics describe the selected itinerary and do not establish that rearrangement cannot improve it. Manual timing edits invalidate optimizer-specific quality facts. See [ADVANCED_WORKLOAD.md](ADVANCED_WORKLOAD.md) for exact policy and evidence.

Authoritative source: the complete nine-page `intelligent_schedule_building_guide/Daycraft_Intelligent_Schedule_Building_Guide.pdf` (read November 12, 2026).

The subsequent [meal-order extension](MEAL_ORDER.md) makes the saved enabled-meal
array order a hard relative precedence constraint, while actual meal times remain
flexible. It supersedes the original soft meal-order preference only.

## Pipeline and ownership

1. Backend reads canonical calendar occurrences, reusable definitions, effective weekly assignments, saved chunks, confirmed completion, projects and verified venues.
2. `planning_intelligence.py` interprets explicit structured context and conservative text cues with traceable evidence. Text cannot invent deadlines, completion or venue permission. Difficulty affects pacing, not intrinsic value.
   An academic task explicitly typed `assessment_preparation` and linked to an actual assessment may only prepare before that assessment's recorded start. This derived preparation boundary does not alter stored task dates; generic activity links remain soft context.
3. A read-only 14-day capacity forecast extends to relevant explicit deadlines within 28 days. Current-week allocation remains inside the assignment week; future recurring assignments remain virtual. Forecasting never writes future schedules.
4. `weekly_scheduler.py` computes soft weekly progress targets, deadline risk, non-cramming recurring allocation and worthwhile extra sessions.
5. `scheduler.py` uses CP-SAT for the selected day, flexible essential meals, cumulative focus/recovery, actual route times and workload-dependent soft objectives. Balanced / Deadline First / Deep Work remains a separate strategy axis.
6. Feasibility validation, named unmet work, forecast risks and objective explanations accompany the result. Confirmed progress is read again on regeneration; elapsed reservations never become completed credit.

## Shared data contracts

- Meal: `id?`, `name`, `duration_minutes`, `enabled=true`, optional actual `location_id`, optional legacy `time`. Existing duration/time values are preserved. Legacy time is a soft preference, never an appointment. New profiles default to Breakfast 30, Lunch 45, Dinner 30 minutes. Block `meal_id` is server-owned identity.
  Existing definitions receive deterministic IDs on reads, without rewriting the database. Editing retains those IDs, so renaming or adjusting a legacy meal cannot discard its explicit lock or confirmed history.
- `settings.workload_level` is an internal per-generation injection from the selected date's day preference (default Medium). Results persist the applied `workload_level` and `planning_intelligence_version=1`.
- Shared workload profile keys: `opportunity_cost`, `preferred_utilization_ratio`, `fatigue_penalty`, `late_penalty_per_hour`, `focus_multiplier`, `recovery_multiplier`. They change soft objectives, never immutable anchors, work availability, required venues or the configured essential recovery floor.
- `horizon_forecast`: start/end, forecast-only marker, estimated capacity minutes, per-day capacities, task risks and limitations. It is an estimate, not a promised future schedule.
- Changes to scheduling settings or the selected date's workload flag saved plans `preferences_dirty` / `needs_regeneration`; blocks and completion records remain intact. Cosmetic settings do not invalidate schedules.

## Acceptance mapping

| Guide requirement | Verification owner |
|---|---|
| Flexible meals, awake/work distinction, long midday commitment, infeasible meals | Scheduler tests and API tests |
| Five workloads, meaningful optional work, essential recovery, fixed anchors | Scheduler comparison tests and browser generation |
| Weekly soft targets, anti-cramming, extras, actual completion, split accounting | Weekly/horizon tests and existing completion regression suite |
| Deadline, related class/assessment/project context, future capacity | Context/horizon tests and API forecast tests |
| Required/preferred/remote/unspecified locations, walking feasibility | Existing suitability/travel suites plus scheduler regression |
| Preserved locked/started/completed records, honest failure states | API/manual editing and reoptimization regressions |
| Persistent UI preferences, applied workload, automatic meal editing | Frontend tests, type/lint/build, Playwright |
| Real runtime and user data preservation | Windows solver health, copied-database generation and SQLite integrity audit |

The portable pre-change source/data backup is `data/backups/pre-intelligent-scheduling-20261112.zip`. No database migration is required for these additive JSON contracts.
