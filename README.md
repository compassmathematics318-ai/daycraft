# Daycraft — Schedule Builder

A local daily planner with React, FastAPI, SQLite persistence, and an actual OR-Tools CP-SAT optimization engine. No model API key or paid service is required.

## Getting started from a GitHub clone

Clone or download this repository to a **writable local folder** on Windows. The root directory must contain `Launch Schedule Builder.cmd`, `backend/`, `frontend/`, and `scripts/` together. Then follow **Launch on Windows** below. The first launch installs dependencies and builds the interface; preinstalled packages and compiled files are intentionally not committed.

For an existing local Daycraft installation, do **not** replace the working folder or delete its `data/` directory just to adopt this repository. Your schedules and locations are stored locally and **are not included in the GitHub source ZIP**. Use the [backup instructions](docs/BACKUP.md) to preserve and migrate your workspace data separately.

To publish a fresh repository from this source tree, follow [GITHUB_PUBLISH.md](GITHUB_PUBLISH.md). No license is included: publishing source code on GitHub does not by itself grant others permission to reuse it. Choose a license separately if you want one.

## Launch on Windows

Double-click **`Launch Schedule Builder.cmd`** in this folder. The first run needs Python 3.11+ and Node.js 22.12+ (Node 24 LTS also works), and Internet access to download project dependencies. It creates `.venv`, installs locked Python dependencies, builds the frontend if needed, safely applies Alembic migrations, starts one local server, waits for health, and opens your default browser. Later launches reuse installed dependencies and compiled assets.

The normal address is **http://127.0.0.1:8765**. If another program occupies the port, the launcher tries the next nine ports and prints the address. It reuses a managed instance only when its workspace and database match; an older unmanaged Daycraft server must be stopped through its original launcher first. Keep the launcher window open while using the app; Ctrl+C or closing the window stops its server. Setup and server logs are retained in `logs/`. Nothing is installed system-wide and administrator privileges are not required.

