# Workload calibration and productive-time efficiency

> Follow-up: [Advanced workload calibration](ADVANCED_WORKLOAD.md) extends candidate admission and replaces the old universal eight-second single-worker default with a bounded complexity-based search policy. This report records the earlier calibration.

Daycraft retains its existing rolling-horizon planner, OR-Tools CP-SAT daily optimizer, ordered flexible meals, contextual priorities, venue suitability, completion accounting and Windows launcher. This extension changes soft allocation and placement objectives; it does not introduce a replacement scheduler, new task facts, database migration or dependency change.

## Diagnosis

The old High and Very High profiles shared the same weekly extra-session candidates and diminishing utility. An unfinished importance-10 task without urgency had extra-session values 80, 50 and 20 regardless of intensity. Once that pool was exhausted, increasing daily utilization willingness could not create additional useful candidates. The old daily objective had essentially only tiny start-time tie-breaks for compactness. A lateness term began six hours after work start regardless of the configured window and was tiny compared with work-value units. Finally, every last circuit arc included recovery, even when no activity followed.

The copied November 13 baseline allocated 508 minutes at High and 525 at Very High. Both were FEASIBLE incumbents at eight seconds, with objective gaps of approximately 1.4% and 4.0%. Similar finishing times alone were not evidence of an error or of optimal solutions.

## Mathematical changes

The daily solver still maximizes a weighted objective subject to the same hard feasibility constraints. Work and urgent-deadline utility remains dominant for ordinary cases. These objectives are soft tradeoffs, not a strict lexicographic guarantee for every possible input.

For unfinished weekly work, the evidence seed is `(importance - 6)*20 + urgency*(30 for Deadline First, otherwise 20) + project_bonus/5 + related_bonus + context_bonus`. Extra session `k` receives `round(seed * advance_multiplier - 30*k)` while positive and physically bounded. Actual completed extras consume their marginal positions. Finite legacy work cannot acquire invented extras; completed definitions remain excluded. Unsupported old pending proposals are removed from the planning candidate view before pacing calculations, without deleting their persisted history. Partial and reserved work remain available for continuation.

| Profile | Advance multiplier | Work-envelope cost/min | Direct idle cost/min | Completion-extent cost/min | Late preference begins at fraction of available window |
|---|---:|---:|---:|---:|---:|
| Very Low | 0.55 | 8 | 12 | 12 | 0.50 |
| Low | 0.75 | 6 | 9 | 9 | 0.55 |
| Medium | 1.00 | 4 | 6 | 6 | 0.65 |
| High | 1.30 | 2 | 3 | 3 | 0.80 |
| Very High | 1.85 | 1 | 1 | 1 | 0.90 |

All costs use the solver's work-value point units (scaled by 1000 in the integer objective). The work envelope is the last optional work end minus its first start, less overlapping fixed/meal occupancy. Completion extent runs from effective work start to last optional work end, again subtracting forced occupied time. Direct optional-work-to-optional-work idle excludes required recovery and route travel. A distant fixed appointment does not attract a small amount of work late merely to eliminate its unavoidable preceding gap. Existing task eligibility, daily maxima, prerequisites, fixed anchors, meal precedence and protected blocks remain authoritative.

Existing opportunity costs, fatigue preferences and essential recovery floors remain. Explicit timing/energy preference weights were normalized to retain their intended precedence over compactness; inferred cognitive timing remains a light suggestion. The bounded conditional daily minimum-session preference was increased to preserve its established behavior against the new extent costs. It remains soft and cannot override hard daily maxima or feasibility.

Late work is evaluated relative to the user's effective work window, with no new hard evening cutoff. Explicit evening preference now extends through configured work end. Preferences accept sleep `00:00` as midnight at the end of the selected day; forecasting applies the same interpretation. Work 08:00-23:30 with sleep 00:00 is supported. Arbitrary overnight work windows remain unsupported.

## Recovery and evidence

A final work node has no automatic recovery when nothing follows. An actual return-home journey still reserves necessary recovery and travel. Explicit/locked recovery blocks remain intact, as do breaks required before subsequent activity and all enabled meals.

Results expose candidate minutes, estimated unused capacity, work/completion extents, forced occupancy, direct discretionary idle, objective value/bound/gaps, branches, conflicts and termination reason. Explanations distinguish exhausted offered supply from constraint/objective tradeoffs and explicitly identify feasible, unproven incumbents. Capacity is an estimate, not a proof that another task can fit. Weighted utility and objective numbers across versions are not independent quality scores because the underlying objective changed.

## Representative executed comparisons

| Controlled scenario | Before | After |
|---|---|---|
| Unfinished weekly task whose minimum is already completed, Medium | 180 productive min | 180 productive min |
| Same task, High | 180 productive min | 240 productive min |
| Same task, Very High | 180 productive min | 300 productive min |
| Scattered anchors, Low through Very High | 240 productive min over 480 min | Same 240 productive min over 430 min |
| Final standalone work | 60 work + 10 terminal recovery min | 60 work, no terminal recovery |
| Scarce urgent work, every profile | 90 productive min over 100 min | Same compact 90/100 min |

These rows are proven OPTIMAL. A separate browser/API fixture produced 45, 45, 180, 225 and 270 productive minutes across the five levels, preserving fixed appointments and ordered meals. A plentiful but finite 810-minute supply produced the same High and Very High workload because both selected all available work. An evening scenario scheduled useful work beyond 22:00 within 23:30 availability.

On the unchanged copied personal inputs, the eight-second High result stays at 508 productive minutes and Very High changes from 525 to 510. The weekly forecast exchanges a 120-minute project session for 105 minutes of other work on Friday and moves the project target to Saturday; this does not overwrite Saturday's saved schedule. These are different task allocations, not merely identical work shifted later. At 30 seconds the Very High productive span is 815 minutes: 510 work, 175 fixed classes/meals, 75 travel, 45 recovery and 10 genuinely unoccupied minutes. Its remaining 120-minute project is unsplittable and cannot be inserted into those gaps without rearranging or replacing work. The old 525-minute selection still passes the current hard-constraint validator, so 510 is not maximum throughput. The new objective values different work and retains search uncertainty; this is not proof of a globally better plan.

Full measurements, intervals, remaining work, statuses, solver bounds and copied-data caveats are in `test-results/workload-calibration/REPORT.md` and its adjacent JSON files. Larger copied-data models remain partly FEASIBLE; increasing solve time does not guarantee a proven optimum or strictly increasing minutes for every profile. The horizon remains a capacity forecast, not a global multi-day timetable optimizer. No claims are made from a schedule's last clock time alone.

## Preservation and coordination

Three genuine GPT-6.1 Sol agents handled daily CP-SAT objectives/recovery, weekly marginal utility plus browser verification, and independent comparative QA. The lead owned shared profile contracts, midnight API/forecast consistency, integration review, full regression verification and data audits. The pre-change source/data archive is `data/backups/pre-workload-calibration-20261112.zip`. Automated generation uses isolated SQLite backups. The frontend design, dependency pins, launcher and stored user preferences remain unchanged.

See the latest `docs/PROGRESS.md` entry for final executed test counts and integration outcomes.
