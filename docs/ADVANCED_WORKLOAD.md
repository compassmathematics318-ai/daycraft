# Advanced workload calibration and available-time utilization

This extension addresses the November 13 case with work availability 08:00-23:30, sleep at midnight and an unallocated two-hour Waterloo Reality Labs session. It retains OR-Tools CP-SAT, existing workload/strategy semantics, rolling forecasts, flexible ordered meals, required recovery, venue suitability, travel, daily limits and completion accounting.

## Verified diagnosis

A fresh SQLite online backup and archived source established the current-machine baseline. At an eight-second, single-worker budget, both High and Very High allocated 525 productive minutes. Very High ended around 22:35. Both were FEASIBLE incumbents, not optimal solutions. The original daily model was offered eight weekly units totaling 645 minutes.

The 55-minute tail cannot directly accommodate the unsplittable 120-minute Waterloo session. However, that local fact does not establish that it cannot fit after rearrangement: an original-code 20-second solve allocated all 645 offered minutes, including Waterloo. Search quality is a confirmed cause of the reported omission.

A second limitation was the forecast-to-daily interface. The weekly model emitted only sessions assigned positive minutes today, and capped each daily unit at that amount. Valuable unreserved work forecast for later days was invisible to the daily optimizer. In a controlled ample-demand case, High and Very High both stopped at 360 minutes because of this candidate restriction.

Five-minute start variables already cover the full configured availability. There was no hard 22:35 cutoff. The workload lateness preferences are relative to work-start/work-end, explicit evening preference reaches work end, and midnight sleep was already supported by the preceding repair. Existing opportunity/fatigue weights were not arbitrarily increased in this extension.

## Changes

High and Very High may now consider positive-value unfinished sessions forecast for later in the current week as optional advance work. Admission respects current eligibility, original session/chunk size, unsplittable duration, excluded tasks, dependency cycles/missing prerequisites, actual reserved work and exhausted daily maxima. The daily CP-SAT model still enforces exact timing, routes, recovery, all daily limits and dependencies. Medium and lower retain the paced candidate selection; existing workload-specific diminishing marginal values distinguish High from Very High.

The original forecast amount is retained as `weekly_planned_minutes`; expanded capacity is marked `weekly_opportunity`. Unselected optional advance work does not become a false missed daily requirement. Actual advancement replaces that session's future prediction for progress accounting; it never moves saved future blocks or grants completion credit. Results report offered advance minutes, actual advanced minutes and reduced forecast future minutes. All public diagnostics use task-definition identities plus stable logical-session references.

Search hints now respect daily maxima, meaningful marginal utility, configured home transitions and the absence of pointless terminal recovery. Hints remain suggestions: every returned schedule is validated by CP-SAT and the independent block validator.

For a complex model (at least ten activity nodes and five optional work candidates), production defaults allow a maximum 20-second daily solve with up to eight workers, bounded by available CPU count. Simpler days retain eight seconds and one worker. Explicit diagnostic solve budgets remain honored with one worker by default; explicit worker overrides are bounded to one through eight. Weekly forecasting retains its separate bounded budget. All five workload levels use the same complexity policy, so workload preference is not secretly a different search budget. Parallel search is nondeterministic and cannot guarantee the same timings or a globally best solution on every run.

Results disclose actual budget, worker count, policy, wall time, objective bound/gap and proven-optimal versus feasible status. A returned-itinerary capacity metric subtracts merged fixed/meal/travel/recovery occupancy inside working hours. It is an accounting measure of this itinerary, not a proof of maximum capacity. Tail diagnostics report the consecutive final free interval, remaining minimum chunks, daily-cap usage and known travel, with an explicit warning that rearrangement may fit additional work. Human-readable explanations make this distinction visible. Manual timing edits clear generated tail/optimality facts instead of attaching stale solver evidence to new times.

The planner's empty unmet-work message now says "Today's planned work is allocated" and retains the reminder that allocation does not confirm completion. It does not imply every future task is finished.

## Comparative evidence

All comparisons use the same frozen inputs within each case. The independent task-value measure is productive minutes multiplied by original task importance, not changing optimizer marginal weights.

- Ample weekly demand: at the same explicit eight-second budget, High/Very High changed from 360/360 productive minutes to 720/780. Larger current results are feasible incumbents.
- Scarce work remains compact and may produce equal schedules. Explicit split-versus-unsplit tests demonstrate that two separate 60-minute gaps can hold an eligible split 120-minute session, but cannot hold an unsplittable one.
- Controlled evening availability: moving work end from 22:30 to 23:30 admits 60 additional useful minutes without changing fixed commitments, recovery rules or session sizes. Broader configured windows do not force extra work where supply is exhausted.
- Initial production-policy real-data verification: High525 minutes, importance-weighted4005; Very High640 minutes, importance-weighted4805. Very High includes Waterloo's complete120-minute session. Three separate eight-worker20-second runs found640, with differing timings/objective incumbents. These remain FEASIBLE, not proven optimal. The original-code20-second single-worker645 result remains evidence that640 is not maximum throughput.

An independent production-policy repeat returned Very High585 minutes (importance-weighted4335), including Waterloo120, versus High525 (4005). It ended22:55, leaving35 minutes; the remaining60-minute unsplittable session also needs travel, and the shorter optional PyTorch chunk has reached its daily maximum. Across observed portfolio runs, Very High585-640 is a range of feasible incumbents, not a reproducibility guarantee.

Detailed final five-level/cutoff matrices and all incumbent/quality limitations are retained in `test-results/advanced-workload/MEASUREMENTS.md` and adjacent JSON. Intermediate single-worker expanded-model runs sometimes yielded585, demonstrating that expanding candidate supply alone did not reliably improve search. Four workers also yielded585 in one test; the bounded eight-worker portfolio improved the observed result. These are observations on this machine, not universal performance guarantees.

## Preservation and verification

Three genuine GPT-6.1 Sol agents handled weekly allocation/browser QA, daily CP-SAT/search diagnostics, and independent benchmark analysis. The lead reviewed shared contracts, API persistence/manual edits, truthful UI wording and integrated regressions. Automated generation uses SQLite copies; live schedules and completion records are not modified. The pre-change source/data archive is `data/backups/pre-advanced-workload-20261113.zip`.

No dependency, security-policy, schema migration or launcher change was required. See `docs/PROGRESS.md` for final executed backend/frontend/browser/API/launcher results. The weekly horizon is still a capacity forecast rather than a globally optimized multi-day timetable. Unknown venue travel remains explicitly uncertain; offline benchmark routes use frozen cached/estimated values.