To test the launcher without opening a browser:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\launch.ps1 -NoBrowser -SmokeTest
```

## Using your workspace

- Begin with an empty personal workspace or explicitly choose the demo-data action. Demo insertion is additive and repeatable; it never replaces existing records.
- Save locations by clicking/dragging a map marker, entering coordinates, or submitting a place search. Set a default starting location in Settings for departure/return travel.
- When mixing physical and unassigned activity locations, choose a default location in Settings. This prevents unspecified activities or meals from bypassing necessary walks. A completely remote workspace needs no default. Demo data sets a demo starting location only when the workspace is empty.
- Open **Classes, Commitments & Assessments** to create reusable blocks. Classes have Lecture/Tutorial/Lab subtypes; commitments have Personal/Groupwork types. Their optional validity dates, descriptions and locations belong to the definition; meeting times belong to separate calendar placements.
- Place classes and commitments from the compact **Block Palette** immediately above the Sunday–Saturday calendar. Search the palette or scroll its row to find a block, then drag it to a day/time; the same block can have several placements. Palette and library **Schedule** actions provide manual alternatives. New drops start with 60 minutes; move, resize or edit meetings in five-minute steps. Delete a placement to keep its reusable block. Assessments require absolute start/end date-times and appear automatically; explicitly edit the assessment to reschedule it.
- Navigate weeks or return to **This Week**. **Copy Previous Week** copies eligible class/commitment meetings, preserves existing events, skips conflicts and out-of-range dates, avoids duplicates, and excludes one-time assessments. Its summary explains partial copies.
- Existing classes are retained as labeled **Legacy weekly repeats**. **Edit repeat** changes the original weekly rule; moving or deleting an individual meeting adds an exception without changing the other dates. New blocks do not automatically repeat forever.
- **Personal projects** hold long-term context: affiliations, dates, contributors, importance, difficulty, descriptions, goals and links. Search, filter and sort project cards; open a project for linked tasks and completion progress. A project without tasks consumes no calendar time.
- **Tasks & deadlines** organizes explicit assignments by Sunday–Saturday week. Navigate to any week, create a reusable task or assign one from the library, and set a best-effort minimum of full sessions. Definitions hold task type, minutes per session, importance, difficulty, optional project, independent due/assessment dates, description and preferences. Weekly targets and progress remain separate. Split chunks count toward one logical session; only fully completed work counts as a completed session. Existing finite work retains its original estimate and remaining work during migration.
- Paused and archived projects normally exclude their tasks from automatic scheduling. In the daily planner, explicitly choose **Include tasks from paused and archived projects** when needed. Locked and started work remains protected. Deleting a linked project requires explicit unlinking and retains its tasks.
- Choose a day (tomorrow initially), select Balanced, Deadline First, or Deep Work, then generate. Review explicitly unallocated work and fixed-commitment conflicts.
- Select a planner activity to inspect its rationale, edit its time, lock it, or record progress. The server checks feasibility before saving. Locked and started work survives regeneration. Reoptimize schedules remaining work from the current time; use this on today's plan.
- Export a saved schedule as ICS or CSV. Four themes are available: Light, Dark, Midnight and Warm.

## How scheduling works

The optimizer uses optional work intervals and an exact sequence circuit. No-overlap, waking/working bounds, fixed commitments, protected meals, dependencies, hard cutoffs, required recovery and walking time constrain the model. A weighted objective balances importance, urgency, soft weekly shortfalls, bounded project context and placement preferences across the existing scheduling modes. Project dates remain context; difficulty never invents task durations. New work starts use a five-minute grid and sessions retain exact whole-minute durations. Time arithmetic uses UTC elapsed minutes with an IANA display timezone (America/Toronto by default), including DST transitions. See [the weekly task contract](docs/TASKS_CONTRACT.md) for objective weights and [the project contract](docs/PROJECTS_CONTRACT.md) for container metadata and legacy compatibility.

Weekly task assignments add session identities and a weekly lookahead to the daily optimizer. Minimum sessions are soft goals: urgent competing work can justify fewer, while meaningful additional sessions can be placed beyond the target. Future commitments, other days' scheduled/completed work and remaining capacity inform daily pacing. Exact whole-minute session durations are retained; new work starts use the five-minute grid. Expected shortfalls are reported. See [the weekly task contract](docs/TASKS_CONTRACT.md) for model, migration and accounting details.

Partial work is reported explicitly. A solver time limit without any incumbent is reported as a timeout; fixed conflicts are reported as infeasible. A feasible incumbent after the time limit is labeled feasible or partial, with its raw solver status retained. Generation does not invent free time or mark allocations completed. An independent validator checks produced schedules and manual edits.

Calendar occurrences are the authoritative fixed commitments for daily optimization, including assessments, classes, personal commitments and groupwork. Unplaced definitions consume no time. Changing the calendar marks affected saved daily plans for regeneration. Descriptions, categories, course associations and locations are retained as typed context; they do not cause an AI model to infer preparation work. Add preparation as an academic task with its own duration and deadline.

Availability is a same-day waking/working window. Overnight work shifts are not currently configurable; deadlines may cross midnight and retain their actual date/offset. There is no natural-language task parser or trained personalization model. Public map availability and geographic accuracy are not guaranteed. Conservative fallback walking estimates cannot establish real-world accessibility; inspect routes and use manual travel overrides where necessary. This is a single-user local application, not a multi-user hosted service.

## Mapping providers and privacy

Place search deliberately uses the public Nominatim service for this personal planner. **Its [usage policy](https://operations.osmfoundation.org/policies/nominatim/) requires identification, attribution, caching, no autocomplete or bulk searches, and at most one request per second.** Searches happen only on explicit submission; the backend identifies the application, serializes requests at 1.1-second intervals, and caches results for 30 days. Do not submit confidential personal information. Search text and coordinates are sent to the configured provider. You can instead save coordinates without geocoding.

Interactive map tiles use OpenStreetMap attribution and normal browser caching, with no offline downloads or prefetching; see the [tile policy](https://operations.osmfoundation.org/policies/tiles/). The default pedestrian router is the [FOSSGIS routing service](https://routing.openstreetmap.de/). Routes are cached for seven days and remote requests are rate-limited, bounded and timed out. Manual overrides take precedence. When a route is unavailable, the server labels an estimate based on straight-line distance multiplied by 1.4 and your walking speed, plus the configured travel buffer. Route geometry displayed for estimates is a direct line. This heuristic is not an actual walking route.

Copy `.env.example` to `.env` to change provider URLs, port, database/cache paths, or disable online search/routing. The launcher reads simple `KEY=VALUE` entries without executing them. For direct development runs, set these as process environment variables. Frontend map tiles can be changed with `VITE_MAP_TILE_URL` at build time; attribution must match your provider.

## Data and development

Personal data lives in `data/schedule_builder.db`; route/search cache lives in `data/travel_cache.sqlite`. Double-click **`Backup Daycraft.cmd`** to create a verified source-and-data ZIP in `data/backups`, including a consistent SQLite snapshot even while Daycraft is running. It omits virtual environments, `node_modules`, caches and raw database journals. The separate `--full` option includes installed environments and private configuration; see [backup and recovery instructions](docs/BACKUP.md). Existing backups are never overwritten. Do not delete personal data to fix a dependency or build problem. Alembic migrations run before startup and are versioned in `backend/migrations`.

Double-click **`Stop Daycraft.cmd`** for graceful shutdown of launcher-managed Daycraft instances in this workspace. It verifies each instance and never globally kills Python. Closing VS Code or Codex does not necessarily close a separately launched Daycraft window. See [process lifecycle and shutdown](docs/PROCESS_LIFECYCLE.md) for supported launch modes and older unmanaged processes.

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q
.venv\Scripts\python.exe -m ruff check backend scripts/serve.py
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend test -- --run
npm --prefix frontend run build
npm --prefix e2e test
```

For development, run `python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8765` in the venv and `npm --prefix frontend run dev` (Vite proxies `/api` to the backend). Normal use requires only the Windows launcher and one server. See `docs/CONTRACT.md` for the JSON API and `docs/PROGRESS.md` for recorded verification and limitations.

The Classes, Commitments & Assessments redesign, preserving migration and its executed verification are documented in [docs/CALENDAR_REDESIGN.md](docs/CALENDAR_REDESIGN.md) and [docs/CALENDAR_QA.md](docs/CALENDAR_QA.md).
