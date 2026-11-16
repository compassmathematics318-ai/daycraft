# Intelligent scheduling upgrade — November 12, 2026

The complete nine-page Daycraft Intelligent Schedule Building Guide was read before implementation. Its requirements are mapped to code and acceptance checks in [the implementation contract](INTELLIGENT_SCHEDULING_CONTRACT.md). OR-Tools CP-SAT remains the optimizer. No database migration, paid AI dependency, or Windows policy change was introduced.

## Meals and recovery

Preferences now edits meal names, durations, inclusion and optional actual venues without mandatory start times. New profiles use Breakfast 30, Lunch 45 and Dinner 30 minutes. Existing profiles keep their custom definitions, durations and legacy times; those times are soft preferences. Enabled meals are required intervals within awake hours, while work remains inside work availability. Standard meal names receive broad wake-relative plausibility bounds and soft timing/order preferences. Actual specified venues require travel. Unsatisfied meals produce explicit conflicts.

Short work chunks may share a sustained-focus run. Essential configured recovery remains authoritative at every workload level; walking does not count as rest. Difficulty and deterministic work-context cues influence pacing, energy placement and comfortable recovery. Individually authorized longer sessions remain possible.

Remaining-day generation does not assume a past meal was eaten. In the meal editor, explicitly select Completed when appropriate, or lock a saved meal. If an unconfirmed required meal has no sensible remaining slot, Daycraft reports the conflict rather than inventing completion.

## Forecasts, context and weekly semantics

The pipeline reads canonical calendar occurrences, tasks, effective weekly overrides, projects, verified venues, saved reservations and confirmed progress. A read-only 14-day forecast extends to applicable explicit dates within 28 days, including dates stored only in future weekly overrides. Remaining-day capacity excludes elapsed open hours. Forecasts expose competition, estimated shortfalls and deadline/preparation risks, and future congestion can increase today's preparation priority.

Actual weekly work stays in its Sunday–Saturday assignment. Future recurring assignments remain virtual, and forecasting never overwrites saved future plans. Late-week missed recurring targets receive a reasonable best-effort allocation instead of automatic catch-up; the original unmet target remains reported. Completed tasks stop producing work; unfinished tasks can receive worthwhile extra sessions after their minimum target. Scheduled, elapsed, verified completed and actually finished work remain distinct. Split-session credit and hard daily block maxima remain intact.

Context interpretation is local and deterministic, with recorded field evidence. Explicit class/course links support study continuity. Generic linked assessments provide bounded urgency; a task explicitly typed as assessment preparation must finish before its linked assessment's recorded start. That preparation boundary is derived from the actual linked event and never changes stored task dates. Project status controls eligibility and project importance contributes a bounded priority bonus. Text never invents completion, dependencies, durations or venue permission.

## Workload behavior

Workload is independent of Balanced, Deadline First and Deep Work. Generated plans record the applied level; preference changes mark the saved plan for regeneration without changing its blocks or history.

| Level | Soft scheduling preference |
|---|---|
| Very Low | Strong cost for discretionary work, shorter productive day, generous recovery |
| Low | Selective valuable work with comfortable gaps and stronger evening avoidance |
| Medium | Balanced useful progress, moderate extras and unscheduled time |
| High | More worthwhile secondary work, longer focus preferences and a longer productive day |
| Very High | Broad sustainable productivity with the lowest discretionary/evening costs |

The shared profiles use opportunity cost, preferred utilization, marginal fatigue, late-day cost, focus and optional recovery preferences. A soft allowance up to 120 useful minutes prevents short availability windows from losing coherent split/dependency work. These are neither quotas nor permissions to violate constraints. No tasks are fabricated.

## Real Windows and copied-data evidence

The active Python environment passes `backend.app.solver_health` with **OPTIMAL**. Smart App Control remains enabled (`VerifiedAndReputablePolicyState=1`). The earlier verified pandas 3.0.6 runtime repair remains in place; this upgrade changes no application dependency pins or security settings.

A proper SQLite online snapshot of the personal database was used for **15 real API generations**: November 13, 2026, all five workloads across all three strategies. All returned HTTP 200, real FEASIBLE/OPTIMAL schedules, no hard conflicts, and passed manual constraint validation. Confirmed history, locked work and source metadata were checked. The original database's table fingerprints are unchanged, SQLite integrity is `ok`, and foreign-key checks are empty.

Balanced productive minutes in that run were 120 / 270 / 375 / 532 / 520. High and Very High were time-limited FEASIBLE results; a larger workload preference does not imply strict monotonicity or a proven optimum. Complete request evidence is in `test-results/intelligent-scheduling/actual-generation.json`. After correcting Deadline First opportunity-cost normalization for weekly units, all five affected copied-data combinations were rechecked successfully: 90 / 240 / 405 / 510 / 525 productive minutes, with manual validation and unchanged personal data/history. Those final results are in `actual-generation-deadline-normalized.json` in the same folder.

The existing localhost launcher passed actual solver readiness, compiled frontend serving at `127.0.0.1:8765`, and authenticated graceful shutdown using a database copy. No orphaned launcher instance was left by this check. Stop Daycraft and SQLite snapshot backup workflows remain available. Portable backups now also include the authoritative scheduling-guide folder.

## Verification and team

Five genuine GPT-6.1 Sol agents contributed solver algorithms, horizon/context modeling, frontend integration, independent backend review, and browser QA. The lead integrated API/schema/persistence behavior, reviewed contracts and history protections, and ran full backend, copied-data generation and launcher checks.

Final executed test counts and browser results are recorded in [PROGRESS.md](PROGRESS.md). Evidence is under `test-results/intelligent-scheduling/`; the solver agent's acceptance details are in `solver-report.md` there.

## Limits

The horizon is an aggregate capacity forecast, not a global multi-day clock-time optimum. Route fragmentation, recovery and later changes can reduce forecast capacity. Session targets estimate effort rather than guaranteeing completion. Text interpretation is a bounded rule set, not semantic AI understanding. Daily CP-SAT can return FEASIBLE or honest timeout/infeasibility. Browser maps use offline/stubbed providers; live external routing availability is not tested. The existing frontend bundle-size and Starlette/AnyIO deprecation warnings remain nonfatal.
