# Timeline archive action and safe archive deletion - 2026-11-14

Implemented with GPT-6.1 Sol frontend, backend audit and independent browser QA
agents. The lead reviewed persistence boundaries, pagination/refetch behavior,
duplicate-click safety and final integration. Production changes are confined to
`frontend/src/Planner.tsx`, `History.tsx` and `history.css`; existing archive APIs,
tables, transaction boundaries and scheduler objective functions are unchanged.

- Daily Planner now places **Save to Schedule Archive** inside the timeline panel
  directly after the last activity and before its closing footer. It names the
  displayed schedule date and saves the server's latest persisted state. The
  primary slot stays disabled as **Saved to Archive** after success; intentional
  Save New Version and View in Archive actions appear separately beneath it.
  This prevents a fast repeated save click from becoming a new-version click.
  Existing autosync and regeneration-detached historical versions are preserved.
  Stale plans explicitly explain that saving preserves their current state and
  regeneration is a separate action. Controls disable during generation/saving.
- Every archive card has a visible **Delete from Archive** action. The dialog
  uses the exact requested title/message, identifies date/version/save time,
  initially focuses Cancel, traps keyboard focus, supports Escape before
  submission, and ignores backdrop clicks. Only **Delete Permanently** submits.
  Synchronous guards prevent repeated requests. Success updates the list before
  its refresh; API failure keeps the record/dialog intact. Follow-up refresh
  errors are distinguished from failed mutations and retry the right operation.
  Pagination refills after deletion, and late responses cannot replace a newer
  filter's results.
- Backend audit confirmed deleting either an attached or frozen version removes
  exactly that archive row: all other SQLite rows remain identical. Repeat delete
  returns 404 without mutation. Active plan blocks, work credit, completed-work
  history, definitions, assignments, preferences and other versions are retained.
  The active plan's derived archive link disappears when its archive is deleted;
  its stored schedule does not change. New failure-injection tests verify atomic
  rollback of version creation and deletion. No backend fix or migration needed.

Executed verification:

- Final `.venv\Scripts\python.exe -m pytest backend/tests -q`: **855 passed**,
  175.55 seconds. Includes completion/week isolation, recurring and week-specific
  tasks, intelligent scheduling, all five workload profiles, locations, meals,
  travel, daily limits, forecasts, reoptimization and archive regressions.
  Focused history suite: **34 passed**, 15.40 seconds; includes five new audit
  cases. Backend Ruff passed. An initial full run had 854 passed / one failure
  from a new test fixture missing the explicit location override; the fixture
  was corrected, targeted tests passed, and the final full run above is clean.
- Frontend: typecheck and lint passed; **209 Vitest tests passed** across 14
  files. Production build passed: `index-D6n4ANCN.js`, `index-5Hk9Pip0.css`.
- History Edge suite executed all ten cases: **9 passed, 1 test-fixture
  assertion failed** because preference changes retain the saved solver status
  while setting `preferences_dirty`/`needs_regeneration`. The assertion was
  corrected to those existing contract fields; the **focused rerun passed 1/1**
  in 36.3 seconds (`DAYCRAFT_QA_RUN=archive-save-retry`, history config, grep
  `bottom archive save preserves`). All ten history scenarios therefore have
  passing verification. Focused evidence is retained separately in
  `test-results/archive-save-retry-browser-results.json`.
  The nine passing cases cover real generated-plan saving, persisted manual
  edits/locks/location/workload, double-click protection, historical versions,
  cancellation/focus, deletion failures/retry, pagination refill and delayed
  filter responses. All **48 WCAG AA axe/overflow audits passed** across four
  themes at desktop/mobile sizes. Lead visually inspected the Light desktop
  footer and Midnight mobile deletion dialog. An earlier test-only accessible
  selector mismatch was corrected to include the button's date/version context.
  Full-run evidence: `test-results/history-browser-results.json` and
  `test-results/history-screenshots/`. The history Playwright config now supports
  an optional QA report prefix so focused runs retain the full-run evidence.
  Full run: 263.98 seconds, `npm --prefix e2e test -- --config
  playwright.history.config.js` with `DAYCRAFT_QA_RUN=archive-history` (before
  report-prefix support). The initial selector mismatch run was interrupted and
  its selector corrected before this full run.
- Completion Edge regression: **12/12 passed**, with
  `DAYCRAFT_QA_RUN=archive-completion-regression` and
  `npm --prefix e2e test -- --config playwright.completion.config.js`.
  Its **28 axe/overflow audits passed**. Combined browser verification covers
  all **22 distinct scenarios** across full runs plus the corrected focused
  rerun, and **76 accessibility/layout audits**, zero violations. Existing
  completion reversal, weekly isolation, saved work, workload controls and all
  four themes remain correct. Evidence:
  `test-results/archive-completion-regression-browser-results.json` and report.
  All isolated browser servers shut down cleanly; port 8876 has no listener.
- `.venv\Scripts\python.exe scripts\verify_archive_restart.py --output
  test-results\archive-actions-restart`: **10 checks passed**, five actual server
  processes. Read-only personal database copy and isolated synthetic work verify
  durable archives/completions, restart, explicit edits, confirmation/undo,
  CP-SAT regeneration, metadata retention and independent archive deletion.
  SQLite integrity and foreign-key checks passed; personal data unchanged.
- `.venv\Scripts\python.exe scripts\test_launcher.py`: **all checks passed**:
  actual Windows launcher, CP-SAT readiness, compiled frontend smoke, migration,
  occupied-port fallback, running-instance reuse and parent-exit cleanup. QA
  used ports 9175/9176; the normal localhost workflow stays at 8765.
- Read-only live audit verified healthy application/solver and byte-identical
  served build assets at **127.0.0.1:8765**. All personal tables match the online
  before-copy, including completed-work audit records and work credit. Backup,
  source snapshot and audit evidence: `test-results/archive-actions-audit/`.
  No live restart was required for this frontend-only change; reload uses the
  tested compiled assets.

Existing Starlette/AnyIO deprecation and Vite bundle-size advisories remain. Automated map
traffic is offline/stubbed; browser coverage uses installed Microsoft Edge and
emulated screen sizes. The unrelated broad 39-case browser suite is not part of
this focused rerun.

# Completion confirmation and weekly progress integrity - 2026-11-14

Implemented as a focused frontend reliability change with GPT-6.1 Sol frontend,
backend verification and independent QA agents. Production changes are limited
to `History.tsx`, optional shared `Modal` behavior in `Forms.tsx`, and theme-token
styles in `history.css`. No backend production code, schema, scheduling objective,
launcher or personal completion data was changed.

- Completed Tasks opens **Mark this session as not completed?** with the exact
  requested explanation, task title and scheduled interval/timezone. Cancel is
  initially focused; keyboard focus stays in the dialog, Escape cancels before
  submission, and backdrop clicks do nothing. Confirmation uses the existing
  history-ID reversal API. A synchronous in-flight guard and disabled actions
  prevent duplicate submissions. API errors retain the dialog and existing work;
  success appears only after the backend responds. A subsequent global refresh
  error is handled separately from reversal failure.
- Weekly isolation was already correct. Stable assignment IDs and Sunday week
  keys keep verified credit independent; no reset job is needed. New regression
  tests explicitly cover November 8–14, 2026 with three completed sessions out
  of four, followed by November 15–21 with zero. Week Specific work is absent
  until explicitly assigned, while Every Week has a fresh effective assignment.
  Earlier history remains intact. Target attainment never changes task lifecycle.
- Late confirmation is displayed on its actual local confirmation date but
  credits the original assignment week. Old-week reversal changes one chunk,
  reconciles its logical session and planning inputs, and marks only affected
  weekly plans stale. Unrelated weeks, chunks and detached archives remain intact.
  Reopened unconfirmed chunks retain their scheduled reservation; they do not
  create duplicate available work. Attached archives track the explicit edit.

Actually executed:

- `.venv\Scripts\python.exe -m pytest backend/tests -q`: **836 passed**,
  136.99 seconds, before collection of the added file. Existing suite includes
  real scheduler, all five workload profiles, daily block limits, forecasts,
  reoptimization, completion and history regressions.
- New `backend/tests/test_weekly_completion_history.py`: **14 passed**,
  3.77 seconds. Covers exact November rollover, year/month rollover, UTC-stored
  Saturday work, late Sunday confirmation, double reversal, partial chunks,
  corrected scheduler inputs, metadata edits, paused/archived definitions, archive
  deletion, local week boundaries in Toronto and Kathmandu, and DST gap/fold.
  Existing focused history/confirmation/recurrence/weekly/lifecycle baseline:
  **143 passed**, 30.72 seconds. Backend Ruff passed including the added tests.
- Frontend typecheck and lint passed; Vitest **207 passed** across 14 files.
  Production build passed (`index-DmeNbH0E.js`, `index-VpbhOrM7.css`).
- Real Microsoft Edge completion suite: **12 passed**, 147.26 seconds, using
  `DAYCRAFT_QA_RUN=reversal-confirmation` and
  `npm --prefix e2e test -- --config playwright.completion.config.js`.
  Includes cancellation/Escape/backdrop/focus, failed and delayed requests,
  repeated confirmation attempts, isolated weekly and split-chunk progress,
  archive semantics and all four themes at desktop/mobile sizes. Lead inspected
  Light desktop and Midnight mobile dialog screenshots. All **28 axe WCAG AA
  and overflow audits passed**, including eight reversal-dialog theme/size pairs.
- Dedicated history Edge suite (`npm --prefix e2e test -- --config
  playwright.history.config.js`): **5 passed**, 106.95 seconds. Covers actual
  generation, archive synchronization/versioning, completion history, deletion
  isolation, error recovery and themed responsive layouts. Results are in
  `test-results/history-browser-results.json`. Its **32 axe/overflow audits**
  passed, bringing this task's combined browser audits to **60**, zero violations.
- Strengthened gated reversal browser case: **1 passed** on a separate focused
  rerun, explicitly asserting no success notice while the backend request is
  held and a success notice only after the real response. Evidence is in
  `test-results/reversal-confirmation-status-browser-results.json`.
- `.venv\Scripts\python.exe scripts\verify_archive_restart.py --output
  test-results\completion-integrity-restart`: **all 10 checks passed** across
  five actual server processes. Online personal-data copy preserved existing
  rows/credit through restart; synthetic split completion, undo, real CP-SAT
  regeneration, task removal, archive deletion and restart all retained correct
  history. Both isolated databases passed integrity and foreign-key checks.
- `.venv\Scripts\python.exe scripts\test_launcher.py`: **all checks passed**.
  Actual Windows launcher, CP-SAT readiness, migration, compiled frontend smoke,
  occupied-port fallback (9175/9176), reuse and parent-exit cleanup verified.
- Read-only live verification at **127.0.0.1:8765** passed: health, operational
  solver and byte-for-byte served production assets. Online backup and row-level
  audit in `test-results/completion-integrity-audit/` show every personal table
  unchanged, including all six audit records (four currently confirmed), stable
  work credit, valid SQLite integrity and no foreign-key violations. No live
  restart was needed for this frontend-only update; reload loads the new build.

Evidence: `test-results/reversal-confirmation-browser-results.json`,
`test-results/reversal-confirmation-screenshots/`,
`test-results/completion-integrity-restart/report.json`, and
`test-results/completion-integrity-audit/live-verification.json`.

Limitations: actual browser coverage uses installed Edge and emulated desktop/
mobile viewports, not other browser engines or physical devices. The unrelated
39-case broad browser suite was not rerun for this focused change. Public map
providers are offline/stubbed in QA. Existing Starlette deprecation and Vite
bundle-size advisories remain.

# Completion reversal, dropdown contrast and schedule dates - 2026-11-14

Three genuine GPT-6.1 Sol agents implemented backend/history integration,
frontend UX and independent Edge QA. The lead reviewed shared interfaces,
archive semantics, prior-status restoration, timezone initialization and date
bounds, and personally ran backend and Windows launcher verification.

- Completed Tasks now offers **Mark as Not Completed** by stable history ID.
  Its transaction reverses the specific credited chunk/manual record, reconciles
  logical-session progress, retains the audit record, restores prior block status,
  and marks affected plans stale without regenerating or changing task lifecycle.
  Attached archives follow the edit; detached versions remain historical.
- Native selects and their options use explicit theme foreground/background
  tokens and light/dark browser color schemes, including shared form selectors.
- Overview and Daily Planner share a labeled Schedule Date component with a long
  date, date picker, previous/next and Today/Tomorrow. Configured timezone drives
  today and initial tomorrow; date-only arithmetic handles DST/year boundaries.
  Date-scoped workload responses cannot replace another selected date's value.
- No migration, optimizer objective changes or launcher modifications. Test data
  uses isolated databases; no personal completion records were changed.

Executed verification (additional focused/browser results follow):

- Full backend suite: **831 passed**, one existing Starlette/AnyIO deprecation
  warning, 222.71 seconds. This run began before the new reversal tests landed.
- Final combined history/confirmation suite: **70 passed**, including new
  history-ID reversal, restart persistence, both week origins and untouched
  next-week plans. Backend Ruff: passed.
- Frontend: **207 tests passed**; final focused History/date checks **12 passed**;
  TypeScript, ESLint and production build passed. Vite retains its bundle-size
  advisory (approximately 603 kB JavaScript).
- Windows launcher `-NoBrowser -SmokeTest`: passed with an isolated database,
  actual CP-SAT self-test, frontend health and graceful shutdown. Existing port
  8765 was occupied, so the unchanged launcher safely used 8766.
- Subsequently activated the update through the existing authenticated stop and
  hidden Windows launcher at **127.0.0.1:8765**. Health and CP-SAT self-test passed;
  the live OpenAPI exposes the reversal route. Online backup and row-level
  before/after audit in `test-results/reversal-delivery-audit/` confirm every
  table unchanged, all six original confirmed blocks preserved, unchanged work
  credit, valid integrity and no foreign-key violations.
- Focused real Microsoft Edge suite: **9 passed** (51.9 seconds), with reversal,
  refresh persistence, date/workload synchronization, four-theme option contrast
  of at least 4.5:1, keyboard interaction, axe and desktop/mobile overflow checks.
  Initial two test-only failures (locator and save timing) were corrected before
  the full passing rerun. Lead visually inspected actual opened Dark workload and
  Midnight theme popups, Light desktop planner and Midnight mobile Overview.
  Evidence: `test-results/completion-screenshots/` and completion browser report.
- Broad Edge regression command `npm --prefix e2e test -- --trace off` executed
  all 39 cases: **36 passed, 3 failed** in 12.4 minutes. Failures were test fixture
  assumptions: tomorrow crossed a Sunday week boundary while task assignments
  stayed in today's week; a prior Home pin/preferences leaked into a map test;
  and a draft map point duplicated the prior Home coordinates. QA corrected only
  the fixtures in `workspace.spec.js` and `zzzzz-locations.spec.js`.
- Corrected workspace/location rerun: **4 passed** in 2.2 minutes, including
  real generation, export, locks, reoptimization, manual edits, map/home behavior
  and all-theme desktop/mobile accessibility. Thus every broad regression case
  has passed, with the three fixture corrections verified by focused rerun.
  Separate evidence: `test-results/qa-regression-results.json`; original full-run
  results remain in `test-results/playwright-results.json`.
- Dedicated archive Edge suite: **5 passed** in 58.0 seconds, including actual
  CP-SAT generation, archive synchronization/versioning/regeneration, completion
  history, deletion isolation, error recovery and four-theme responsive audits.
  Evidence: `test-results/history-browser-results.json` and history screenshots.
  All 39 broad regression scenarios, nine focused feature scenarios and five
  archive scenarios have passing coverage after the documented fixture reruns.

Limitations: real browser verification uses installed Microsoft Edge (Chromium)
on this Windows host; other browser engines, OS palettes and physical touch
devices were not separately tested. Map provider traffic is stubbed/offline in
QA. Existing upstream deprecation and Vite bundle-size warnings remain.

# Schedule Archive and Completed Tasks - 2026-11-13

