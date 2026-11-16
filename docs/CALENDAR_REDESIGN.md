# Classes, Commitments & Assessments — delivered redesign

## Behavior

The renamed page combines a reusable Block Library with one Sunday–Saturday weekly calendar. Classes (Lecture/Tutorial/Lab), commitments (Personal/Groupwork), and one-time assessments retain descriptions, locations and contextual fields. Creating a class or commitment does not reserve any time. Assessments require absolute start/end times and have one authoritative calendar occurrence.

The calendar-adjacent Block Palette references those same saved classes and commitments, with category icons/colors, searchable horizontally scrolling items and manual Schedule buttons. It stays immediately above the independently scrolling time grid, so placing multiple meetings does not require returning to the library. Assessments are excluded. Definitions edited in the library update the palette directly. See the latest entry in [PROGRESS.md](PROGRESS.md) for verification of this follow-up.

Class and commitment cards support multiple placements through Schedule or real drag/drop. First drops reserve 60 minutes. Existing meetings can be moved, resized, edited or deleted independently of their definition; placement input uses five-minute precision and rejects overlaps and invalid date limits. The scrollable time grid covers the full day. Narrow screens use contained horizontal scrolling to keep all seven day columns usable, with manual Schedule controls as a touch/keyboard alternative.

Copy Previous Week preserves local times and durations, linked metadata and existing target events. It skips assessments, conflicts, out-of-range dates and nonexistent DST times, and reports partial results. Repeated copying does not duplicate occurrences. A DST shift that prevents preserving both the original wall times and elapsed duration is reported as a skip rather than silently changing it.

## Data and integration

Alembic revision `0002_activity_calendar` adds activity definitions and dated occurrences with foreign-key linkage and cascade deletion. Original legacy class records remain intact. The library mirrors their metadata; explicit legacy recurrence expands into the same occurrence stream used by the calendar and optimizer. Editing/deleting a single legacy meeting records an exception and, for edits, a dated replacement. Edit repeat retains control of the original series. New blocks do not create automatic endless recurrence.

Actual occurrences become fixed CP-SAT commitments with correct dates, locations and metadata. Travel, meals, task/project allocation, deadlines and progress accounting continue through the existing engine. Unplaced definitions consume no time. Calendar changes mark affected saved plans stale and prevent edits from bypassing changed fixed commitments until regeneration. Completed and started planner snapshots are preserved.

Typed descriptions, categories, subtypes, course associations and upcoming assessment context are available through the APIs and optimizer input/output. No AI model interprets descriptions or automatically invents preparation tasks; preparation remains an explicitly managed task with its own duration and deadline.

## Verification actually executed

- **111 backend tests passed**, including migration preservation, all three CRUD types, atomic conflict rejection, date/precision/DST validation, copy semantics, restart persistence, legacy exceptions, stable completed history, fixed-calendar optimization, travel and the existing application tests. Ruff passed.
- **34 frontend tests passed**, including explicit ambiguous-DST preservation, changed wall-time conversion and nonexistent-time rejection. Strict TypeScript, ESLint and production build passed. Final assets are `index-BUxa6qTN.js` and `index-BdXJ6ygC.css` and were verified served by the live localhost application.
- A focused real Edge Playwright calendar workflow passed with genuine mouse library drop at 14:05, event move to 15:10, and pointer resize ending at 16:25. Manual and dragged placements share the same persisted shape. The workflow also exercised assessment edits, deletion of individual placements, partial/idempotent copying, refresh persistence and optimizer metadata.
- The final combined `npm --prefix e2e test` completed with **exit 0: three workflows passed in 2.1 minutes** on the final assets. It covers the existing full application, the complete calendar workflow with all three categories edited/deleted, and an actual second-fold assessment metadata edit. A deterministic 7.5-second held-pointer regression verifies that notification expiry does not shift the calendar or change a resize result; success messages now use fixed toasts.
- Four themes at desktop/mobile plus tablet produced **nine passing calendar axe/overflow checks**. The lead inspected actual Light/Dark desktop, Midnight mobile and Warm tablet screenshots. The existing full application browser regression also passed. See [CALENDAR_QA.md](CALENDAR_QA.md) for final combined-run results and exact coverage.
- The final combined suite produced **21 passing accessibility/overflow audits**, with no unexpected page exceptions.
- Windows `.cmd` startup/health/frontend smoke, occupied-port fallback, running-instance reuse, and cleanup after launcher-parent termination all passed with the new migration. Launcher tests use ports 9175 onward to avoid the browser-test server on 8876.
- The migration first passed on a clone of the actual database backup. The live database was then backed up again to `data/backups/pre-calendar-live-20261109-024211.sqlite`, migrated, and audited read-only. All original entities, settings and saved planner blocks matched the backup; the existing class now has a linked library definition and dated weekly occurrence. Foreign-key checks reported no violations.

## Launch and limits

The upgraded app runs at `http://127.0.0.1:8765`. For normal startup, double-click `Launch Schedule Builder.cmd`. The existing one-server deployment is unchanged.

Browser checks use installed Microsoft Edge; physical touch devices and other browser engines were not separately tested. Native HTML drag/drop support varies on touch browsers, so Schedule/manual editing remains available. Existing same-day planner availability and public routing-provider/fallback limits remain unchanged. Test/demo records stayed in isolated databases under `test-results/`; no demo data was inserted into the personal database.
