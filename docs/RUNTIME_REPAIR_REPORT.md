# Daycraft verified Windows runtime repair — November 12, 2026

## Outcome and exact change

Real schedule generation is restored in the active project virtualenv while
Windows Smart App Control remains enforced. No Windows Security setting,
registry policy, binary signature or scheduler algorithm was changed. The user
does not need to disable or reconfigure a Windows protection.

Only **Pandas 3.1.1 -> 3.0.6** changed. The official CPython 3.11 Windows x64
wheel was verified against PyPI's SHA256 and tested in a clean environment with
the rest of the 34-package lock unchanged. The same verified wheel was installed
into `.venv` with `--no-index --no-deps`. Both requirements files now pin 3.0.6;
the launcher's hash stamp matches the updated lock. No speculative reinstall of
the blocked bytes occurred. The original official wheel and pre-edit lockfiles
remain in `test-results/runtime-repair/` for audit/recovery.

The installed Python is 3.11.9, OR-Tools 9.14.6206 and NumPy 2.4.6. The active
environment passes `pip check`. All 46 installed Pandas native entries match
the official wheel byte-for-byte. The exact provenance, ABI requirements,
signature limits and Windows sources are in
[RUNTIME_TRUST_INVESTIGATION.md](RUNTIME_TRUST_INVESTIGATION.md).

## Windows evidence and limits

Windows 11 25H2 build 26200.9711 has SAC state 1. The enforced policy is
`VerifiedAndReputableDesktop`, GUID
`{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. The old `algos` extension still produced
3077 record 64150, status `0xc0e90002`, and a direct loader WinError 4551 before
replacement. The old parser loaded in the later raw loader check; its earlier
block must not be presented as a current block. No new different dependency was
identified in the reviewed project events.

Official provenance is stronger than installed RECORD consistency but is not
publisher Authenticode signing. The new build executes under the unchanged
policy on this PC; cloud reputation can change. Keep the launcher self-test.
If a future block occurs, use the documented official review/distribution routes.
SAC has no ordinary per-app exception. This Windows build has a documented
re-enable regression; current Microsoft update guidance and supported manual
options are recorded in the trust investigation. None was needed or applied.

## Real generation and data preservation

- `.venv\Scripts\python.exe -m backend.app.solver_health`: exit 0,
  `operational`, `ready`, `OPTIMAL`. `/api/solver-health`: HTTP 200.
- Original date **Friday, November 13, 2026**: all five workloads crossed with
  Balanced / Deadline First / Deep Work produced **15 HTTP 200, FEASIBLE plans**.
  Each had nonempty actual blocks, no conflicts and passed a subsequent real
  manual-edit constraint validation request. These are feasible incumbents;
  global objective optimality is not claimed.
- Workload-as-strategy remains HTTP 422. No workload-dependent solver behavior
  was introduced, and CP-SAT objectives/time limits remain unchanged.
- Definitions, priorities, projects, relationships, calendar metadata and settings
  remained unchanged by generation. The source database matched its consistent
  snapshot and passed SQLite integrity and foreign-key checks. Tests wrote only
  isolated copies; the user's saved workload preference was preserved.
- The personal reproduction sample contained no credited chunks, completed
  logical sessions or pre-existing locked work blocks. Nonempty completion,
  locked-work, weekly/daily-limit, travel, suitability, fixed-calendar, break and
  meal cases are covered by the backend and browser regression suites. Do not
  infer nonempty-history coverage from the empty personal sample alone.

Evidence: `active-health.json`, `active-pip-check.log`,
`active-runtime-verification.json`, `active-install-report.json`,
`actual-generation.json` and its log under `test-results/runtime-repair/`.
Initial 503 results remain in `before-actual-generation.json` and
`before-browser/`; failed/blocked attempts have not been relabeled successful.

## Additional repair exposed by the working solver

Generated calendar blocks returned relationship snapshots that the strict manual
edit schema rejected on round trip. The input schema now recognizes those two
fields. Explicit changed/forged values are rejected with HTTP 422, omitted values
retain the saved server snapshot, and unrelated unknown fields remain forbidden.
Two real solver regression cases cover unlinked/linked context, unchanged edits,
older-client omission, forged values, unchanged persistence and fixed times.

Old test assumptions were aligned with documented elapsed-work preservation,
delete-everywhere tombstones and post-end completion confirmation by using
explicit clocks. Production lifecycle/completion rules were not weakened.

## Shutdown and backup delivery

Use **Stop Daycraft.cmd** to request authenticated graceful termination of this
workspace's managed instances. The launcher serializes startup, checks exact
workspace/database identity, handles repeated launches, retains the parent's
Windows process handle and creation time, and refuses mismatched or unmanaged
instances. No global Python termination is used. SQLAlchemy disposal runs in
`finally`; normal shutdown releases SQLite connections and WAL handles.
Closing an editor does not necessarily close a separately launched application
window. [PROCESS_LIFECYCLE.md](PROCESS_LIFECYCLE.md) explains supported paths.

Use **Backup Daycraft.cmd** for a verified source/data ZIP even while the app
runs. SQLite's online backup API creates a standalone, integrity-checked snapshot;
the ZIP includes source, lockfiles, compiled UI and a hash manifest, excludes live
DB journals, caches, virtualenvs and node_modules, and never overwrites archives.
`--full` is a separate larger environment option. Literal full-folder copies
remain possible after stopping all instances. See [BACKUP.md](BACKUP.md).

## Verification record

The exact full active backend command returned **653 passed, one failed**:
the synthetic overloaded test exceeded its three-second budget during concurrent
browser accessibility work. The unchanged test then **passed alone in 3.56s**,
with its same solver budget. Both logs remain. This timing sensitivity is a
remaining performance limit, not a native import failure; no time limit or
optimization guarantee was relaxed to make a test pass.

All **25** focused backup/lifecycle tests pass. Frontend TypeScript, ESLint,
**184** Vitest tests and the production build pass; backend/helper Ruff passes.
The active launcher integration passes startup, occupied-port fallback, reuse,
strict solver readiness, graceful stop and parent-exit cleanup.

The broad Edge run returned **35 passed, four failed**. The failures involved two
fresh-profile theme fixtures, a selected-week loading race in a fixture, and
outdated confirmation wording. Their corrected active-runtime reruns passed
(three together, then the remaining venue case). All 39 workflows therefore
have passing coverage across explicitly separate runs, not one all-green broad
run. An intermediate incorrect venue wait is also retained as failed evidence.
Production frontend behavior and visual design were not changed.

The final browser-generation result and source/data archive are recorded in
[PROGRESS.md](PROGRESS.md). Detailed before/after results are retained under
`test-results/runtime-repair/`. Automated provider calls use offline/stubbed
responses; live map services are not revalidated. Browser coverage uses installed
Edge and emulated viewports, not every browser or physical mobile device.