Implemented the [history contract](HISTORY_CONTRACT.md) with four genuine
GPT-6.1 Sol agents: backend/database, frontend/UX, persistence/integration and
independent browser QA. The lead defined the shared lifecycle, reviewed edge
cases and visual output, integrated verification, and personally restarted and
audited the actual Windows application.

## Behavior and persistence

- Added Completed Tasks and Schedule Archive directly after Locations & Map,
  before Preferences, with responsive layouts in all four themes.
- Daily Planner has Save to Archive, visible attachment status and Save New
  Version. Saves deduplicate; numbered versions remain distinct. Successful
  planner edits and confirmations update the attached snapshot transactionally.
  Regeneration/reoptimization preserves the old version and starts an unarchived
  working revision. Background library changes cannot rewrite archived details.
- Archive date/workload/search filters, full historical timelines, saved context,
  explanations and confirmed permanent deletion operate on independent snapshots.
  Deleting one archive cannot delete active plans, tasks or completion credit.
- Completed Tasks derives explicit work from the existing confirmation system.
  It groups by actual confirmation date in the configured timezone, retains
  original scheduled bounds and weekly/project/activity associations, distinguishes
  partial chunks from logical sessions and task lifecycle, and supports totals,
  day/week navigation, search and context links. Undated earlier evidence stays
  separate and self-contained. Elapsed time and target attainment add no credit.
- Additive migration `0008_schedule_history` creates `schedule_archives` and
  `completed_work`, with unique identities, date indexes and independent source
  references. New `/api/schedule-archives` and `/api/completed-tasks` endpoints
  expose paginated historical views. Existing progress tables remain authoritative.

## Personal data and actual restart verification

Online SQLite backup and source ZIP: `test-results/archive-history/20261113-230123/`.
Original data: 3 active schedules, 6 confirmed blocks, 12 chunks, 16 logical
sessions, 14 task definitions, 13 task weeks, 2 projects and 28 occurrences.
Every original data row and confirmed block is unchanged after live migration
and restart; only the Alembic version row advances. SQLite integrity is `ok`,
foreign-key violations are zero, and original session/chunk credit is identical.

The existing Windows launcher was run with `-NoBrowser`, gracefully stopped by
its authenticated instance ID and run again. Live backend PID changed from
52320 to 24208; state and completed-history SHA256 values are identical across
the restart. **All six prior confirmations, totaling 415 minutes, are available.**
A read-only live Edge check displayed all six rows and verified the planner Save
action and initially empty archive. No demo or test completion was added to the
personal database. The app remains at `http://127.0.0.1:8765` with CP-SAT
`operational / OPTIMAL`. Served assets byte-match final `index-C6tXtSWq.js` and
`index-BnzsCwj4.css`.

## Executed checks

- Full backend: **831 passed** in 218.97 seconds. Backend and verification-script
  Ruff checks passed. Dedicated history coverage includes concurrent save
  deduplication, rollback atomicity, immutable context, mixed-offset completion
  ordering, undated credit, physical source deletion, and unchanged optimizer inputs.
- Frontend: **203 passed** across 13 files; final history wording regression:
  **8 passed**. TypeScript, ESLint and production build passed. On Windows,
  `npm.cmd` was used because PowerShell blocks the `npm.ps1` shim.
- Final isolated HTTP restart replay: **10 lifecycle checks passed across five
  actual backend processes**, including copying/migrating personal data, six-event
  backfill, idempotence, edits, split credit, undo, versions, staleness, actual
  CP-SAT regeneration, task/archive deletion and durable restart recovery.
  Evidence: `test-results/archive-history/restart-20261113-231853/report.json`.
- Final dedicated Edge history suite on the exact served `C6tXtSWq` build:
  **5 passed** in 120.69 seconds, with zero unexpected/flaky results, including
  error/retry behavior, context navigation and **32 axe/overflow checks** across
  desktop/mobile and four themes. All audit violation lists are empty; an
  additional **16 modal viewport screenshots** were retained. The isolated
  browser server shut down cleanly. Existing completion suite: **7 passed**, including **20
  accessibility/overflow checks**.
- Full default `npm.cmd --prefix e2e test`: **37 passed, 2 failed** in 23.6
  minutes. Both failures were legacy theme-persistence assertions (projects and
  weekly tasks), not history/solver/map/lifecycle assertions. After adding fixture
  readiness and explicit settings-response checks, the exact two cases passed
  through `playwright.theme-regression.config.js`: **2 passed** in 2.4 minutes.
  Every one of the eight expected theme PUT responses arrived on the **first
  selection**; no retry annotation or missing-response attachment was produced.
  Thus all 39 default workflows have passing evidence across the original run
  and targeted follow-up; the original full command's two failures are retained
  in its report. The later dark-selection transient was not reproduced, and its
  precise cause is not established. No product change was made for these tests.

Early verification exposed an obsolete exact API-response assertion; it now
checks the added read-only archive fields while retaining exact original-payload
and raw-database preservation assertions. The subsequent complete backend run
passed. A browser run coincided with Vite replacing `dist`; that run was stopped
and restarted against frozen final assets. The restart helper now bypasses the
system proxy for localhost. The standard launcher also passed running-instance
reuse without starting a duplicate server.

## Limits and evidence

The existing Starlette/AnyIO deprecation and Vite bundle-size warnings remain
nonfatal. Browser coverage uses Edge and emulated mobile sizes; map providers
are offline/stubbed during automated tests. Metadata that was never stored
historically cannot be reconstructed: missing completion timestamps and unknown
workload levels remain explicitly unrecorded. Filters and summaries operate over
local stored snapshots; large-scale archive performance was not benchmarked.
The scheduler, weekly optimizer, travel, meal-planning and launcher source files
match their pre-change backup checksums.

Additional evidence: `test-results/archive-history/live-before.json`,
`live-after.json`, `live-browser.json`, `live-completed.png`, `live-archive.png`,
and `20261113-230123/comparison.json`; browser reports/screenshots are in
`test-results/history-*` and `test-results/completion-*`. The original default
results are `test-results/playwright-results.json`; the passing theme follow-up
is `test-results/theme-regression-results.json`.

---

# Personal Projects tracker cleanup - 2026-11-13

Removed project-level weekly allocation bars, percentages, target text and week ranges from project cards and project details. Removed the detail-level aggregate remaining-time summary, the display-only aggregation component and its unused props/styles. Kept project metadata, ratings, dates, descriptions, filters, CRUD controls, linked-task counts/navigation and each linked task's status/session length. Task-level weekly tracking remains unchanged. No backend, scheduler, dependency, database or launcher changes.

A genuine GPT-6.1 Sol QA agent updated the focused browser assertions and independently reviewed the source diff; no findings. The lead inspected desktop/mobile screenshots and verified integration.

Executed verification:

- Frontend Vitest: **195 passed** (12 files).
- TypeScript, ESLint and production build: **passed**. Existing nonfatal large-bundle warning remains.
- Project API regression suite: **40 passed**, including project metadata/relationships and scheduling behavior. Existing Starlette/AnyIO deprecation warning remains.
- Backend Ruff: **passed**. Windows solver self-test: **operational / OPTIMAL**.
- Edge Playwright project workflows: **2 passed**. Covers create/edit/delete, metadata/ratings, linked-task navigation, task weekly allocation after real generation, project scheduling eligibility, absent aggregate trackers, four themes and desktop/mobile/tablet accessibility/overflow checks. Browser server used an isolated SQLite database and shut down normally. Existing Node deprecation/color warnings remain.
- Preservation audit: **54 backend/source/launcher/data files unchanged**, including live user data. Full backend and unrelated browser suites were not rerun for this frontend-only cleanup. Launcher source was preserved; no separate launcher smoke test was run.

Evidence: `test-results/project-card-cleanup/` (scoped source backup/diff, test logs, browser report, preservation hashes); screenshots/a11y reports in `test-results/project-screenshots/`. Built frontend assets: `index-BLYmwWtW.js` and `index-BA0CIjo-.css`.

---

# Advanced workload calibration and available-time utilization - 2026-11-13

Implemented [advanced workload/search improvements](ADVANCED_WORKLOAD.md) with three genuine GPT-6.1 Sol agents for weekly opportunities/browser QA, daily CP-SAT search/diagnostics and independent benchmarks. The lead reviewed contracts, implemented API/manual-edit integration and truthful allocation wording, audited data, inspected the generated planner and verified integration.

## Verified causes and implementation

- Current preferences allow 08:00-23:30 with midnight sleep. The original eight-second single-worker High/Very High runs both allocated 525 minutes; Very High ended around 22:35. An original-code 20-second solve allocated all 645 offered minutes, including Waterloo's unsplittable 120-minute session. The 55-minute tail cannot directly hold that session, but rearrangement can. Search quality is a confirmed limitation.
- Weekly forecast emission hid eligible future work and capped split sessions at today's forecast amount. High/Very High now admit positive-value unreserved future sessions as optional candidates. Actual advancement reduces the same session's future prediction without changing saved future schedules or completion credit. Original chunk minima, daily limits, prerequisites and hard constraints remain authoritative.
- Existing workload weights remain intact. Hints respect useful marginal work, daily maxima, home travel and terminal recovery. Complex models use a bounded 20-second portfolio with up to eight workers; simple days retain eight seconds/one worker. Explicit diagnostic budgets are honored. All profiles share the complexity policy. Results disclose budget, workers, bounds and parallel nondeterminism.
- New returned-itinerary capacity/tail diagnostics distinguish free time, minimum chunks, daily caps and known travel without claiming that rearrangement is impossible. Optional supply does not inflate unmet daily work. Manual timing edits clear stale optimality/tail facts. The planner says "Today's planned work is allocated" and retains its completion disclaimer.

## Quantitative results

At the same explicit eight-second budget on ample weekly demand, High/Very High improved from 360/360 to 720/780 productive minutes. Independent final production-policy results on frozen personal inputs:

| Work cutoff | Very Low | Low | Medium | High | Very High |
|---|---:|---:|---:|---:|---:|
|22:30|133|266|375|525|525|
|23:30|145|290|435|525|585|

Values are productive minutes. At 23:30, High/VH importance-weighted minutes were 4005/4335. The independent VH585 plan includes Waterloo120 and ends22:55. Its remaining 35-minute tail cannot directly fit the remaining 60-minute unsplittable session and travel; a shorter optional candidate has reached its daily cap. Other portfolio runs found 640 minutes (weighted4805), and the real API run found635. These are feasible incumbents, not guaranteed optima or identical reruns. The original 20-second645 result is retained as evidence of search limitations. Complete intervals, metrics and methodology are in test-results/advanced-workload/MEASUREMENTS.md.

## Executed final verification

- **807 backend tests passed**, 176.98 seconds; Ruff passed. One existing Starlette/AnyIO warning remains. An earlier concurrent run had 806 passes and one three-second overloaded-search timeout; the unchanged test passed in isolation, then the full quiet run passed807. No feasibility assertion was weakened.
- **195 frontend tests passed on final source**; TypeScript, ESLint and production build passed. The existing bundle-size warning remains. Frontend design is preserved; the sole source change is the truthful empty-unallocated message.
- **10 distinct browser scenarios passed across focused runs**, with no skipped cases. The combined run passed9; an older test incorrectly expected no other schedules after preceding suites had created them. It now seeds a real future plan and compares all other schedules against their exact pre-generation contents. Its complete three-case suite passed, including the corrected case. Evidence: browser-regressions.json, browser-intelligent-final.json and final-verification.json.
- Generation-specific browser/API waits now allow45 seconds for the supported20-second solver budget; other actions keep their prior timeouts. Seventeen affected helper files passed JavaScript syntax checks. Earlier harness encoding and outdated-wait issues were repaired. The unrelated default39-case browser suite was not repeated.
- Browser coverage includes all five workloads at both cutoffs, real generation, fixed anchors, ordered meals, travel, deadline preparation, stale forecasts, mouse/keyboard/emulated-touch meal reordering, locked/impossible meals, and the honest120-minute-session/55-minute-tail case. Edge desktop/mobile were exercised; other engines and physical touch hardware were not tested.
- **Five copied-database API generation requests returned HTTP200**, one per workload in Balanced mode. All schedules passed manual constraint validation and preserved completion credit, metadata and locked work. Strategy separation and Deadline/Deep Work behavior are covered by backend/browser regressions. Evidence: actual-generation-deadline-normalized.json (inherited filename; this run uses Balanced).
- Actual Windows solver health is **operational/OPTIMAL**. The existing launcher passed -NoBrowser -SmokeTest -RequireScheduler at127.0.0.1:8765 on a database copy and shut down gracefully. Neither8765 nor8876 remains listening after QA.
- Live table fingerprints match the pre-change SQLite snapshot; integrity is ok and foreign-key errors are empty. No dependency, migration, security-policy or launcher changes. Backup: data/backups/pre-advanced-workload-20261113.zip. Automated mutations used isolated databases.

Remaining limits: rolling forecasting is not a global multi-day timetable optimization; parallel/time-limited results vary; capacity diagnostics describe the chosen itinerary; automated copied-data routes use frozen cached/estimated offline values. Model construction, weekly forecasting and I/O add elapsed time beyond the daily solve budget. Existing user schedules remain intact; regeneration applies the new behavior.

---

# Workload calibration and scheduling efficiency - 2026-11-12

Implemented [workload calibration](WORKLOAD_CALIBRATION.md) with three genuine GPT-6.1 Sol agents covering daily CP-SAT, weekly marginal utility/browser QA, and independent comparative QA. The lead integrated profile contracts, midnight API/forecast consistency, reviewed changes and verified the complete integration.

- High/Very High now derive distinct positive, diminishing extra-session utility from actual importance, urgency, project and contextual evidence. Completed/finite work cannot gain invented extras; stale zero-value pending proposals do not distort pacing. Rolling-horizon estimates remain forecasts and never overwrite future saved plans.
- Soft productive-span, completion-extent and direct work-gap costs favor compact days. Fixed/meal occupancy and mandatory recovery/travel are distinguished from discretionary gaps. Urgent utility and feasibility remain authoritative; explicit timing preferences and conditional daily minimum behavior are preserved.
- The final circuit arc no longer emits recovery with nothing following. Required recovery before a real home journey and explicit/locked breaks remain. Late-work preferences use configured availability; evening energy preference extends through configured work end. Sleep 00:00 is accepted as end-of-day midnight, including forecast capacity.
- Solver evidence includes objective bounds/gaps, termination reason, candidate supply and extent/idle diagnostics. Explanations identify supply limits, tradeoffs and search uncertainty.

## Executed verification

- Final full backend: **780 passed**, one existing Starlette/AnyIO deprecation warning, 184.23 seconds. Earlier integration run: 775 passed before the final five solver regressions were added. Backend Ruff passed.
- Frontend: **195 tests passed**; TypeScript, ESLint and production build passed. Existing bundle-size warning remains. Frontend source and design were unchanged.
- Playwright: **8 passed**, no skipped/flaky tests in final runs: two new workload/midnight workflows plus six existing intelligent-scheduling and meal-order regressions. Verified all five workload choices, strategy separation, actual generated work, fixed anchors, meals/order, venues/travel, protected history, infeasible order, midnight preferences save/reload, and no pointless terminal recovery. Initial new-fixture mistakes (missing commitment subtype and unsupported overnight work-end input) were corrected; final reports are under test-results/workload-quality and test-results/workload-calibration. The unrelated default 39-case browser suite was not repeated.
- Copied personal database, November 13: **15/15 actual generation API requests returned HTTP 200** across all five workloads and all three strategies, with actual FEASIBLE/OPTIMAL schedules, no conflicts and successful independent manual-constraint validation. Protected history, entity metadata and completion credit were unchanged. Evidence: test-results/workload-calibration/actual-generation-deadline-normalized.json (the reused harness filename; requests cover all strategies).
- Comparative QA: 35 before plus 35 after synthetic schedules passed validation at equal eight-second budgets. A target-met unfinished weekly task produced Medium180/High240/VeryHigh300 productive minutes, all OPTIMAL, versus180 each before. Scattered-anchor spans shortened50 minutes with work unchanged; terminal recovery10 became0. Browser work minutes were45/45/180/225/270. Scarce/full-supply cases correctly remained similar.
- Actual Windows solver health is operational/OPTIMAL. Existing launcher passed -NoBrowser -SmokeTest -RequireScheduler on an isolated database at127.0.0.1:8765 and stopped gracefully. Production assets are unchanged.
- Live data table fingerprints match the pre-change SQLite snapshot; integrity is ok and foreign-key violations are empty. Pre-change source/data backup: data/backups/pre-workload-calibration-20261112.zip. No migration, dependency, security-policy or launcher modification.

