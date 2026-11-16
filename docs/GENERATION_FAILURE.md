# Schedule generation failure: November 13, 2026

## Resolved on November 12, evening (Toronto)

The active Windows runtime now passes the real solver self-test and generates
real schedules with Smart App Control still enabled. Official Pandas 3.0.6 was
validated in isolation and replaces 3.1.1; OR-Tools and its optimization model
are unchanged. The actual November 13 **Medium + Balanced** request succeeds
on copied personal data. All 15 workload/strategy combinations return HTTP 200,
`FEASIBLE` plans, no conflicts, and pass manual constraint validation. The
personal database remains unchanged. Details and current evidence are in
[RUNTIME_REPAIR_REPORT.md](RUNTIME_REPAIR_REPORT.md).

## Original failure and earlier diagnostics (historical)

Status: **generation remains blocked by Windows Application Control**. Error
reporting and retry behavior are corrected; this is not a completed solver repair.

**November 12 follow-up:** exact Windows events identify the built-in **Smart App
Control** policy, not evidence of an organization-managed machine. Smart App
Control has no individual-app allow exception. The earlier generic administrator
approval advice is superseded by [WINDOWS_RUNTIME.md](WINDOWS_RUNTIME.md), which
contains the verified policy, signing evidence and supported recovery routes.

## Reproduction and cause

The live application at `127.0.0.1:8765` had the date-specific workload preference
`high`. The Overview generation handler sent:

```json
{"date":"2026-11-13","mode":"balanced","reoptimize":false,"include_inactive_projects":false}
```

`POST /api/schedules/generate` returned HTTP 500, `Internal Server Error`. The
traceback in `logs/server-20261112-165630.err.log` reaches:

1. `backend/app/main.py`: import the schedule generator.
2. `backend/app/scheduler.py`: import `ortools.sat.python.cp_model`.
3. OR-Tools imports Pandas.
4. Windows refuses to load `pandas_parser.cp311-win_amd64.pyd` with
   `ImportError: DLL load failed ... An Application Control policy has blocked this file.`

Subsequent isolated imports also report the policy blocking Pandas' `algos`
native module. This is not limited to an invalid API enum. The parser binary's
SHA256 matches its installed Pandas RECORD; installed versions are Pandas 3.1.1
and OR-Tools 9.14.6206. No binary or security policy was modified.

The exception occurs before reading task inputs or evaluating the optimization
mode. Workload metadata remains separate from the Generate schema, which accepts
only `balanced`, `deadline` or `deep`. An attempted `mode: "high"` is correctly
rejected with HTTP 422. No workload objective or scheduling coefficient changed.

## Changes

- `backend/app/main.py`: narrow external solver-dependency preflight for generation
  and manual validation. ImportError/OSError produces HTTP 503 with an actionable
  explanation and preserves the full traceback in server logs. Application
  import errors and runtime solver exceptions are not mislabeled as dependency
  failures. No synthetic schedule is returned and no plan is overwritten.
- `frontend/src/App.tsx`: a generation failure now offers **Retry generation**,
  resending the exact failed POST. The previous button only fetched `/state`.
  Changing the date clears stale retry context. A successful POST followed by a
  failed refresh retries the refresh rather than generating twice.

## Data safety and actual evidence

Before the live reproduction, SQLite backup created
`data/backups/pre-generation-repair-20261112-170143.sqlite`. Every table matched
after the failed request; integrity and foreign-key checks passed. Subsequent
five-level tests use isolated copies, preserving the user's saved High choice.

Evidence under `test-results/generation-repair/`:

- `live-reproduction.json`: actual live request, response, backup and data audit.
- `dependency-integrity.json`: installed versions and binary RECORD verification.
- `direct-api-results.json` and `direct-api-log.txt`: actual requests on a copy of
  personal data, with all five workload values and all three valid optimization
  strategies. Each reaches the dependency block and returns 503. Invalid High as
  a strategy returns 422. Saved application state remains unchanged after failure.
- `full-backend-attempt.log`: full pytest attempted; three scheduler test modules
  fail collection because of the same native dependency policy rejection.
- `live-after-diagnostics.json`: after activation through the existing launcher,
  the same High + Balanced request now returns the explicit 503. Every personal
  table still matches the backup. The diagnostic/retry improvements are live at
  `127.0.0.1:8765`; generation remains unavailable.
- `browser-results.json` / `browser-report/`: actual browser requests for all five
  levels and each Retry send Balanced, never a workload value as the strategy.
  All ten requests return 503. The required-success workflow fails all five
  success assertions; the separate simulated-unavailable retry workflow passes.
  Edge also timed out while retaining the failed test's trace/tearing down.

These checks demonstrate the failing boundary and safe failure behavior, not
successful generation. Completion regression tests use real saved-block ledgers;
passing them does not establish successful reoptimization.

## Required external resolution

The confirmed Smart App Control block needs a legitimate trust/distribution
resolution; ordinary administrator rights do not provide an individual-app
exception. See [WINDOWS_RUNTIME.md](WINDOWS_RUNTIME.md) for Microsoft's documented
feedback and valid publisher-signing routes. Reinstalling/replacing native files
to evade the block, weakening policy, or removing OR-Tools is not an application
repair and was not attempted.

After the policy issue is resolved, rerun the real five-level generation/browser
checks and the full backend suite, including reoptimization, travel constraints
and preserved completion history. Do not declare the problem fixed until the
same November 13 High-workload operation returns a real valid generated schedule.

The dedicated browser regression uses a consistent backup, never the live data
file as its write target:

```powershell
$env:DAYCRAFT_GENERATION_SOURCE_DB = 'C:\Projects\schedule_builder\data\backups\pre-generation-repair-20261112-170143.sqlite'
npm.cmd --prefix e2e test -- --config=playwright.generation.config.js
```

The test requires actual HTTP 200 and real CP-SAT results. It deliberately fails
while the dependency is blocked instead of skipping or mocking solver success.
