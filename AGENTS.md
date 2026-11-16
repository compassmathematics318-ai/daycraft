# Schedule Builder engineering guide

## Architecture
FastAPI serves a compiled React/TypeScript/Vite frontend and a local SQLite database managed by SQLAlchemy/Alembic. OR-Tools CP-SAT optimizes five-minute intervals; the server validates manual edits. All dates use IANA timezone America/Toronto by default. Core features require no AI key.

## Ownership and roles
- Scheduling Engineer: `backend/app/scheduler.py`, `backend/tests/test_scheduler.py`. Pure `generate_schedule(date, settings, classes, tasks, blocks, route_minutes, mode, now=None)` returns schedule dictionary. Travel callback accepts origin/destination IDs. Explicit unmet work and solver status required.
- Backend Engineer: `backend/` except scheduler files. API, schemas, persistence, migrations, exports and backend tests. Integrates scheduler contract.
- Frontend/UX Engineer: `frontend/`. Accessible responsive UI, four themes, map interaction and API integration.
- Maps Engineer: `backend/app/travel.py` and focused map tests; provider policies, cache/override provenance, walking routes and labeled fallbacks. Coordinate API integration with the lead.
- Integration/DevOps Engineer: root launcher/scripts, project dependencies, Windows startup and cleanup verification. Coordinate script mutations with the lead.
- Lead: shared contracts, cross-layer integration, documentation, review fixes and final verification.
- QA/Review Engineer: assigned after a parallel slot is available; reviews integration and owns `e2e/` tests and fixes agreed with owners.

Do not overwrite other owners' files. Communicate interface changes before implementing. Preserve real user data. Demo insertion is explicit and additive.

## Shared API contract
See `docs/CONTRACT.md`. Unknown fields must not silently corrupt stored data. Bind only to localhost. Public map calls must use timeouts, rate limits, caching and attribution; routing fallback must be labeled estimated.

The activity library/calendar extension is specified in `docs/CALENDAR_CONTRACT.md`. `activities` stores reusable metadata, `occurrences` references activities through a database foreign key, and retained legacy class records supply explicit recurrence. Calendar reads, copying and CP-SAT use the same occurrence source. Never treat an unplaced definition as occupied time. Do not erase legacy records or convert new definitions into endless recurrence. Calendar edits must invalidate affected daily plans until regenerated.

## Verification
` .venv\Scripts\python.exe -m pytest backend/tests -q`
` .venv\Scripts\python.exe -m ruff check backend`
` npm --prefix frontend run typecheck`
` npm --prefix frontend run lint`
` npm --prefix frontend test -- --run`
` npm --prefix frontend run build`
` npm --prefix e2e test`
` powershell -NoProfile -ExecutionPolicy Bypass -File scripts\launch.ps1 -NoBrowser`

Record actually executed results and limitations in `docs/PROGRESS.md`. Never describe authored tests as passing without running them.