## Measured limitations

Complex real-data schedules are not all proven optimal. At eight seconds the copied personal High allocation stayed508 minutes and Very High changed525 to510 because weekly forecasts selected different Friday/Saturday sessions. With30 seconds Very High had510 work within815 span minutes, including175 fixed/classes/meals,75 travel,45 recovery and10 unoccupied minutes; the remaining120-minute task is unsplittable. This is not a proof of a globally best weekly plan. Weighted utility across changed models is not an independent quality score. See the full independent analysis in test-results/workload-calibration/REPORT.md. Tests used Windows Edge; other browser engines and physical touch hardware were not newly tested. Automated routes used frozen cached/estimated offline data.

---

# Draggable meal order ? 2026-11-12

Implemented the focused [meal-order extension](MEAL_ORDER.md) with three GPT-6.1 Sol agents for frontend, scheduling and independent browser QA. The lead reviewed integration, added restart/persistence/history API tests, audited scope/data preservation and ran the full backend suite.

- Existing ordered settings.meals array remains authoritative; no migration, order field, dependency change or regenerated meal IDs. Save preferences persists the reordered objects and invokes existing stale-plan handling. Names, durations, venues, enabled flags and legacy timing preferences are retained.
- A compact grip supports pointer/touch dragging, visible insertion feedback, edge auto-scroll and subtle animation. Move up/down buttons retain keyboard focus and announce positions; Escape cancels; reduced-motion preferences are respected. Repeat dragging settles old animations and guards pointer ownership.
- CP-SAT now requires each enabled meal to finish before the next enabled meal starts. Actual times remain flexible. Disabled definitions are omitted from the sequence. Completed/started/locked records remain protected; infeasible orders name the conflict instead of dropping meals. Independent generated-meal validation also checks actual UTC chronology.
- Solver work is limited to meal precedence, matching protected meal metadata, order-aware hints and conflict explanations. Source comparison confirms workload profiles, weekly forecasting, travel implementation, schemas/API/persistence, dependency files and Windows launcher are unchanged.

## Executed verification

- Full backend: **750 passed**, one existing Starlette/AnyIO deprecation warning, 152.35 seconds. Evidence: test-results/meal-order/backend-final.log. The initial full run caught three unconfigured-meal travel-inference regressions in an overbroad history guard; narrowing it restored all original assertions. The combined focused regression run also passed 278 tests.
- Backend Ruff: **passed**.
- Frontend: **195 tests passed**; TypeScript, ESLint and production build **passed**. Used npm.cmd. Final assets: index-CnnKRtSR.js / index-DmUyAzE8.css. Existing nonfatal bundle-size warning remains.
- Focused Playwright on the final production build: **3/3 passed**, no skipped tests. Verified mouse Breakfast bottom-to-top, insertion feedback, Escape cancellation, keyboard Enter/Space and retained focus, trusted emulated touch with measured auto-scroll, save/reload and exact field/ID persistence, add/delete/disable, all five actual Windows CP-SAT generations, fixed events, meal durations/venues, actual transition walks, return-home travel, waking limits, impossible order and protected locked-history conflicts. All five generation cases returned OPTIMAL. Desktop/mobile accessibility and overflow checks passed; screenshots inspected independently. Evidence: test-results/meal-order/browser-results.json and actual-workload-meal-order.json.
- API integration also closed/reopened the application against its saved SQLite file and proved order/fields/IDs survived restart. Reordering marked the saved plan stale without changing blocks; an inverse completed/locked order returned an explicit conflict and retained original records.
- Windows solver health: **OPTIMAL/operational**. Existing launcher with -NoBrowser -SmokeTest -RequireScheduler passed on a database copy at 127.0.0.1:8765 and shut down gracefully. Final checks found neither 8765 nor the QA port 8876 listening.
- Live personal database table fingerprints match the pre-change snapshot; SQLite integrity is ok and foreign-key errors are empty. All automated mutations used isolated databases. Backup: data/backups/pre-meal-order-20261112.zip. Scope/data audits are under test-results/meal-order/.

No known feature blocker remains. Browser coverage is Microsoft Edge with mouse, keyboard and emulated touch; other browser engines and physical touch hardware were not tested. The full unrelated 39-scenario browser suite was not repeated for this focused extension; full backend/frontend regressions and the targeted browser scenarios were executed. Existing infeasible meal configurations now correctly require an order or editable-constraint adjustment rather than allowing the optimizer to invert the list.

---

# Intelligent scheduling upgrade ? 2026-11-12 evening (Toronto)

Implemented the complete nine-page scheduling guide through the existing CP-SAT architecture. Five genuine GPT-6.1 Sol agents owned daily algorithms, horizon/context modeling, frontend, independent backend review and browser QA; the lead integrated schema/API/persistence, reviewed hard constraints and history, and verified Windows runtime and copied personal data.

See [INTELLIGENT_SCHEDULING_REPORT.md](INTELLIGENT_SCHEDULING_REPORT.md) for behavior, evidence and limitations, and [INTELLIGENT_SCHEDULING_CONTRACT.md](INTELLIGENT_SCHEDULING_CONTRACT.md) for the requirement-to-code mapping.

## Delivered

- Essential flexible meals; new-profile Breakfast30/Lunch45/Dinner30 defaults; preserved custom durations and optional legacy timing preferences; optional actual venue, enabled toggle, stable identities and protected history. No mandatory meal clock fields. Awake hours remain separate from work availability.
- Sustained-focus recovery, meaningful five-level workload objectives, independent strategy selection, applied-workload audit and preference staleness. Fixed commitments, hard dates, daily maxima, venues and travel stay authoritative.
- Read-only14-day forecasts bounded to28days for relevant explicit dates, including future weekly overrides; remaining-day capacity, competing targets and future-congestion urgency. No forecast writes to future schedules or virtual recurring assignments.
- Conservative contextual rules and evidence, anti-cramming recurring targets, worthwhile extra sessions for unfinished work, confirmed completion and split-credit preservation. Explicit assessment preparation must precede its actual linked assessment; generic links remain soft and stored task dates never change.
- Corrected Deadline First opportunity-cost units for weekly tasks while retaining the legacy task normalization. No paid AI, replacement scheduler, database migration or application dependency change.

## Final executed verification

- `.venv\Scripts\python.exe -m pytest backend/tests -q`: **731 passed**, one existing Starlette/AnyIO deprecation warning,162.75s. Final evidence: `test-results/intelligent-scheduling/backend-final.log`.
- `.venv\Scripts\python.exe -m ruff check backend`: **passed**.
- Frontend typecheck and ESLint: **passed**. Vitest: **190 passed across11files**. Production build: **passed**, with the existing nonfatal chunk-size warning. `npm.cmd` was used because PowerShell blocks the npm.ps1 wrapper; build output was captured with native stderr handling so a warning was not mistaken for a build failure.
- Playwright: **49 distinct scenarios have executed passing evidence, none skipped**. Standard full run38/39 initially, then the remaining theme/map readiness fixture passed its complete focused retest. Completion6/7 initially, then the workload test was updated to assert preserved blocks plus the newly required stale flags and passed. Intelligent acceptance3/3 passed; the five-workload case passed again against final normalized solver code. New-test UTC-versus-offset and preparation-cutoff-field assertions were corrected, and an academic urgency fixture explicitly declares Academic type. No solver was mocked. Details: `test-results/intelligent-scheduling/qa-review-report.json`.
- Final browser workload comparison: VeryLow/Low/Medium/High/VeryHigh scheduled180/225/315/450/450productive minutes with20/30/40/70/70break minutes. All preserved urgent academic work, cutoff, immutable lecture, three required meals, nonoverlap and availability. Mobile accessibility and overflow checks passed; desktop/mobile screenshots were independently inspected.
- Actual November13,2026 copied-personal-database generation: **all15 workload/strategy combinations returnedHTTP200**, real FEASIBLE/OPTIMAL schedules, no hard conflicts, successful manual constraint validation and preserved history. Final normalization affected DeadlineFirst only; its five combinations were rerun successfully, yielding90/240/405/510/525productive minutes. Evidence: `actual-generation.json` and `actual-generation-deadline-normalized.json` under `test-results/intelligent-scheduling/`.
- Live personal database table fingerprints remained unchanged; SQLite integrity=`ok`, foreign-key errors=[]; existing saved schedules, task/project relations and completion records preserved. All destructive generation tests used online SQLite copies.
- Windows solver self-test: **OPTIMAL/operational**; `pip check`: no broken requirements. SmartAppControl registry state remains1(enabled). Active pandas3.0.6 repair and lockfiles remain unchanged; no security action is required.
- Existing PowerShell launcher with `-NoBrowser -SmokeTest -RequireScheduler`: **passed** on copied data at127.0.0.1:8765, compiledfrontend served, then authenticated graceful shutdown confirmed. Stop/backup workflows remain intact. Portable backups now include the authoritative guide folder.

## Data, backup and limits

Pre-change backup: `data/backups/pre-intelligent-scheduling-20261112.zip`. Final source/data backup is created as `data/backups/daycraft-intelligent-scheduling-20261112.zip`, with SQLite snapshot, ZIP checksums and manifest hashes verified separately. Existing archives were retained. No live personal records were migrated or rewritten.

The horizon remains an aggregate forecast rather than a global multi-day optimum. Text rules do not provide general semantic AI understanding. CP-SAT may return FEASIBLE within its interactive budget; higher workload need not yield strictly more minutes, and no work is fabricated. Required meals with no sensible remaining slot produce explicit conflicts rather than assumed completion. Browser routing uses offline/stubbed providers, not live external map services. Nonfatal frontend bundle-size and Starlette/AnyIO warnings remain.

---

# Verified Windows runtime repair - 2026-11-12 evening (Toronto)

**Real schedule generation is restored in the active Windows virtualenv with
Smart App Control still enabled. No Windows Security action is required.**
Three genuine GPT-6.1 Sol agents handled trust/dependency investigation,
process lifecycle and backup/independent browser QA; the lead integrated and
independently checked the active runtime, API, data preservation and packaging.

## Repair and current security evidence

Only **Pandas 3.1.1 -> 3.0.6** changed. Its official PyPI CPython 3.11 Windows
x64 wheel SHA256 and all native bytes were verified, then the complete pinned
application environment was tested in isolation before installation into `.venv`
with `--no-index --no-deps`. Both requirements files pin 3.0.6, installed versions
match the lock and the launcher stamp matches its hash. Python 3.11.9, OR-Tools
9.14.6206, NumPy 2.4.6 and other pins are unchanged. No scheduler algorithm,
objective, time limit, workload semantics, migration or production frontend changed.

Windows 11 25H2 build 26200.9711 retains SAC state 1 and the original
VerifiedAndReputableDesktop policy. Before replacement, direct loading of the
old `algos` file produced WinError 4551 and fresh 3077 record 64150. The old parser
loaded in the later raw-loader check, so its earlier block is historical.
Installed native bytes matched official wheels even when blocked. The new Pandas
extensions remain unsigned but execute under the unchanged policy; this is
observed acceptance on this PC, not a publisher signature or permanent cloud
reputation guarantee. No protection was weakened or policy altered.

The working solver exposed a separate manual-edit roundtrip defect: generated
calendar relationship snapshots were absent from the strict input schema. The
schema now accepts unchanged/omitted snapshots and rejects forged changes with
422. Two real regression cases verify both linked and unlinked contexts. Engine
disposal now runs in lifespan `finally`. Original files and lockfiles are retained
under `test-results/runtime-repair/pre-edit/`.

## Actually executed after repair

- Active solver self-test: **exit 0, operational / ready / OPTIMAL**; `pip check`
  passes; `/api/solver-health` returns 200. All **46** installed Pandas native
  entries match the verified official wheel.
- Actual November 13 generation on a SQLite backup: **15/15 HTTP 200 FEASIBLE**
  schedules (five workload levels x three independent optimization strategies).
  Each had real blocks, no conflicts and passed a real manual constraint
  validation request. Medium + Balanced succeeds. Workload used as strategy
  remains 422. This does not claim globally optimal personal schedules.
- Active exact full backend command: **653 passed, one failed**, one existing
  Starlette/AnyIO warning, 136.97s. The synthetic overloaded case exceeded its
  three-second solver budget during concurrent browser work. With browsers
  stopped, that **unchanged test passed alone, exit 0, 3.56s**. Both logs remain;
  this is passing coverage of all 654 cases across separate runs, not a claim
  that the full invocation was green. The isolated candidate had also passed
  653 cases plus that separately run overload case before active promotion.
- Frontend: **184 Vitest tests passed**, TypeScript, ESLint and production build
  passed. Backend and changed helper-script Ruff passed. The existing Vite
  >500kB chunk-size warning remains nonfatal.
- Shutdown/backup helpers: **25 tests passed**, including live-WAL consistent
  snapshotting, uncommitted-work exclusion, corruption/FK rejection, archive
  collision safety, both CMD entry points, exact-instance authentication,
  stale-record refusal, parent identity, SQLite preservation and WAL release.
- Active Windows launcher integration passed: CMD startup, compiled workspace,
  actual solver readiness, occupied-port fallback, repeated launch before
  migration, strict ready-instance reuse and graceful parent-exit cleanup.
- Broad Edge suite: **35 passed, four failed, 29.5m**. Two fresh-profile theme
  assumptions, one asynchronous selected-week fixture and outdated confirmation
  wording were corrected. Active targeted reruns passed the four cases (three
  together, remaining venue case separately). All **39** workflows have passing
  coverage across those runs. An intermediate incorrect venue wait is retained
  as a failed attempt. No product behavior was weakened to satisfy these tests.
- Final **active** Edge generation workflow: **one test passed, 1.5m**, executing
  all five persisted workload levels on copied personal data, with a rendered
  Medium-success screenshot. Earlier candidate generation/retry suite passed
  two tests; its simulated-unavailable response test is not claimed as real
  solver success. No browser test was skipped in the broad run.

## Data, shutdown and backup

Original personal tables, settings, relationships and saved schedules match the
pre-repair SQLite snapshot. Integrity is `ok`, foreign-key errors are empty.
Generation preserves task/project/calendar metadata. The personal sample has
zero credited chunks/completed logical sessions/pre-existing locked work;
nonempty history and locks were exercised by backend/browser fixtures instead.

`Stop Daycraft.cmd` uses an authenticated per-instance graceful request, never
global Python termination. Startup is serialized; exact workspace/database and
parent creation identities are checked. Closing VS Code/Codex does not imply
closing a separate launcher. Test instances were stopped and default port 8765
was left unused so the project can be packaged.

`Backup Daycraft.cmd` creates a SQLite online snapshot and source/data ZIP with
integrity/FK/CRC/SHA256 verification. It excludes caches, virtualenvs, node_modules,
raw live DB journals and runtime tokens; no existing archive is overwritten.
`--full` and separately stopped full-folder copies remain available. Release
archive: **`data/backups/daycraft-runtime-repair-20261112.zip`**. Its independent
audit compares every table with both the live source and the initial pre-repair
snapshot; see `test-results/runtime-repair/final-backup-verification.json`.

Evidence is under `test-results/runtime-repair/`, including `active-health.json`,
`active-runtime-verification.json`, `actual-generation.json`,
`active-backend-full.log`, `active-overload-isolated.log`, `final-helper-tests.log`,
`active-launcher.log`, `candidate-default-initial/`, `active-fixtures-initial/`,
`active-venue-final/` and the final generation report. Prior collection errors,
503s and candidate failures remain recorded as failures, not successes.

