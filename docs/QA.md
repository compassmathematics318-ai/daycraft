# Independent QA record

QA owns `e2e/`; the application team owns fixes to frontend/backend. Playwright uses installed Microsoft Edge, an isolated timestamped SQLite database and route cache under `test-results/`, and offline routing. Automated map tile requests are fulfilled locally to avoid automated requests or pans against a public tile service. Map click/marker/location workflows still execute the real Leaflet interface. Live mapping provider availability is a separate check.

## Review findings

1. Generated classes/meals were automatically locked and preserved across regeneration, retaining stale source times after edits or deletion. The lead implemented source-aware preservation and backend regressions.
2. A real scheduler reproduction showed a 30-minute unspecified-location task bridging A09:00–10:00 and B10:30–11:00 despite a 60-minute walk, returning `optimal` without conflicts. The lead added explicit default-location validation for mixed physical/unspecified activities and regressions.
3. Deleting unlocked scheduled tasks could leave dangling task IDs in saved plans, preventing later edits. The lead implemented consistent removal of unstarted, unlocked references, preserving protected work.
4. Frontend activity edits submitted naive datetime-local strings, which strict backend validation rejected. The frontend owner added IANA timezone conversion, including DST handling. The final browser workflow successfully moved a project to 20:00 and rejected a class overlap.
5. Class exception-date input removed commas on each keystroke, preventing natural typing of a second exception. The frontend owner retained raw draft input until submit; the final browser test typed and persisted two exception dates.
6. Task quick-completion could leave stale uncompleted schedule blocks that rejected subsequent edits. The lead synchronized statuses. The final browser test completed a task through its card and then successfully saved another planner activity.

## Verification status

**Final execution: `npm --prefix e2e test` exited 0, one comprehensive workflow passed in 42.4 seconds (workflow body 39.0 seconds).** Earlier full workflows also passed, but the standard Playwright Windows webServer teardown hung until manual cleanup. The final harness uses a token-guarded QA-only shutdown endpoint in `e2e/server.py`; startup, testing, shutdown and runner exit now complete automatically. Production application routes are unchanged. Server logs remain in `test-results/e2e-server.log`.

The real browser workflow covers map clicks and coordinate entry; saved locations; route fallback and manual overrides; preferences; class/task/project creation and editing; project deletion; keyboard typing of multiple class exceptions; real optimization and reserved travel; hard-deadline placement; ICS download; locks and regeneration; session completion and regeneration; invalid overlap rejection; successful time editing; page reload persistence; four persistent themes; desktop/mobile/tablet overflow; quick task completion followed by another schedule save; and ICS/CSV output. There were no uncaught JavaScript page errors.

`node e2e/visual-review.mjs` also exited 0 against a fresh demo database and actual optimal schedule. It captured and audited 14 screens: desktop overview, desktop planner and 390px mobile planner for every theme, plus 768px tablet and a task dialog. All 14 axe WCAG AA scans returned zero violations, and all overflow checks passed. The comprehensive workflow independently produced 12 additional passing theme/viewport axe reports. Screenshots disable animations to avoid capturing a navigation transition. The lead and QA visually inspected actual screenshot artifacts.

A separate real-browser console review visited all seven navigation screens and recorded zero console errors and zero page exceptions in `test-results/console-review.json`.

Artifacts: `test-results/screenshots/review-*.png`, `test-results/visual-review.json`, `test-results/accessibility/`, `test-results/playwright-report/`, `test-results/downloads/schedule.ics`.

These checks use installed Microsoft Edge headlessly, not other browser engines or physical touch devices. Public map tiles are replaced locally only in automated QA; these tests do not establish live tile/geocoding/provider availability. Location marker dragging and timetable drag/drop were not separately automated; map selection and validated inspector time edits were exercised. Automated axe scans are bounded checks, not a claim of complete accessibility certification.