Limits: the three-second stress case is sensitive to competing work; normal
CP-SAT timeouts remain explicit. No dependency configuration can guarantee future
Windows reputation acceptance. Maps used offline/stubbed providers and Edge
emulated viewports; live provider service and other browsers were not revalidated.
Two initial cold isolated probes timed out before later exact probes passed.
See [RUNTIME_REPAIR_REPORT.md](RUNTIME_REPAIR_REPORT.md),
[WINDOWS_RUNTIME.md](WINDOWS_RUNTIME.md), [PROCESS_LIFECYCLE.md](PROCESS_LIFECYCLE.md)
and [BACKUP.md](BACKUP.md).

---

# Earlier Windows runtime policy diagnosis and solver readiness - 2026-11-12

**Schedule generation remains externally blocked; no repair-complete claim.** Reproduced the user's current **Medium**, November13,2026 request on actual Windows localhost8765 after backing up the personal database. It returned503 before model construction. Exact Windows CodeIntegrity event XML now identifies **Smart App Control**, policy `VerifiedAndReputableDesktop`, GUID `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`, policy ID27555.1000.240208. Event3077/status0xc0e90002 blocks both `.venv/Lib/site-packages/pandas/_libs/pandas_parser.cp311-win_amd64.pyd` and `algos.cp311-win_amd64.pyd`; correlated3033/3089 and exact timestamps/record IDs/hashes are saved in `test-results/windows-runtime/windows-policy-evidence.json`. Both files are NotSigned; Python executables have valid Python Software Foundation signatures. Registry and active policy file corroborate SAC. No matching AppLocker event was found. CiTool/DeviceGuard access was denied by Windows even after approved read-only escalation; this did not prevent identification from the blocking event itself.

**Correction to prior guidance:** this is a built-in consumer Windows policy, not evidence of an organization-managed PC. Microsoft's documentation identifies the exact policy GUID as SAC and says SAC has no individual-app allow exception. Ordinary administrator rights cannot supply that exception. Earlier generic advice to ask an administrator to simply approve the file is superseded by [WINDOWS_RUNTIME.md](WINDOWS_RUNTIME.md), with Microsoft sources, read-only Event Viewer/Security inspection, Feedback Hub and valid publisher-signing routes. No cloud reputation decision or precise enforcement-transition date can be established. No security protection, policy, package binary or execution environment was changed to evade the block.

Dependency findings: intended CPython3.11.9 x64 virtualenv; OR-Tools9.14.6206, Pandas3.1.1, NumPy2.4.6. `pip check` passed. Installed RECORD verification checked223/1063/1605 hashed files respectively with zero missing/mismatches; this establishes installed consistency, not remote wheel provenance. Lockfile/dependency stamp agree. Daycraft does not use Pandas tables directly, but the official CP-SAT Python wrapper imports Pandas unconditionally, evaluates its types and declares it required. Removing/stubbing it or blindly reinstalling identical files is not a supported fix. No independently trusted replacement build was established, so no speculative dependency substitution occurred. Evidence: `dependency-analysis.json` / `dependency-signatures.json` in the runtime results directory.

Implemented `backend/app/solver_health.py`: a bounded hidden same-interpreter child must import the real solver, validate a tiny known-feasible model, obtain FEASIBLE/OPTIMAL and confirm the solved variable before reporting operational. It separates missing packages, explicit policy blocks, other load failures, configuration failures, native crashes and timeout. No database is opened. Detailed exceptions stay in local logs. `GET /api/solver-health` returns200 only operational,503 unavailable; existing `/health` remains workspace/process liveness. Generation's policy message now shares the accurate recovery guidance and retains the user's plan.

The existing Windows launcher now runs the actual probe, writes timestamped solver JSON/traceback logs, and distinguishes **Workspace ready** from **Scheduling ready**. Normal startup keeps the workspace available with an explicit solver warning. Optional `-RequireScheduler` fails before migrations/server startup if the real probe cannot pass. `Launch Schedule Builder.cmd` remains unchanged, as does localhost8765. No solver/objective, workload semantics, calendar, task or completion accounting changed. Four genuine GPT-6.1 Sol agents handled Windows diagnostics, dependency analysis, health implementation and independent QA; lead integrated/reviewed APIs/launcher, verified official guidance and actual live behavior.

Actual verification: **97 targeted backend tests passed**, including26 health tests and13 independent edge/API review tests; Ruff passed. These use explicitly simulated dependency outcomes for classification, not claims of successful real optimization. Frontend TypeScript and production build passed (existing large-bundle warning). Full Python suite was attempted and stopped on3 scheduler collection errors from the same blocked native import. Actual Windows minimal-solver CLI returned exit1/unavailable/windows_policy_blocked before model creation. Real copied-data API check returned liveness200, solver-health503 with a byte-for-byte equivalent SQL dump. Normal isolated launcher smoke at9197 passed workspace startup/migrations/compiled frontend/cleanup and explicitly warned scheduling unavailable; strict launcher check correctly returned exit1 without starting a server. Logs: `launcher-workspace.log`, `launcher-strict.log`, `api-review.json`, `full-backend-attempt.log` under `test-results/windows-runtime/`.

Real Edge browser testing exercised all five workload levels plus each Retry: all10 valid Balanced POSTs returned503 with saved plans unchanged. The required-success generation workflow remains **FAILED** (five200 expectations received503); the separate unavailable-response retry workflow passed. An existing90-second Edge failure teardown timeout recurred; QA server31160 shut down cleanly. Report: `test-results/generation-repair/browser-results.json`. No generated success was mocked/skipped. All-five objective equivalence, real scheduling feasibility, travel and regeneration remain unverified until the native import is permitted.

Activated the new readiness endpoint and corrected guidance through the existing launcher on8765. Live `/health`200, `/api/solver-health`503 and November13 Medium generation503 are recorded in `test-results/windows-runtime/live-after-health.json`; launcher details in `live-launch.out.log`. Every personal table still matches backup `data/backups/pre-windows-runtime-20261112-173351.sqlite`; integrityOK and no foreign-key violations. Existing Medium preference and all schedules/completion records remain intact. The remaining resolution is legitimate Windows trust/vendor distribution review as documented in the runtime guide, not a hidden application-control bypass.

# Schedule generation failure investigation - 2026-11-12

**Primary request remains unresolved:** the same November 13, 2026 High-workload generation operation still cannot produce a schedule because Windows Application Control blocks the installed Pandas native dependency imported by OR-Tools. This entry does not claim a successful solver repair.

Reproduced against the running personal app after a safe SQLite backup. The saved preference was `high`; the actual generation contract is `POST /api/schedules/generate` with `date: 2026-11-13`, `mode: balanced`, `reoptimize: false`, `include_inactive_projects: false`. The original response was HTTP 500. The live traceback in `logs/server-20261112-165630.err.log` fails at the scheduler import, through OR-Tools `cp_model` and Pandas, before reading task data or applying a strategy. Windows reports `An Application Control policy has blocked this file` for `pandas_parser.cp311-win_amd64.pyd`; subsequent fresh imports also report blocked `algos`. The parser binary matches its installed Pandas RECORD. Installed Pandas 3.1.1 / OR-Tools 9.14.6206 remain unchanged.

Workload and strategy are already separate. All five workload preferences persist independently; `mode: high` returns 422 rather than explaining the reported 500. All three valid strategy values reach the same dependency failure. There is no evidence of a migration incompatibility or a new completion-ledger exception in this failing path.

Implemented bounded corrections in `backend/app/main.py` and `frontend/src/App.tsx`: external solver import failures now return an actionable HTTP 503 while retaining the full logged traceback and original saved plan. Application programming errors and solver-runtime exceptions remain outside this narrow handler. **Retry generation** now repeats the exact failed POST instead of merely loading `/state`; stale date context is cleared and a refresh failure after successful generation cannot trigger a duplicate POST. Optimizer weights, workload influence, scheduling constraints, dependency packages and Windows policies were not changed.

Three genuine GPT-6.1 Sol agents handled backend diagnostics/tests, frontend/API integration, and independent database/browser QA. Lead reproduced the actual live fault, verified dependency integrity and the full persisted-data snapshot, reviewed the code, tested all five workload values/all three strategies on a personal-data copy, and activated the diagnostic/retry changes through the existing launcher. A normal sandbox process-stop denial required approved escalation solely to restart the identified Daycraft process; it did not bypass Application Control.

Executed checks: **151 available backend tests passed**, 5 solver-dependent suitability cases deselected; backend Ruff passed. The 151 include 15 new dependency-contract tests and 41 session-completion tests. Full backend pytest was attempted and failed collection in three scheduler modules due to the same policy block. Frontend TypeScript, ESLint, **184 tests**, and production build passed; the 184 tests were rerun after the final date-context correction. Final assets: `index-BAe1dhH-.js` / `index-DOEbybKO.css`. Existing Starlette/AnyIO deprecation and large-bundle warnings remain. Isolated launcher smoke on copied personal data at port9196 passed migrations, startup, health, frontend serving and cleanup; this is not a scheduling test.

Final browser verification: **7/7 existing completion/workload Edge workflows passed**, with **20 accessibility/responsive audits** across four themes and desktop/mobile, 0 skipped/flaky. These confirm past confirmation/undo, future rejection, split/week accounting, above-target work, withdrawn history, preference synchronization and persistence. Report: `test-results/generation-completion-regression-browser-results.json`; matching HTML and screenshots use the same prefix. QA process 28040 at port8876 shut down cleanly. The dedicated generation suite's separate unavailable-response retry test passed; its **real generation-success test FAILED**, with five HTTP200 assertions receiving503. Actual UI request/response attachments verify five initial requests plus five identical retries, all with valid Balanced strategy and no workload field. The failed workflow also encountered a 90-second Edge teardown timeout while retaining diagnostics; the server ultimately shut down cleanly. Failure report: `test-results/generation-repair/browser-results.json`. Lead inspected the actual failure screenshot and clear error/retry layout. No solver-success response was mocked or skipped to produce a passing generation claim.

Direct real API tests on an isolated copy exercised all five workload values and all three supported strategies. Every valid request reached the dependency failure and returned 503 with unchanged saved state. They did **not** generate schedules. Live recheck after activation also returned the explicit 503 for High + Balanced. The existing localhost workflow is running at **127.0.0.1:8765** with the new diagnostics, but its solver remains unavailable.

Data evidence: backup `data/backups/pre-generation-repair-20261112-170143.sqlite`; every live table still matches that backup after restart and the failed request, including the user's saved High preference. Integrity and foreign-key checks pass. Evidence is under `test-results/generation-repair/`: `live-reproduction.json`, `live-after-diagnostics.json`, `dependency-integrity.json`, `direct-api-results.json`, `direct-api-log.txt`, `available-backend.log`, `full-backend-attempt.log`. Details and external resolution: [GENERATION_FAILURE.md](GENERATION_FAILURE.md). An administrator must review/allow the required trusted native dependencies through normal device policy before full generation, reoptimization, travel feasibility and preserved-completion solver tests can be verified. No bypass or substitute scheduler was introduced.

# Saved session confirmation and workload preferences - 2026-11-12

Implemented Daily Planner **Mark Session Completed** and **Undo Completion** against actual saved task work blocks. The server rejects positive confirmation before the stored end instant, protects evidence from client edits, checks stable ledger identities, and makes repeat requests idempotent. Split chunks credit actual minutes in the existing ledger; full logical-session counts, per-week independence and task lifecycle remain separate. Undo restores the prior block status without erasing older baseline credit. Historical withdrawn work can be confirmed without reactivating deleted tasks/weeks. Existing finite legacy counters retain exact reversible contributions, including work beyond an exhausted estimate; no historical logical sessions or timestamps are fabricated.

Regeneration now retains elapsed unconfirmed task blocks as reservations available for later confirmation, without awarding credit. Their identities, timing and actual venues remain protected; the weekly adapter reserves their existing minutes. Completion updates saved daily/weekly display projections without invoking the solver. Generic manual edits cannot combine a changed interval with completion to bypass the future guard. Bulk legacy session completion atomically rejects future chunks.

Overview and Daily Planner share the labeled five-level Workload Level selector (Very Low, Low, Medium, High, Very High). Preferences persist per date in the existing Configuration store, default to Medium and synchronize across pages. They have **no effect on optimization**. Existing balanced/deadline/deep strategies remain separate; omitted generation mode preserves the saved day's strategy and defaults to balanced for a new day. The UI explicitly says workload adjustments are coming soon. No schema migration or launcher changes were needed.

Genuine GPT-6.1 Sol agents delivered backend/data, frontend/UX, scheduling integration and independent QA. Lead reviewed integration, added actual-data replay, caught and corrected a future-time-edit confirmation bypass and nullable legacy reversal edge case with the backend owner, and fixed a mobile selector clipping defect found in screenshot review.

Executed verification:

- **136 backend tests passed**, 5 solver-dependent cases deliberately deselected from the available suite; this includes 41 new confirmation/preference cases and 2 pure daily-counter tests. Exact command: `test-results/completion-backend-command.txt`; output: `test-results/completion-backend-available.log`. Backend and integration-script Ruff passed. One existing Starlette/AnyIO deprecation warning remains.
- **184 frontend tests passed** across 10 files. TypeScript, ESLint and production build passed. Final assets: `index-C4IX40mR.js` and `index-DOEbybKO.css`. Existing nonfatal large-bundle warning remains.
- **7/7 focused Edge/Playwright workflows passed**, 0 skipped/flaky. **20 accessibility and responsive-layout audits passed**, including the new selector-within-hero check, across four themes and desktop/mobile. Lead inspected actual screenshots. These tests use a real isolated API/database with explicitly seeded saved plans, not generated solver results. Final report: `test-results/completion-layout-final-browser-results.json`; screenshots/report directory: `test-results/completion-layout-final-*`.
- Six older generation workflows were updated to respect elapsed-only confirmation; syntax and collection checks passed (39 default workflows, 7 dedicated confirmation workflows). Those generation workflows remain unrun under the dependency block. The dedicated command is `npm.cmd --prefix e2e test -- --config=playwright.completion.config.js`.
- Isolated Windows launcher smoke at port **9195** passed migrations, startup, health, compiled frontend and cleanup. QA port 8876 shut down cleanly. The default localhost address and `Launch Schedule Builder.cmd` remain unchanged.
- `scripts/verify_session_completion.py` replayed actual personal saved IDs on a database copy: real-clock future confirmation was rejected; an explicitly simulated later clock verified confirmation, repeat idempotence, restart persistence, exact undo, and elapsed reservation preservation. All five workload values left settings and saved plans unchanged. This is not evidence that actual personal work was completed. Result: `test-results/session-completion/personal-replay.json`.

Data preservation: `data/backups/pre-session-completion-20261112-163942.sqlite` contains the pre-task backup. Every live personal table still matches it, including 12 task definitions, 8 materialized task weeks, 5 logical sessions, 4 chunks, 2 schedules, 6 activities, 26 occurrences and 2 projects. SQLite integrity is OK and foreign-key checks are clean. No personal completion or workload preference was written during verification.

**Remaining blocker:** an actual full `python -m pytest backend/tests -q` attempt failed during collection in the three solver modules because Windows Application Control rejects the existing `.venv/Lib/site-packages/pandas/_libs/pandas_parser.cp311-win_amd64.pyd`. Current evidence: `test-results/session-completion/full-backend-attempt.log`. The earlier approved outside-sandbox attempt failed identically; the user chose to finish available checks and report the blocker. No security policy or package binary was changed. New CP-SAT regeneration/partial-session regression tests are authored but **not executed**. Full generation, travel feasibility and the complete generation-based browser suite therefore remain unverified for this change.

The existing process at **127.0.0.1:8765** remains healthy and was not restarted. Updated backend code is **not activated in that process**; the compiled frontend is on disk. Normal device-administrator resolution of the blocked trusted dependency is still needed for full solver verification and safe activation. Do not interpret the passing saved-plan tests as a successful fresh schedule generation. Contract and manual verification: [SESSION_COMPLETION_WORKLOAD.md](SESSION_COMPLETION_WORKLOAD.md).

# Task deletion, library associations and related entities - 2026-11-12

Root cause verified against the personal database and existing API: the Week Specific action removed only the assignment. The temporary `hi` definition (stable ID `946c47d8-5ade-4394-81c3-b5a23653361b`) remained active at CMH, so Task Library and the map correctly continued reading it. It was not a duplicated calendar occurrence or stale map cache. The audit found no remaining assignment, session, saved schedule block, project/activity link, recurrence or inbound dependency for that exact task. Unassigned definitions are otherwise valid library data and were not blanket-deleted.

Implemented explicit confirmed Remove from this week, Delete task everywhere, and Stop repeating operations. Removal keeps definition/other weeks and retains a hidden history row; full deletion tombstones identity, detaches active associations, cleans dependencies and cancels future pending work including locked pending blocks. Past, started and completed evidence remains. Maps exclude deleted definitions and legacy aliases, including fallback entries from old plans. Stop repeating retains past recurrence and suppresses both lazy and materialized future demand. Explicit reuse/copy after the cutoff uses week-specific source semantics without duplicating automatically recurring work. Library cards display actual global association summaries: Every Week, one Sunday-Saturday range, expandable Multiple weeks, or Unassigned.

Tasks and commitments now share a grouped searchable selector with the requested full field label. Tasks reuse their existing independent project/activity fields and retain old dual links; commitments use validated typed entity IDs. Missing, self and circular targets are rejected, renames resolve live, and deletions detach links. Current context reaches task planning and fixed commitment blocks without invented deadlines, venues or extra events. Project priorities and linked-assessment urgency retain the existing deterministic rules. No LLM service or schema migration was added.

Independent review found and corrected regeneration/manual-edit edge cases for withdrawn in-progress and elapsed unlocked work. History-only validation units preserve recorded identities/venues without new scheduling candidates; server-derived snapshot protection cannot be forged through manual edits. Existing overlap, time, travel and recovery validation remains authoritative. New solver regression tests are authored but are NOT reported as passing because of the environment blocker below.

Genuine GPT-6.1 Sol agents handled backend integrity, frontend, independent browser QA and a separate scheduling review. Lead established contracts, traced real data, reviewed integration, added scheduler safeguards, fixed the reported live leftover through the existing API, and ran isolated personal-data and launcher checks.

Executed checks: 52 selected backend tests passed (37 deliberately deselected methods require other coverage), including 15 lifecycle/service tests; backend Ruff and compilation passed. Full backend pytest was attempted and stopped at collection with three scheduler-module errors. Final frontend checks passed 175 tests, TypeScript, ESLint and production build; assets `index-CJDkkMbg.js` / `index-BoK0T0bb.css`. Eight distinct real Edge browser workflows passed across initial runs and corrected fixture reruns; 36 theme/accessibility/overflow audits were clean. The final routing regression verified a 47-minute manual override and its non-estimated provenance in both callback and route matrix for an elapsed withdrawn unlocked block. Final affected-workflow rerun passed 4/4 on the exact final assets in 163 seconds, with zero failures/skips/flaky results. All 52 final WCAG/overflow audits passed across four themes and desktop/390px mobile, including normal and empty task/commitment selectors, library labels and lifecycle confirmations. Keyboard input on empty results preserved existing selected IDs. Explicit assignment and UI copying after recurrence cutoff passed while historical recurrence remained intact. Audit workflows recorded zero page errors. Lead inspected final mobile empty-search and commitment-picker screenshots. Evidence: `test-results/lifecycle-final-browser-results.json`, `lifecycle-final-browser-report/index.html`, `lifecycle-final-task-relationships/`, and `lifecycle-final-screenshots/`. All QA servers shut down; port 8876 is closed. Existing Starlette/AnyIO deprecation and Vite bundle-size warnings remain.

Live repair: `scripts/repair_reported_hi.py` defaults to read-only. After exact-ID/location/history/dependency revalidation, its --apply used the existing localhost DELETE endpoint, preserved CMH, and proved every other table/record unchanged. A second invocation made no change. Backup: `data/backups/pre-reported-hi-repair-20261112-150317.sqlite`; evidence: `test-results/task-lifecycle/reported-hi-repair.json`. The initial broader backup/audit is `data/backups/pre-task-lifecycle-20261112-145414.sqlite` / `test-results/task-lifecycle/before-audit.json`.

`scripts/verify_task_lifecycle.py` passed on a fresh copy of the resulting personal database, preserving all 12 remaining definitions, course/project/activity links and the original database. Current project and linked commitment metadata reached the planning adapter and produced exactly one fixed block per actual occurrence. Deletion and commitment links persisted after reopening the copied app/database. SQLite integrity and foreign-key checks passed. This replay does not execute CP-SAT. Evidence: `test-results/task-lifecycle/integration-summary.json`. Isolated launcher smoke at port 9194 passed migrations, startup, health, compiled frontend and cleanup; default 8765 and launcher sources remain unchanged.

BLOCKER: Windows Code Integrity events 3077/3033 reject the existing `.venv/Lib/site-packages/pandas/_libs/pandas_parser.cp311-win_amd64.pyd` under enterprise signing policy `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. Approved outside-sandbox pytest failed identically. The file's SHA256 matches the installed Pandas 3.1.1 RECORD. An actual isolated schedule-generation request returned HTTP 500 at that import. No package binary or security setting was modified. The user explicitly chose to finish available checks and report the blocker. Full solver/regeneration tests, three authored generated-history browser scenarios and the full 39-workflow browser regression remain unverified. Existing pass counts from prior tasks are not evidence for this change.

The current app process at 8765 was left running; the updated backend has not been activated because a new process cannot load the optimizer dependency. The frontend build is ready on disk. Allowing the trusted dependency through the device's normal policy process is required before full scheduling verification and safe activation. Browser tests used Edge with emulated viewports, offline routing/manual fixtures and stubbed tiles; live external providers were not reverified. Details: `TASK_LIFECYCLE_AND_RELATIONS.md`, `test-results/LIFECYCLE_QA.md` and reports under `test-results/task-lifecycle/`.

# Task relationships, allocation and explicit completion - 2026-11-12

Implemented the existing activity foreign key as a shared searchable picker for all class, assessment and commitment categories, including weekly overrides. Course inputs are removed; old values remain safely stored/readable. Current joined metadata and canonical occurrences reach planning, with a bounded deterministic soft urgency term for linked upcoming assessments. It never invents a hard task deadline or occupied interval. Rename/deletion and occurrence edits invalidate linked plans; deletion preserves the task/history and clears live links.

Weekly target indicators now describe allocation, with separate pending future/elapsed minutes and verified history. Logical sessions count once across split chunks. Removed manual task-card session logging; planner work evidence remains supported. Explicit task completion/reopening is separate from work credit and stops/resumes future planning without rewriting the ledger or remaining estimate. The legacy API no longer fabricates all-session completion from a task status change or closes the task when remaining work reaches zero. Definition completion cannot be bypassed with a weekly active override. Soft weekly goals, extra sessions, daily hard maximums, travel and explicit deadlines remain intact.

Forms use the requested Every Week / Week Specific / Task Library target labels and selected-week helper. Week creation and original assignment editing remain distinct. The relationship picker supports keyboard search and stable IDs for duplicate names; mobile QA prompted a bounded normal-flow dropdown fix. Existing academic records with no subtype now show an honest required placeholder instead of displaying an unselected default.

Genuine GPT-6.1 Sol agents delivered backend/data, scheduling, frontend and independent QA. Lead reviewed integration, fixed the completed-definition override escape, updated contracts, and replayed the actual personal database on an isolated copy. No schema migration or LLM service was needed.

Executed checks: 522 backend tests passed; backend Ruff passed (existing Starlette/AnyIO deprecation warning). Final post-QA frontend verification: 164 tests across eight files passed; TypeScript, ESLint and production build passed. Final assets are `index-D43nUdAW.js` and `index-xT_rmYyK.css`. All 30 distinct Edge/Playwright workflows passed across the full run and corrected targeted reruns: 28/30 in the full 9.5-minute run, then 2/2 after updating stale test assertions for allocation wording and an accessible label containing helper text. No product code changed between those runs. Final reports are `test-results/task-relationships/full-browser-results.json` and `corrected-browser-results.json`. Root verification script Ruff passed. Isolated Windows launcher smoke at 9193 passed migration/startup/health/compiled frontend and cleanup; launcher source and default 8765 remain unchanged. Existing Vite bundle-size warning remains.

Final browser visual verification: clean-viewport and strengthened last-option click runs each passed 1/1. Across four themes and desktop/mobile, the last result stays fully within the modal and selecting it preserves its stable activity ID. Lead inspected all four clean mobile viewport screenshots. 199 unique WCAG axe audits had zero violations; responsive bounds checks passed. Durable summary: `test-results/task-relationships/qa-summary.json`; extra reports: `clean-viewport-results.json` and `final-popup-results.json`. The isolated QA server shut down cleanly.

Personal-data evidence: backup `data/backups/pre-task-relationships-20261112-030357.sqlite`; replay `scripts/verify_task_relationships.py`; result `test-results/task-relationships/integration-summary.json`. Five preserved course values and five stable activity links survived. Fresh generation met a target with one allocated session and zero verified completion. At a later injected clock, 90 elapsed minutes remained unverified. Explicit close/reopen preserved every logical-session/chunk ledger tuple. All original personal-data tables matched the backup; SQLite integrity and foreign-key checks passed. All test generation was isolated.

The currently running 8765 backend has not been restarted, respecting the request not to restart the application. Backend changes require the next launcher start. Browser testing uses a fresh isolated running application at 8876. Pending elapsed work remains reserved until the user explicitly resolves a planner block; it is not assumed missed or completed. Browser/provider tests use offline/manual route fixtures and do not reverify live external routing. See `TASK_RELATIONSHIPS.md` and `TASKS_CONTRACT.md` for the contract.

# Semantic venue suitability and morning scheduling repair ? 2026-11-12

Two distinct causes were established. Preferred locations had been limited to an explicit opt-in whitelist, which made a single selected preference behave as the only permitted venue. Separately, the sequence model forced every remote/unspecified node (including lunch) to inherit its predecessor's physical position. Lunch ending exactly at a fixed MC class therefore forced preceding work to be at MC too, even when hours of idle time were available for travel before lunch. The earlier arbitrary-MC substitution masked this scheduling defect.

The semantic layer now derives conservative activity requirements from structured fields, title/description and project context, or uses the user's explicit complete requirements. It never infers facilities/access from place names or coordinates. Preferred candidates include verified matching capabilities plus confirmed access, and suitable activity-specific user confirmations. Required locations remain hard constraints. Candidate IDs, evidence, confidence and limitations are server-derived; manual requests cannot forge them. Actual-venue exports and map visits use the actual place?s room/building, preserving configured room metadata. Valid saved calendar occurrences overlay their actual venue once in the map, while reusable definitions keep the original preference; stale future adapter-locked events cannot override updated calendar sources. Requirements and evidence propagate through recurring definitions, effective weeks, occurrences, logical sessions, split chunks, routes and persisted plans. Existing data receives safe empty defaults without a schema migration. Versioned read-only stale handling prompts regeneration of obsolete pending plans; historical records remain intact.

The solver now permits physically reachable relocation before flexible nodes, reserving actual travel. Priorities, weekly/daily targets, working hours, positive preference penalty, solver seed and time budget were retained. Diagnostics include objective/bound and effective work hours. Daily Planner distinguishes actual/preferred places, shows evidence without AI claims, and suppresses exact obsolete location explanations in old plans without altering their stored text. Optional compact controls support reusable venue needs and verified saved-place facilities/access in Maps and the shared picker.

Genuine parallel GPT-6.1 Sol agents implemented backend/semantic rules, scheduling, frontend and independent QA. Lead established contracts, reviewed safeguards, captured identical actual inputs, verified integration and data preservation, and restarted the existing Windows launcher.

Executed automated checks: 494 backend tests passed; backend Ruff passed (one existing Starlette/AnyIO warning). 154 frontend tests passed; TypeScript, ESLint and production build passed (existing chunk-size warning). Final Edge/Playwright suite: 27/27 passed in one invocation (6.1 minutes), including all four semantic venue workflows. The new workflows produced 25 clean accessibility/overflow audits across four themes and desktop/mobile layouts. Final screenshots confirm compact schedule cards, readable capability controls, complete expanded evidence and the corrected middle-dot separator. Evidence: test-results/semantic-location/qa-review.json; final browser artifacts: test-results/semantic-location/browser-1794468488179.

Controlled regression evidence: test-results/semantic-location/actual-solver-inputs.json is the same captured task/day/settings/route input for both solvers. Preserved baseline first event at 12:00, first work at 14:35; fixed solver first work at 08:00. Both OPTIMAL; 315 productive minutes retained, 0 unallocated. Fixed plan has 65 travel minutes and no independent validation errors. A separate full API replay of the personal database copy persisted the 08:00 plan and kept Gym's 90-minute session at PAC. Sources/results are in test-results/semantic-baseline/ and test-results/semantic-location/. No universal 08:00 start was added; synthetic late preferences, explicit earliest starts, current-time bounds and impossible travel scenarios retain their appropriate later starts.

Data/runtime verification: backup data/backups/pre-semantic-location-20261112-015406.sqlite. scripts/verify_semantic_locations.py compared every personal-data table with that backup and passed integrity/foreign-key checks. All generation writes were confined to isolated copies. scripts/verify_semantic_browser.mjs inspected the actual localhost personal plan with every API mutation blocked: old plan is flagged for regeneration, PAC preserved, flexible wording present, obsolete restriction sentences absent. Existing launcher is running at 127.0.0.1:8765 and serves index-CP6foIGW.js.

Limits: semantic interpretation is deterministic, conservative and English rule based; no LLM calls/dependency were added. Facility/access verification comes from explicit user knowledge, not live inspections or opening-hours/booking services. User-supplied custom requirements support unsupported activities. Ambiguous needs retain the preferred venue unless separately confirmed alternatives exist. Replay/QA routes use labeled offline estimates or deterministic manual fixtures; these tests do not verify live walking routes. Reoptimize the flagged November 13 plan to apply the repaired solver; locked/started work remains protected.

# Explicit venue permissions and Gym/PAC integrity repair ? 2026-11-12

Root cause reproduced from the actual personal database and live API: Gym's recurring definition and effective weekly assignment both selected PAC, while its saved 2026-11-13 schedule block selected MC as the actual venue. The CP-SAT preferred-location domain admitted every known venue with a small preference penalty. No incorrect PAC ID or task association was found.

The solver now uses only the configured physical venue unless preferred-place substitution is explicitly enabled with a whitelist of suitable saved-place IDs. Required places remain hard constraints. Existing records default to no substitution; no schema migration or historical rewrite was needed. Shared API validation, weekly/calendar propagation, route matrices, reference guards, manual edits and export agree on configured versus actual venue. Manual physical edits materialize the selected actual venue before feasibility validation. Protected history requires trusted server records. Unknown locations remain visibly unknown; remote activities retain continuity without claiming a mandatory destination.

The shared picker exposes optional alternative-location consent and suitable saved places. Weekly overrides now receive only location fields, fixing an integration defect found by browser QA. Planner/dashboard distinguish planned from preferred venues; old unauthorized actual venues carry an explicit warning. Unsafe unlocked, unstarted current/future legacy plans are flagged stale on read, require regeneration before editing/exporting, and retain original stored blocks. Relevant definition/occurrence/venue edits invalidate dependent plans.

Parallel GPT-6.1 Sol contributions: backend/API and data integrity, solver constraints/validation, frontend forms and presentation, and independent browser QA/review. Lead traced actual data, reviewed integration, corrected shared picker serialization and historical venue wording, and verified the launcher and personal-data replay.

Executed final checks: 457 backend tests passed (one preexisting Starlette/AnyIO warning); backend Ruff passed. 142 frontend tests passed; TypeScript, ESLint and production build passed (existing bundle-size warning). Full Edge browser run: 24/25 passed in 6.9 minutes, including both new venue workflows. The sole failure was an outdated project-test assumption that library creation automatically assigns a week; the test now enters Week Specific explicitly. The corrected project-only rerun passed (1/1, 33.8 seconds). All 25 distinct workflows therefore passed across the full run and targeted rerun; production code did not change between them. 200 accessibility reports generated during the final full run, including nine new venue audits, had zero violations; responsive overflow checks passed. Light/dark desktop/mobile screenshots and the actual personal Gym details were visually inspected. Exact browser results and timestamp-filtered audit evidence: test-results/venue-integrity/qa-summary.json.

Actual-data verification: consistent backup data/backups/pre-venue-integrity-20261112.sqlite. scripts/verify_venue_integrity.py regenerates only an isolated copy of that database. Gym receives a full 90-minute session at PAC and a separate 15-minute estimated walk beforehand. Every personal-data table matches the backup; SQLite integrity and foreign-key checks pass. Evidence: test-results/venue-integrity-before.json and venue-integrity-after.json. scripts/verify_venue_browser.mjs verifies the actual running personal plan is marked stale and distinguishes recorded MC from preferred PAC, with all API writes blocked. The original plan remains untouched. The normal Windows launcher was restarted successfully at 127.0.0.1:8765 and serves index-wxKm3e9h.js.

Limits: replay and browser routing tests use labeled offline estimates/manual route fixtures, not newly verified live walking routes. A read-only live SLC search smoke returned the correct provider-backed cached result; it is not evidence of a new external-provider request. Venue suitability is explicitly selected by the user, not inferred by AI. In Daily Planner, select November 13 and Reoptimize day to replace the flagged old plan using the corrected venue rules; locked/started history is preserved.

# Simplified Week Specific task creation — 2026-11-12

Focused TaskEditor UX change, with existing APIs and persistence retained. Week Specific creation captures the page's selected Sunday–Saturday week automatically. Removed Weekly intention, assignment checkbox and week picker. Minimum sessions this week is a regular field directly below session length. Existing assignment context is captured when editing, and editing a reusable definition never creates a new assignment merely because a week is currently displayed. Recurring creation stays recurring; library creation stays unassigned with a reusable default weekly target. Separate assign/weekly-override dialogs remain available.

Executed verification: 133 frontend unit tests, typecheck, ESLint and production build passed. 98 backend weekly-task/recurrence/scheduling tests passed. All four focused Edge browser workflows passed in one invocation (2.2 minutes): reusable library/weekly progress, all-theme responsive task forms, automatic selected-week creation with assignment-preserving edits, and recurring creation/exceptions/history. All 30 task accessibility audits and overflow checks passed. The updated desktop form screenshot was inspected. The running localhost service is healthy and serves index-BYYR_TBK.js. New browser coverage creates a task from an arbitrary displayed week, verifies its persisted target and assignment, then edits from the library while viewing a different week and checks that the original assignment ID/target remain and no new assignment is created. Existing helper and library expectations were updated for automatic assignment.

No backend, schema, migration, launcher or user-data changes. No subagents were needed. Existing Vite size and Starlette/AnyIO deprecation warnings remain.

# Task management tab separation — 2026-11-11

Focused frontend change; no backend, database, migration, launcher or scheduler changes. No subagents were needed for this fix.

- Week Specific lists and counts only explicit/copied assignments, excluding virtual and materialized recurring assignments by source and definition recurrence. Search, filters and empty states operate on that category. Every Week retains recurring definitions; Task Library retains all reusable definitions.
- Copy selection shares the same category predicate. Assign existing task continues to exclude recurring definitions, with an appropriate empty state when no eligible reusable tasks match.
- Weekly summary metrics still use the complete effective workload and now explicitly explain that they include Every Week and Week Specific tasks. The scheduler still receives both categories.
- Recurring cards provide Adjust selected week to preserve weekly exception/skip management without mixing recurring cards into Week Specific. The exception dialog identifies the selected week.

Actually executed: 133 frontend tests passed; TypeScript, ESLint and production build passed. 76 backend recurrence/weekly scheduling tests passed. Focused browser separation, copying and recurring exception/history workflows passed across reruns. The new separation workflow verified tab counts, filtering, assignment exclusion, library membership, combined summary and real schedule generation with both categories. The initial exception browser selector was corrected to use its accessible combobox role and the rerun passed. Library conversion and all-theme/mobile recurrence/exception/copy browser checks also passed (2 tests in 1.3 minutes). All five distinct focused browser workflows have passing executions across the targeted runs.

The running localhost service remained healthy and serves the new frontend build. Existing Vite size and Starlette/AnyIO warnings remain.

# Location search repair and scheduled-day clarity — 2026-11-11

Delivered with four genuine GPT-6.1 Sol agents: geocoding/backend, frontend/UX, independent scheduling review, and QA. Lead reproduced the live failure, established its cause with an unchanged-backend comparison, coordinated interfaces, reviewed provider/context handling, activated the final build and verified live searches and data preservation.

Root cause and repair:

- The prior agent-launched server inherited the restricted test environment's outbound-network limits. Student Life Centre returned HTTP 503 in 1.16 seconds; QNC Waterloo returned its cached result in 78 milliseconds. Restricted direct requests failed immediately with ConnectError, while approved network-enabled provider requests returned HTTP 200. Restarting the normal launcher with network access BEFORE changing backend code made the identical Student Life Centre query succeed. This was a runtime connectivity regression, not simply a missing alias or empty provider result. Evidence: test-results/search-repair-network-restart.json.
- The old geocoder collapsed HTTP, timeout, network and malformed-response failures into one generic error, had no independent fallback, and expanded only MC/RCH. The new shared search pipeline reuses saved identities, supports 13 campus building codes plus UWaterloo, normalizes names, validates coordinates and building matches, and uses a maximum of two Nominatim attempts plus one independent Photon fallback. Public calls remain explicit submitted searches, rate-limited and timed out; no provider autocomplete is triggered by typing. No coordinates are invented or silently selected.
- Provider errors now distinguish no results, throttling, timeouts, unavailable services, bad configuration, invalid queries and invalid responses. Positive caches last 30 days; empty searches expire after 5 minutes; failed requests are not cached. Existing valid caches remain usable. Diagnostics identify provider/stage/outcome without logging raw personal queries or credential-bearing URLs. The fallback is configurable with GEOCODER_FALLBACK_URL; GEOCODER_URL remains supported.
- Home/map context is coarsened to two decimal places before proximity bias; exact home coordinates stay local. General search is not geographically bounded. Explicit Waterloo aliases use campus bounds and reject unrelated shops or centroids. Generic fallback retains the original query after primary failure. Saved-place filtering remains usable during outages in both the shared picker and standalone manager.
- Both search surfaces show result names, addresses, provenance and confirmation guidance. Marker previews and reusable-place selection remain available. Accessibility review fixed missing names on the standalone manager's saved/draft marker controls.
- Labels now read 'Minimum work blocks on a scheduled day' and 'Maximum work blocks on a scheduled day' across definitions, weekly overrides and related summaries. Helper text states that unscheduled days may have zero blocks. API field names and scheduler semantics were retained: conditional soft minimum, hard maximum, actual daily chunks versus completed weekly logical sessions.

Actually executed:

- Final full Python suite: 429 passed in 83.22 seconds; backend and verification-script Ruff passed. The existing Starlette/AnyIO deprecation warning remains. Focused geocoding checks: 70 passed.
- Independent scheduling review: 145 existing scheduler/weekly tests passed. Real CP-SAT experiments in all three modes verified minimum 2/maximum 4, zero routine work under urgent competition, a one-block soft shortfall, and a 150-minute logical session capped at four 30-minute chunks without receiving full weekly completion credit. Repeated semantic schedules matched; no optimizer defect or code change was needed.
- Frontend: 132 unit tests passed; typecheck, lint and production build passed. Typecheck/lint/build passed again after the marker accessibility fix. Existing Vite bundle-size warning remains.
- Complete Edge Playwright run: all 21 workflows passed in one invocation in 11.9 minutes. All 191 accessibility audits had zero violations and corresponding overflow assertions passed: calendar 10, daily controls/maps 24, locations 32, projects 34, recurrence 33, search 16, tasks 30 and workspace 12. The isolated QA server shut down cleanly. Coverage includes daily fields/weekly persistence/room behavior, grouped-map identity, shared picker errors/local reuse/provider selection/Home persistence, and standalone manager search/persistence. The initial focused manager audit identified unnamed markers; the fix passed its focused rerun and this full run.
- LIVE application API: all seven requested campus queries returned HTTP 200 with valid candidates. SLC's first result came from a fresh Nominatim request; equivalent names reused that verified cache, while existing QNC/MC/EC4 places were correctly reused locally. Additional live queries for mixed-case SLC, Student Life, Quantum Nano, 200 University Avenue West and Toronto City Hall also succeeded. Evidence: search-repair-search.json and search-repair-extra-live.json under test-results.
- LIVE independent fallback: with the primary intentionally pointed at an unavailable local port and a separate cache, real Photon returned SLC, QNC, MC, EC4 and Toronto City Hall. Evidence: test-results/search-independent-fallback-live.json. No mocked provider response was used for these checks.
- LIVE Edge picker smoke verified actual SLC result, exact coordinates and interactive map preview with real OpenStreetMap tiles, plus the new default daily label. All application mutations were blocked; no location/task was saved into personal data. Evidence: test-results/search-repair-live-browser.json and search-repair-live-picker.png.
- Existing Windows launcher started the final backend at 127.0.0.1:8765 with approved provider connectivity. Health passed and served JS/CSS exactly match the tested build (index-CfVFbXat.js/index--snEWeVX.css). No launcher rewrite or self-elevation was introduced. One automatic approval review timed out before execution; its permitted retry succeeded.
- No database migration. A consistent backup was saved at data/backups/pre-search-repair-20261111.sqlite; final original-table fingerprints, integrity and foreign keys match exactly. Existing locations, home preferences, task progress, activities, projects and schedules were preserved.

Limitations: public providers offer no guaranteed availability; saved places/cache and an independent fallback reduce that dependence, and failures remain explicit. Browser regression tests use Edge/emulated viewports and deterministic provider/tiles fixtures; the separate live API and browser checks above verified real connectivity. Daily minimum remains soft, and weekly capacity remains a forecast rather than a seven-day global optimizer.

See SEARCH_REPAIR.md for the operational root cause and DAILY_BLOCKS_CONTRACT.md for unchanged scheduling semantics. To verify: search 'SLC Waterloo' from any Add a location picker, select the Student Life Centre candidate and inspect its pin. No task is forced onto an otherwise unscheduled day by the renamed minimum field.

# Map grouping, conditional rooms and daily task limits — 2026-11-11

Implemented in the existing application with four genuine GPT-6.1 Sol agents: backend/database, frontend/UX, scheduling optimization and independent QA. Lead coordinated the shared contract in DAILY_BLOCKS_CONTRACT.md, reviewed integration, verified the personal-data duplication, ran complete checks and inspected browser screenshots.

- Root cause: the map overview appended a reusable definition and its occurrence as separate entries. The personal database had one Waterloo Reality Labs activity and one occurrence, not duplicate records. The live map now returns one activity at East Campus 4 with its occurrence nested beneath it. No activity or occurrence records were deleted.
- Map aggregation groups by underlying activity/task ID per saved place. Multiple visits, task chunks and weekly assignments retain their own metadata beneath one entry. Different IDs sharing a title stay separate; counts, category/day/week filters, marker popups and detail panels use the same grouped representation. Location changes remove obsolete current associations while preserving historical or protected visits.
- Shared location forms remove Building inputs and show one optional Room Number only for a valid physical place. Required/preferred/remote/unspecified semantics remain intact. Rooms persist on definitions, weekly overrides and individual occurrences; changing or clearing the selected place clears the editable room context. Existing stored building and room values survive migration.
- Tasks expose minimum daily blocks (default 1) and optional maximum daily blocks through recurring, week-specific and library forms, APIs, copying and weekly overrides. Safe integer validation enforces nonnegative minimum, positive maximum and maximum at least minimum. Each split chunk counts as one daily block; weekly completion still requires a full logical session.
- CP-SAT enforces the daily maximum across all internal sessions of the same task, including protected/completed work. Manual edits use the same validation. An already protected over-cap schedule is reported infeasible without deleting history. The minimum is conditional and soft, with bounded preference and explicit shortfalls; zero work remains valid and urgency/hard commitments retain precedence. Manual schedule changes refresh reported daily progress.
- Migration 0007 rewrites no records in the existing JSON-backed schema. Backup: data/backups/pre-daily-limits-20261111.sqlite. Both staged and live audits confirmed unchanged original columns and payload fingerprints, SQLite integrity and foreign keys. No QA records were added to personal data.

Actually executed:
- Full backend: 394 tests passed. Backend and migration-audit Ruff clean. Existing Starlette/AnyIO deprecation warning remains.
- Frontend: 119 tests passed; TypeScript, ESLint and production build passed. Existing Vite bundle-size warning remains.
- All 19 distinct Edge Playwright workflows have passing executions on the unchanged production build: 14 passed in the full invocation, 4 passed in the subsequent five-workflow run, and the remaining geographic-overview workflow passed its corrected focused rerun (27.0 seconds; 31.4 seconds total). This is combined coverage, not a claim of a single 19-pass invocation. Initial failures were obsolete Room labels, removed saved-place room controls and definition/occurrence aggregation text/count assertions; test expectations were updated to the requested behavior.
- Both new workflows passed, covering daily validation/weekly persistence/room clearing and grouped-map identity/nested occurrence editing. Sixteen new screenshots and axe/overflow audits cover room forms and grouped maps in four themes at 390/1440 widths: zero violations and no horizontal overflow. Lead inspected dark desktop/light mobile room and map views plus the task daily-input layout. Existing project, calendar, task, recurrence and location workflows also passed. Independent API review contributed two passing integration tests included in the full backend count.
- Windows launcher integration passed exact .cmd startup, migrations, health/build smoke, occupied-port fallback, existing-instance reuse and parent-exit cleanup. Current build activated through the existing launcher at 127.0.0.1:8765. Served JavaScript/CSS match the tested build byte for byte; live WRL grouping and data-preservation audits passed.

Limits: browser checks use installed Edge and emulated viewports, with external tiles/providers stubbed for deterministic tests. Weekly capacity remains a forecast rather than a global seven-day optimizer; each generated day enforces its actual block cap. Daily minimum is a soft preference, not a mandatory mode. Existing unknown-location and routing fallback limitations remain documented in LOCATIONS_CONTRACT.md.

To verify: open Locations & Map and expand the single Reality Labs entry to see dated visits. In any task editor set minimum 2 and maximum 2; generate a day with enough time and inspect daily progress. Split chunks consume separate daily slots, manual extra blocks are rejected, and a shorter feasible day may report a minimum shortfall. Selecting a physical location reveals Room Number; clearing it or choosing Remote hides and clears the editable room value.

# Universal locations and travel intelligence — 2026-11-11

Delivered in place with five genuine GPT-6.1 Sol specialist agents: frontend/UX, backend/database, geospatial services, scheduling, and independent QA. Lead coordinated contracts, reviewed integration, fixed protected resolved-position edits and Windows route-cache connection cleanup, ran integration/data/launcher checks, and inspected desktop/mobile screenshots.

- Shared compact location picker across classes, assessments, commitments, recurring/task-library/week-specific forms and eligible planner sessions. Saved aliases filter locally; provider searches are explicit; selected results require confirmation. Interactive marker refinement, optional address/building/room/floor/entrance details, saved reuse and duplicate-place reuse prompt, clear/change and semantic modes are supported.
- Locations & Map now provides grouped nearby pins, synchronized activity list, category/search/day/week filters, actual timestamps versus untimed definitions, weekly location overrides, and navigation into owning editors. Overnight events remain visible on intersecting days. Optional Home uses the shared picker, persists locally, centers the map and has Return to Home; start/end-at-home are independent opt-ins. Default map region is configurable.
- Required venues constrain physical position. Preferred venues can yield to another known feasible location. Remote sessions retain physical continuity; unknown locations remain explicitly unverified and cannot erase travel between known venues. Occurrence and weekly overrides reach the optimizer. Original policy and resolved physical location stay separate. Locked/started/completed history is protected.
- CP-SAT enforces sequence-dependent walking duration plus buffer, materializes travel intervals, and excludes them from productive minutes. Home trips occur only when explicitly enabled. Existing default_location_id remains stored but does not silently fill unknown venues or imply daily home trips.
- Geocoding and routing retain configurable providers, timeouts/rate limits/cache/attribution and labeled fallbacks. MC/RCH aliases use at most one alternate official-name query after an empty initial result. No guessed coordinates, paid key, or automatic per-keystroke public geocoding. SQLite route-cache connections now close explicitly on Windows.
- Additive migration 0006_universal_locations adds nullable occurrence override metadata. Backup data/backups/pre-universal-locations-20261111.sqlite preserved. Staged and live audits found all original columns/payloads identical, including the saved location, settings, projects, six activities, thirteen occurrences and saved plan. SQLite integrity/FKs passed; no QA/demo data entered personal data.

Actually executed:
- Full backend: 350 tests passed. After the final cache-connection cleanup, all 35 geospatial regressions and the lead integration scenario passed again. Backend and verification-script Ruff clean. One existing Starlette/AnyIO deprecation warning remains.
- Frontend: 92 unit tests passed; typecheck/lint/build passed. Lint/build passed again after marker accessibility fixes. Existing Vite bundle-size warning remains.
- Complete Edge Playwright: 17 workflows passed in 6.2 minutes, preserving all 14 earlier calendar/project/task/recurrence workflows and adding three location workflows. A subsequent test-only visual/footer rerun passed with 32 screenshots and 32 clean axe/overflow audits across four themes and desktop/mobile sizes. Independent API review: 6 passed. Browser tiles/providers were stubbed; actual map screenshots show the intentionally blank test basemap.
- Live public service check: MC Waterloo and RCH each returned a candidate; pedestrian routing between their confirmed public coordinates returned 421 metres/6 minutes with real path geometry and estimated=false. Evidence test-results/location-live-services.json contains no personal locations.
- Lead isolated API scenario: MATH145 ending10:20 and Reality Labs starting10:20 in another building correctly returns infeasible. Moving the latter to10:35 returns optimal with a visible10:20–10:35 walk (manual6minutes + buffer5, rounded to15). scripts/verify_location_delivery.py completed exit0.
- Windows launcher: exact .cmd startup, migration, health/build smoke, occupied-port fallback, existing-instance reuse and parent-exit cleanup all passed. Final activation at127.0.0.1:8765 passed health, Sunday-normalized overview and byte-for-byte served assets verification (index-DTRBihwB.js/index-ECqhAl2R.css). PowerShell Stop-Process failed during activation; confirmed old launcher was stopped with taskkill, then the normal hidden launcher started successfully.

Browser review found and fixed unnamed Leaflet picker markers; API review found and fixed protected resolved-location tampering. Other review fixes covered category/subtype filtering, unknown/remote labels, overnight day filters, universal-latitude proximity grouping, duplicate reuse, historical dictionary preservation and stale resolved positions on edits. Initial browser harness selectors were updated for the shared picker and explicit Home opt-in; final full run passed.

Limits: walking is the supported travel mode. Unknown attendance locations cannot have verified travel coverage and are labeled accordingly. Preferred alternatives are chosen among known planning venues, not arbitrary nearby businesses. Distinct known IDs reserve at least one five-minute transition even if a manual/callback duration is zero; identical IDs reserve zero. Relative weekly task deadlines and semantic AI interpretation remain outside this implementation. Public services may be unavailable; estimates remain labeled. Browser coverage uses installed Edge/emulated viewports, not every device/engine.

To verify: set two saved venues as Required on consecutive commitments, set a walking override and buffer, then generate a day. An impossible zero-gap transition is rejected; sufficient space produces a separate Walk interval. Set a task to Preferred to allow a feasible alternate venue, or Remote to avoid an unnecessary destination without bypassing the route between physical commitments. Home departure/return can be tested independently in Locations & Map.

Evidence: docs/LOCATIONS_CONTRACT.md; test-results/locations-{data-before,data-after,staged-migration-audit,live-verification,lead-scenario}.json; test-results/location-live-services.json; test-results/location-screenshots/; test-results/launcher/; logs/locations-launch.*.log. The current Playwright HTML report shows the later focused visual rerun; the complete17-test run output was observed directly and recorded here.
# Recurring and Week Specific tasks delivery — 2026-11-11

Implemented in place with four genuine GPT-6.1 Sol specialists: backend/database, frontend/UX, scheduling, and independent QA. Lead reviewed shared interfaces, added scheduling preference effects, integrated fixes, and verified launch/data preservation.

- Three management tabs: Every Week, Week Specific, Task Library. Recurring editor, pause/resume/archive, identity-preserving conversion, independent weekly targets, skips and overrides, and arbitrary-week copy with selection and server preview.
- Recurrence expands lazily in memory; reads create no future rows. Scheduling/progress/exception writes materialize stable weekly identities. Explicit assignment identity wins deduplication. Current/future defaults flow through unoverridden fields while existing logical session targets/credit remain intact; historical materialized metadata is snapshotted.
- Copy reuses definitions, excludes recurring sources, merges without overwrite, reports skips/duplicates, creates no progress or scheduled intervals, and explicitly preserves or shifts absolute dates. DST gaps reject atomically.
- Effective metadata reaches the OR-Tools weekly/daily adapters. Soft targets, bounded diminishing extra work, difficulty placement, projects, split-session credit, preferences and hard constraints remain functional. Preferred weekdays and time of day now influence placement.
- Migration 0005_task_recurrence changes no existing payloads or tables. Consistent backup: data/backups/pre-recurring-tasks-20261111.sqlite. Both staged and live audits preserve all original settings, projects, activities, occurrences, saved schedules and canonical task tables; SQLite integrity/FKs pass. No test/demo records entered personal data.

Executed verification:
- Final lead backend suite: 298 passed; backend Ruff passed. Existing upstream Starlette/AnyIO deprecation warning only.
- Frontend: 85 unit tests passed, typecheck/lint/build passed. Vite reports a bundle over 500 kB.
- Windows launcher: exact .cmd, dependency reuse, migration, health/build smoke, occupied-port fallback, existing-instance reuse and parent cleanup all passed. An earlier concurrent-edit run timed out during an automatic frontend rebuild; the settled-build rerun passed all checks.
- Live app activated at http://127.0.0.1:8765 with build index-CzJ4bhvc.js; health, Sunday-normalized weekly API and personal-data audit passed.
- Final complete Edge Playwright run: 14/14 workflows passed in 4.9 minutes, including existing planner/maps/calendar/projects/task regressions and recurrence/copy/conversion. All 33 new recurrence accessibility and overflow audits passed across four themes, desktop/mobile/tablet and dialogs. Lead visually inspected Light desktop cards plus corrected Dark/Midnight mobile dialogs. The first run exposed a mobile radio-width CSS defect and a test label-selector mismatch; both were corrected before the complete passing rerun. Frontend lint and build passed again after the CSS fix.

Limits: descriptions have no semantic AI interpreter; weekly capacity is a forecast around a daily optimizer, not a globally optimal seven-day timetable. Relative weekly deadlines are not implemented. Browser tests use installed Edge with emulated viewports and offline/stubbed map providers; live public routing was not reverified.

Evidence: test-results/recurrence-data-before.json, recurrence-data-after.json, recurrence-staged-migration-audit.json, recurrence-live-week.json, launcher/, playwright-report/, recurrence-screenshots/ and logs/recurrence-launch.*.log.
# Latest delivery â€” Intelligent Tasks & Deadlines (2026-11-11)

The original redesign is implemented, integrated, tested and active at **http://127.0.0.1:8765**. The existing Windows double-click launcher remains operational. Genuine frontend/UX, backend/database, scheduling and independent QA agents contributed; the lead audited the interrupted work, completed integration fixes and personally ran final verification. No repository reset/revert, discarded implementation or user-data replacement occurred. This directory is not a Git repository; agents worked in the shared workspace, with explicit file handoffs.

## Completed behavior

- Tasks & Deadlines now has Sundayâ€“Saturday navigation, arbitrary date selection, This Week, separate weekly assignments, reusable library definitions, search/type/project/status filters, sorting, weekly workload and session summaries. The same definition can be assigned to multiple weeks with independent targets and progress. Selecting another date in the same week retains loaded data. Overview uses the planning date's actual week, independently of the Tasks page's selected week.
- The new editor includes all six task types; exact positive whole-minute session durations without an arbitrary cap; optional project; soft minimum sessions; 0.5-step importance/difficulty sliders; splitting/minimum chunks; description; conditional academic subtype; independent due/assessment timestamps; optional general deadline; and expandable status/location/start/dependency/preference options. Unchanged date inputs preserve their original instants through DST. Unassigned definitions consume no calendar time.
- Canonical definitions, FK-linked weekly assignments, logical sessions and persisted chunks share one planning/accounting service. Split chunks count once toward their parent session. The ledger separates imported/manually reported baseline credit from chunk credit, supporting idempotent saves and exact completion undo. Actual session snapshots retain their original lengths when later sessions change duration; workload summaries combine those snapshots with missing future sessions correctly.
- OR-Tools daily generation uses the selected day's complete weekly context: future calendar capacity, scheduled/completed sessions, cutoffs, dependencies, project status and remaining work. Finite weighted shortfall penalties make minimums soft; valuable extras have diminishing marginal values. Low-value zero-target work does not produce filler. Difficulty affects placement/distribution, not intrinsic value or fabricated duration. Five-minute starts and exact whole-minute work lengths coexist with existing travel, recovery, locks and scheduling modes. Infeasible/partial/timeout states and expected weekly shortfalls are reported.
- Reaching a minimum does **not** close its assignment. A separate `target_met` flag describes goal progress; explicit Completed/Paused controls eligibility. Tests prove meaningful sessions can still be scheduled after the minimum has already been completed and that increasing a met target remains eligible. Explicitly closing a week never invents completion credit.
- Unskipped pending chunks continue to reserve their session's minutes, including past plans. Mark a genuinely missed chunk **Skipped** before replanning those minutes; the app does not guess whether unreported work happened. This prevents 20 past pending minutes plus 60 new minutes from being reserved against one 60-minute session. Named exclusions identify paused/archived project tasks and their reasons.
- Alembic `0004_weekly_tasks` preserves original task/project links, all original table rows and saved plan payloads, with immutable legacy snapshots. Existing finite work is represented conservatively in the current week without invented future recurrences or extra work. Newly written older `/api/tasks` client records retain explicitly labeled finite compatibility behavior until assigned to a week; they are never submitted alongside duplicate weekly work. New UI work uses the canonical weekly APIs. See [TASKS_CONTRACT.md](TASKS_CONTRACT.md) for the data contract and exact objective terms.

## Recovery and agent handoffs

The core frontend, canonical backend/migration and scheduling adapter were already implemented when the accidental interruptions occurred. Their code and test contributions were retained. Recovery checked active processes, saved reports and source contents rather than assuming canceled commands succeeded. The canceled lead integration command had no saved initial result; it was rerun. An interrupted scheduler patch had not landed and was applied after inspection. No orphaned canceled test process remained; intentionally running QA servers were coordinated separately.

Recovery completed the pending-reservation fix, mixed-duration summaries, named exclusions, future-week Overview context, same-week picker fix, and the distinction between target satisfaction and explicit week completion. Independent integration and browser checks exposed and verified these issues. The test harness was also adapted to soft targets, explicit week assignment, independent logical sessions, UTC-equivalent timestamp comparisons, empty-state duplicate actions and isolated weekly fixtures. A former date-independent compatibility fixture was replaced with explicit weekly fixture records so it could not compete with unrelated future-week tests. Cancellation was not recorded as a test failure or pass. Genuine assertion failures were investigated and rerun.

## Actually executed on final code/build

- **267 backend pytest tests passed**, exit 0, in **14.74 seconds**. Includes the original API/project/calendar/map regressions, 112 scheduler/calendar/weekly scheduling cases, weekly API/migration/ledger tests and two independent met-target status regressions. Covered fewer/more than minimum, no filler, future capacity/pacing, independent weeks, exact 1/7/137-minute work, huge safe-integer inputs with bounded candidate materialization, soft/hard dates, project eligibility, dependencies, preserved work, migration/restart persistence, min reductions, explicit completion without fabrication, mixed-duration snapshots, chunk credit/undo, ID-forgery rejection and deletion safeguards. Ruff passed for `backend` and the new production verification scripts. The existing Starlette/AnyIO test-client deprecation warning remains.
- **81 frontend Vitest tests passed**, exit 0, across four files. Strict TypeScript and ESLint passed. The final production build passed: `index-xy5jL6cP.js` and `index-DOHp4ftI.css`. Vite issued a nonfatal bundle-size advisory; the JavaScript bundle is about 501 kB uncompressed / 147 kB gzip.
- **All ten Microsoft Edge Playwright workflows passed**, exit 0, in **2.1 minutes** on the final build: full workspace/maps/planner/export regression; comprehensive calendar drag/move/resize/manual/copy; repeated-hour assessment editing; Sunday/copy boundaries; narrow-view palette/keyboard use; project lifecycle; all-theme project UI; reusable weekly task/year-navigation/persistence; actual planner split completion/undo; and all-theme weekly task UI.
- **86 combined axe WCAG AA and overflow audits passed**: 12 workspace/planner, 10 calendar, 34 projects and 30 tasks. Task coverage includes all four themes at desktop/mobile, reusable library, forms, expanded advanced options, assignment dialogs and tablet targets. No unexpected browser page exceptions were reported. The lead inspected Light desktop weekly cards, Dark task editor, Midnight mobile weekly cards and Warm advanced mobile viewport captures.
- The recovered **lead cross-day integration scenario passed** against an isolated SQLite database: 20 completed minutes plus 40 on another day form one session; repeated completion saves are idempotent; undo restores exact credit; decreasing the target preserves actual session IDs; another week has independent progress. Evidence: `test-results/lead-weekly-integration.json` and its preserved per-run databases.
- **Windows launcher integration passed** with isolated databases: exact `.cmd` startup, dependency reuse, migration, health/compiled frontend smoke, occupied-port fallback (9175 to 9176), existing-instance reuse and cleanup after launcher-parent termination. Final activation verified the existing project's launcher/port before stopping its old parent and starting the tested build with `-NoBrowser`. No unrelated process was stopped.
- A consistent personal backup is retained at `data/backups/pre-weekly-tasks-20261111.sqlite`. Fresh staged upgrades and the final live read-only audit passed. Every original row/fingerprint is unchanged: settings, both personal projects, all six calendar definitions, all 13 placements, task/project source tables and the saved schedule. The personal database had no task rows, so nonempty legacy task/project migration was additionally tested in isolated synthetic databases. SQLite integrity and FK checks passed. No demo or QA data was inserted into personal data.
- **Live verification passed** for health, `0004_weekly_tasks`, canonical definition API/state agreement, Sunday normalization, the Dec 27, 2026â€“Jan 2, 2027 year boundary, calendar compatibility, and exact served HTML/JS/CSS bytes matching the tested build. Launcher startup output is in `logs/weekly-tasks-launch.*.log`.

Evidence: `test-results/playwright-report/`, `test-results/browser/.last-run.json`, `test-results/task-screenshots/`, `test-results/project-screenshots/`, `test-results/calendar-screenshots/`, `test-results/tasks-{data-before,data-after,staged-migration-audit,live-verification}.json`, `test-results/lead-weekly-integration.json`, `test-results/launcher/`, and `test-results/e2e-server.log`.

## Remaining limits

Weekly capacity is an explicitly labeled forecast, not a globally optimal seven-day timetable; the daily solver independently validates actual placements, routes and hard constraints. Existing same-day availability limits remain. Large optimization problems can still reach the configured solver time limit and are reported honestly. Descriptions are persisted context without semantic AI interpretation. Browser verification used installed Edge/emulated viewports, not every engine or physical touch device; automated maps used offline/stubbed public providers. No known blocking defect remained in the completed verification.

# Earlier delivery â€” Personal Projects redesign (2026-11-10)

Implemented with genuine frontend/UX, backend/database, scheduling and independent QA subagents. The lead coordinated the shared contract, reviewed implementation, completed final integration fixes and ran final verification. The verified app is active at **http://127.0.0.1:8765** through the existing Windows launcher.

## Delivered behavior

- Personal Projects now stores long-term contextual containers separately from work tasks. Its compact editor includes name, multiple affiliations, optional dates, contributors, importance (1â€“10) and difficulty (0â€“10) with precise 0.5-step keyboard sliders, description, status, category, goals and HTTP(S) links. Duration/session/availability controls remain in Tasks & Deadlines.
- Searchable/filterable/sortable cards show status, category, affiliation, ratings and linked-task completion. Details expose context, links and actual tasks; users can navigate both ways and create linked work. Projects with no tasks show no fictitious completion percentage and consume no planner time.
- Tasks optionally reference projects through database foreign keys. Editing with an older client that omits `project_id` preserves the link; explicit null unlinks it. Deleting a linked project requires explicit **Delete project & keep tasks** confirmation and retains all tasks. Deleted-project filters clear immediately.
- The scheduler receives complete project context. Importance adds `round((importance - 1) * 10)` per-minute objective points (0â€“90), alongside task priority and urgency in all three modes. Paused/archived projects exclude new automatic work by default, with explicit one-generation opt-in and reported reasons. Locked/started work and preserved prerequisite sessions remain protected. Difficulty never invents durations; project dates never replace task deadlines; affiliations/contributors do not imply other people's availability. No semantic AI interpretation was added.
- Project/context changes invalidate saved plans for regeneration while preserving their blocks. The planner explains stale context and excluded work. Legacy work-task kinds remain compatible.
- Alembic `0003_personal_projects` creates contextual projects and FK task associations. Every legacy project work record keeps its original task ID, complete work data, dependencies and saved schedule references; the migration adds its container and link, retaining an immutable original snapshot. No task or work estimate is fabricated. Legacy importance maps from priority Ã— 2, clamped to 1â€“10; dates stay unset rather than becoming inferred deadlines. See [PROJECTS_CONTRACT.md](PROJECTS_CONTRACT.md).

## Actually executed on final code/build

- **194 backend pytest tests passed**, exit 0, in 11.26 seconds. Includes 40 project API/migration tests plus scheduling and existing API/calendar/map regressions. Coverage includes CRUD/all metadata, strict counts/ratings/half steps/dates/URLs, missing/empty project references, link/unlink/delete retention and FK enforcement, old-client compatibility, restart persistence, repeat migration and lossless legacy snapshots, no-task containers, all scheduling modes, importance/urgency/hard constraints, exclusions/opt-in, preserved work/dependencies, and stale-plan regeneration. Ruff passed for `backend` and the new verification scripts. The existing Starlette/AnyIO test-client deprecation warning remains.
- **56 frontend Vitest tests passed**. Strict TypeScript, ESLint and Vite production build passed. The 20 new project utility cases cover rating/count/date/link validation, API limits, migration provenance exclusion and meaningful task completion progress.
- **All seven Microsoft Edge Playwright workflows passed**, exit 0, in 1.5 minutes on the production build: the whole-app workflow; comprehensive calendar drag/move/resize/manual/copy/themes; repeated-DST-hour assessment edits; Sunday-week preservation/copy boundaries; many-block narrow-screen/calendar keyboard use; complete contextual-project/task lifecycle; and all-theme project accessibility/responsiveness.
- **56 combined axe WCAG AA and overflow audits passed**: 12 existing workspace/planner checks, 10 calendar checks, and 34 new project checks across Light/Dark/Midnight/Warm desktop/mobile, collapsed/expanded forms, detail dialogs, linked tasks and Warm tablet. No unexpected page exceptions were reported. The lead visually inspected Light desktop project cards, Dark desktop form, Midnight mobile cards and Warm mobile details, including a viewport-only modal capture.
- **Windows launcher integration passed** with isolated databases on ports 9175/9176: exact `.cmd` startup, installed dependency reuse, migration, health and compiled frontend smoke, occupied-port fallback, existing-instance reuse and cleanup after launcher-parent termination. The root launcher and normal `127.0.0.1:8765` workflow remain intact.
- Before activation, the real migration passed against a SQLite copy of the personal database. A consistent backup is retained at `data/backups/pre-project-redesign-20261110.sqlite`. After actual launcher startup/migration, the read-only audit found identical settings, all six calendar definitions, all 13 placements and the saved schedule payload. The personal database had no task records, so nonempty legacy work migration was verified in isolated synthetic databases. Foreign-key and SQLite integrity checks passed; no demo or QA records were added to personal data.
- Live verification passed for health, project API/state agreement, migration revision, existing Sunday calendar boundaries, and byte-for-byte equality of served HTML/JavaScript/CSS with the tested build (`index-fQtLLDQZ.js`, `index-PQao69tQ.css`). The production launcher is running; startup logs are `logs/projects-launch.*.log`.

The first combined browser run passed five workflows and surfaced two test-harness issues: a real-date workspace placement collided with a fixed calendar fixture, and exact wrapping-label selectors failed for native selects. The harness now cleans only its own QA placement and selects the project comboboxes by accessible role/name. The complete seven-workflow rerun passed without production changes. Independent QA also found the empty project-ID API edge; it was fixed and included in the final 194-test backend run.

Evidence: `test-results/playwright-report/`, `test-results/browser/.last-run.json`, `test-results/project-screenshots/` (including viewport-only mobile dialogs), `test-results/projects-{data-before,data-after,staged-migration-audit,live-verification}.json`, `test-results/launcher/`, and `test-results/e2e-server.log`.

Limits: browser verification uses installed Edge and emulated viewport sizes, not every browser engine or physical touch device. Automated mapping used offline/stubbed providers; live public routing services were not reverified. Descriptions/goals are persisted context with no AI interpretation mechanism. Existing same-day availability limits remain.

# Earlier delivery â€” Calendar palette and Sunday weeks (2026-11-09)

Implemented with genuine frontend/UX, backend calendar and independent QA subagents; the lead reviewed contracts, integration, screenshots, launcher behavior and data preservation.

- A compact searchable, horizontally scrolling palette now sits immediately above the calendar's independently scrolling time grid. Icons and category colors follow all four themes. Its class/commitment items reference existing saved definitions, update with CRUD, support repeated placements and offer manual Schedule buttons. Assessments are excluded; no separate definition store or scheduling state was introduced.
- Drag previews show five-minute positions and flag conflicts/date restrictions. Invalid drops are rejected, and previews clear when leaving the calendar. Empty time grids now support keyboard focus and native arrow-key scrolling with a visible focus ring.
- Calendar columns, dashboard queries, manual dates, Previous/Next/This Week and Copy Previous Week consistently use Sundayâ€“Saturday. Backend week endpoints normalize input dates to the containing Sunday. November 8â€“14, 2026 is explicitly covered. Persisted occurrence instants, assessment dates and legacy recurrence weekday numbering are unchanged; no migration was added.

Actually executed on the production build:

- **124 backend pytest tests passed**; Ruff passed. Includes original scheduler/API/travel tests plus Sunday/Saturday/year boundaries, Toronto midnight filtering, DST copying, eligible copies/idempotence, assessment exclusion and exact saved-instant preservation. The existing Starlette/AnyIO test-client deprecation warning remains.
- **36 frontend Vitest tests passed**; strict TypeScript, ESLint and Vite production build passed. TypeScript/build and ESLint were rerun after the keyboard-focus fix.
- **Five combined Microsoft Edge Playwright workflows passed, exit 0, in 1.3 minutes**: whole-app regression; comprehensive calendar/palette flow; repeated-DST-hour assessment edit; exact November 8â€“14 grouping/navigation/copy/preservation; and many-block responsive/manual scheduling. The calendar workflow genuinely dragged MATH147 to Wednesday 10:30 and Friday 14:05 from the adjacent palette with unchanged outer page scroll, refreshed and verified both placements linked to the same definition, then moved/resized events and checked conflicts, date limits, metadata CRUD, assessment locking and optimizer integration.
- **22 combined axe WCAG AA/overflow audits passed**, covering Light/Dark/Midnight/Warm at desktop/mobile, tablet and the mobile manual dialog. The lead inspected adjacent-drop, many-block desktop/mobile, Dark desktop, Midnight mobile and Warm tablet screenshots. No unexpected browser page exceptions were reported.
- A strengthened **focused empty-grid browser check passed separately (exit 0, 8 seconds)** after the combined run: navigate to a week with zero events, use native ArrowDown to scroll, retain/search 18 reusable palette items and open the accessible mobile manual dialog. Production code/build did not change between runs. The generic Playwright report now contains this latest focused run; a copy is at `test-results/calendar-ux-empty-grid-report/`.
- **Windows launcher integration passed**: exact `.cmd` startup, safe migration/dependency reuse, compiled frontend health, occupied-port fallback, existing-instance reuse and cleanup after launcher-parent termination. Isolated launcher checks used ports 9175/9176. The production port/default launcher remain `127.0.0.1:8765` and `Launch Schedule Builder.cmd`.
- The personal database was backed up consistently through SQLite's backup API to `data/backups/pre-calendar-ux-20261109.sqlite`. A read-only before/after audit found identical counts and SHA-256 fingerprints for entities, settings, activities, occurrences, saved plans and migration version. All new test records stayed in isolated QA databases.
- **Activated and verified at `http://127.0.0.1:8765`**: the previous verified launcher was restarted, the containing-week request returns November 8â€“14, and the live HTML/JavaScript/CSS match the tested production files byte-for-byte. The personal-data fingerprint audit still matches after restart. The one-off activation helper initially misdecoded local UTF-8 HTML using Windows PowerShell's default encoding and falsely reported verification failure; explicit UTF-8 and a separate byte comparison passed. No product fix was needed. Durable live-check evidence is `test-results/calendar-ux-live-verification.json`; launcher logs are `logs/calendar-ux-launch.*.log`.

Evidence: `test-results/calendar-screenshots/`, `test-results/playwright-report/`, `test-results/browser/.last-run.json`, `test-results/e2e-server.log`, and `test-results/calendar-ux-data-{before,after}.json`. Browser coverage uses installed Edge, not every browser engine or physical touch hardware. Manual scheduling remains the mobile/keyboard alternative. Automated public map traffic was stubbed/offline; this change does not reverify live routing providers.

# Earlier delivery â€” Classes, Commitments & Assessments

The activity-library and weekly-calendar redesign is implemented and the personal database has been upgraded to `0002_activity_calendar` with its original records and saved blocks preserved. The app is running on `127.0.0.1:8765`. Current backend verification: 111 pytest tests and Ruff passed. Current frontend verification: 34 Vitest tests, strict TypeScript, ESLint and production build passed. The final combined real Edge run exited 0 with three workflows passed, including actual drag/drop, movement, resizing, a held-pointer notification-expiry regression, manual entry, copy-week, assessment/DST edits and the existing application regression. All 21 combined accessibility/overflow audits passed.

See [CALENDAR_REDESIGN.md](CALENDAR_REDESIGN.md) for architecture, data audit, Windows startup checks and limitations, and [CALENDAR_QA.md](CALENDAR_QA.md) for the final combined browser-run evidence. The earlier initial-app delivery record follows for history.

# Initial delivery verification â€” 2026-11-09

The directory was empty when this implementation began. Six genuine specialist subagents contributed scheduling, backend, frontend/UX, maps review, independent QA, and Windows integration work. The lead integrated contracts, routing, launcher, documentation and cross-layer fixes.

## Implemented

- Persisted classes/recurrence/exceptions, academic tasks/deadlines/prerequisites, personal projects, locations and preferences in SQLite with Alembic.
- Real deterministic OR-Tools CP-SAT optimization with exact activity sequencing and travel constraints, fixed/locked/started work, sleep/availability, meals/breaks, minimum/maximum study sessions, hard deadlines, dependencies, urgency/mode/energy preferences, explicit unmet work and solver status. Constructive hints improve incumbent quality; the solver validates all hard constraints.
- Responsive React dashboard, chronological planner/inspector, validated manual edits and drag-to-gap, locking, progress, reoptimization, ICS/CSV, explicit additive demo, and Light/Dark/Midnight/Warm themes.
- Leaflet map selection/dragging, saved markers/coordinates, user-submitted place searches, pedestrian routes, directional manual overrides, persistent cache, rate limiting, configurable providers, labeled fallback estimates and attribution.
- Root Windows `.cmd` launcher, project-local dependency setup, locked packages, safe migrations, compiled frontend served by one local FastAPI server, health checks, port fallback, logs, browser opening and parent-exit server cleanup.

## Actually executed

- Backend: **63 pytest tests passed**, including scheduler, API, migrations/restart persistence and travel/provider scenarios. One upstream Starlette/AnyIO deprecation warning remains in the test client; tests pass.
- Backend/scripts: Ruff passed; `pip check` found no broken dependencies.
- Frontend: strict TypeScript, ESLint, production build and **19 Vitest tests passed**.
- Real Edge Playwright workflow passed with a clean **exit 0** in 42.4 seconds (one comprehensive workflow). It exercises CRUD, map selection/overrides, settings, generation/travel/deadlines, locks/regeneration, completion accounting, rejected overlap, a valid timezone-aware edit, reload persistence, ICS download and CSV/ICS exports. The isolated QA server stops automatically via a token-guarded QA-only shutdown route; production routes are unaffected. See `docs/QA.md` for details.
- Four-theme visual review: **14 axe/overflow checks passed** for desktop overview/planner, 390-pixel mobile, 768-pixel tablet and a dialog. Zero reported WCAG AA violations, horizontal overflow or JavaScript page errors. Final screenshots use disabled animations for stable navigation state. The lead inspected actual screenshots and verified the larger mobile metadata. A separate final console review across all seven navigation screens reported no errors.
- Windows: actual `.cmd` startup/health/frontend smoke passed; occupied-port fallback, running-instance reuse and cleanup after launcher-parent termination passed. Separate actual launch from a project path containing spaces passed. Safe native-warning/exit-code handling was exercised. Normal launcher opened the app's Edge window at `127.0.0.1:8765`.
- Live public mapping: Waterloo geocoding succeeded; Davis Centre to Dana Porter pedestrian route returned **8 minutes / 523 metres**, labeled routed. Automated browser tests stub public tile downloads and use offline routing to avoid automated tile-service traffic; this does not establish every place/provider/route will be reachable.

## Review fixes verified

Stale generated class/meal times after source edits; unspecified-location travel bypass; dangling saved task/location-override references; task-level completion vs planner consistency; native PowerShell stderr handling; timezone-naive manual edits; mixed-offset chronological sorting; multi-exception keyboard input; malformed provider responses; cached/manual route provenance; and mobile typography were addressed during integration. Regression coverage was added for the material scheduling/API/map issues.

## Limits and scope

Availability currently uses same-day waking/working windows, not overnight shifts. Dates/deadlines and DST boundaries are supported. No natural-language parser, AI key, paid model or trained personalization model is part of the core app. Walking fallbacks are conservative distance heuristics, not verified physical routes; manual overrides are available. Mixed physical/unassigned activities require a default location to prevent teleporting. Public geocoding/routing/tiles require Internet and remain subject to their provider policies.

The native Computer Use tool stopped before visual inspection because it could not confidently identify the browser URL; it was not used further. Browser verification instead used the explicitly requested Playwright tests and actual captured screenshots. This is a single-user localhost application.

Test data is isolated under temporary directories and `test-results/`; no demo records were loaded into the personal `data/schedule_builder.db`. Launch by double-clicking `Launch Schedule Builder.cmd`. See README for settings, backups and verification commands.




