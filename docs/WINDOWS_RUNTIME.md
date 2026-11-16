# Windows scheduling runtime: verified repair

## Current result — November 12, 2026, evening (Toronto)

**The active Windows runtime now generates real schedules while Smart App
Control remains enabled. No Windows Security action is required.** Only Pandas
changed, from 3.1.1 to official 3.0.6; Python 3.11.9, OR-Tools 9.14.6206,
NumPy 2.4.6 and all other locked versions remain unchanged. Both requirements
files pin the tested Pandas release. This was validated in a clean isolated
environment before active installation from the verified official wheel.

The active self-test returns `operational / ready / OPTIMAL`, `pip check` passes,
and `/api/solver-health` returns HTTP 200. On a consistent copy of personal data,
November 13 generation returned HTTP 200 and real `FEASIBLE` plans for all five
workloads and all three optimization strategies (15 combinations). Each plan
also passed the independent manual-edit constraint validation path. Workload
levels remain metadata, separate from solver strategies; no objective, time
limit, scheduler algorithm or migration changed.

The CPython 3.11 Windows x64 Pandas 3.0.6 wheel SHA256 is
`2e5fa32ff162dfdbc280157d664f44d23049ae414725af9676df339c501d82cd`.
All 46 installed native files match that official wheel. Its extensions remain
unsigned; execution under the enforced policy is observed, not a publisher
signature or a guarantee that future Windows reputation decisions cannot change.

Fresh investigation distinguished the old files: the 3.1.1 parser became loadable
at the raw Windows loader boundary, while `algos` still produced enforcement
event 3077 record 64150 at 23:54:11 UTC, WinError 4551 and the original SAC GUID.
The parser's archived block is historical, not evidence that it remained blocked.
The original complete import still failed on `algos`. No additional dependency
block was identified in the reviewed project events.

See [the completed repair report](RUNTIME_REPAIR_REPORT.md) for execution results,
data preservation, shutdown and backup instructions, and
[the trust investigation](RUNTIME_TRUST_INVESTIGATION.md) for official provenance,
isolated checks and supported fallback options. The installed Windows 11 25H2
build is 26200.9711. Its known SAC re-enable issue is documented there; changing
security settings was unnecessary for this repair.

## Original diagnosis below (historical, before replacement)

Checked on this Windows installation on November 12, 2026. **Actual schedule
generation remains blocked. No solver success is claimed.**

## Exact mechanism and files

The block is **Smart App Control**, enforced by Windows Code Integrity's built-in
`VerifiedAndReputableDesktop` policy:

- Policy GUID: `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`
- Policy ID/version from the event: `27555.1000.240208`
- Event channel: `Microsoft-Windows-CodeIntegrity/Operational`
- Enforcement event: **3077**, status **0xc0e90002**, with correlated 3033/3089
- Requested signing level 2; validated signing level 1

Microsoft identifies this exact policy name/GUID as the policy active when
[Smart App Control is on](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/inbox-appcontrol-policies).
The event's generic phrase "Enterprise signing level" does **not** establish
that this personally owned device is managed by an organization.

Both verified blocked files are under
`C:\Projects\schedule_builder\.venv\Lib\site-packages\pandas\_libs\`:

| File | Recorded enforcement evidence |
| --- | --- |
| `pandas_parser.cp311-win_amd64.pyd` | 3077 record 63486, 2026-11-12 21:56:35 UTC |
| `algos.cp311-win_amd64.pyd` | 3077 record 63614, 2026-11-12 22:33:51 UTC |

These files have **no recognized Authenticode signer** (`NotSigned`). There is
no verified publisher certificate for an administrator to approve on these
particular binaries. The Python executables themselves have valid **Python
Software Foundation** signatures, which do not confer trust on loaded extensions.
Unsigned does not by itself mean corrupt or malicious. The cloud reputation
decision behind this block cannot be established from the available evidence.

The active policy file and registry Smart App Control state 1 corroborate the
blocking event. No matching AppLocker event was found. `CiTool` policy listing
and Device Guard CIM were denied by Windows, including an approved read-only
escalation. The blocking event XML itself identifies the policy conclusively;
no retained matching 3099 activation event establishes when enforcement began.

Evidence, hashes and exact native paths:
`test-results/windows-runtime/windows-policy-evidence.json`.

## Why this dependency loads

The launcher uses `.venv\Scripts\python.exe`, CPython 3.11.9 x64, with the
expected Python 3.11 base installation and system site-packages disabled.
Installed versions: OR-Tools 9.14.6206, Pandas 3.1.1, NumPy 2.4.6.

The import chain is Daycraft `scheduler.py` -> OR-Tools `cp_model.py` -> Pandas
-> its native extensions. Daycraft uses scalar CP-SAT operations, but the
[official OR-Tools wrapper](https://raw.githubusercontent.com/google/or-tools/v9.14/ortools/sat/python/cp_model.py)
imports Pandas unconditionally and evaluates Pandas types during import. Its
[release metadata](https://pypi.org/pypi/ortools/9.14.6206/json) requires Pandas
>=2.0.0. Removing or stubbing Pandas would be an unsupported replacement of a
required dependency, not removal of an unnecessary Daycraft import.

`pip check` passes. RECORD verification found no missing/mismatched hashed files
among 223 OR-Tools, 1,063 NumPy and 1,605 Pandas entries. The lockfile matches the
launcher's dependency stamp. The installed RECORD consistency does **not** prove
remote wheel provenance; installer metadata says pip and contains no direct URL.
No evidence supports blindly rebuilding the environment or reinstalling the same
files as a remedy for this explicit policy block. No dependencies were changed.

## What you can do on this personal PC

**Correction to earlier guidance:** ordinary administrator rights are not a
per-file approval for Smart App Control. Microsoft's
[Smart App Control FAQ](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions)
says it has no individual-app allow exception. The earlier suggestion to ask
an administrator to simply allow these files was too generic for this mechanism.

1. Open **Windows Security -> App & browser control -> Smart App Control** to
   inspect its status. No security setting needs changing to inspect it.
2. Open **Event Viewer -> Applications and Services Logs -> Microsoft -> Windows
   -> CodeIntegrity -> Operational**. Locate event 3077 for the exact project
   paths above. The evidence JSON includes record IDs, policy and hashes.
3. Report the reproducible legitimate-package block to Microsoft through
   **Feedback Hub (Win+F) -> Security and Privacy -> Smart App Control** and/or
   the dependency maintainers. Share only the relevant event, versions and hashes,
   not the personal SQLite database. Microsoft documents this feedback route;
   it does not guarantee a trust decision or immediate unblocking.
4. Request an officially supplied, compatible distribution whose **native
   dependencies**, not only its installer/Python executable, satisfy Windows
   trust requirements. Microsoft recommends valid publisher signing for app
   developers. No such replacement build was independently established as trusted
   on this computer during this investigation, so none was substituted.

Those are legitimate review/distribution routes, not an available local "Allow"
button. Self-signing/renaming the denied binaries, disabling protections,
altering policy, or switching environments solely to evade the block was not
attempted. An alternative runtime would need independent approval and actual
Windows integration testing before it could be called a supported remedy.

## Runtime checks now provided

```powershell
.venv\Scripts\python.exe -m backend.app.solver_health
```

This starts a bounded, hidden child using the **same virtualenv interpreter**,
imports the actual solver, validates a tiny known-feasible model and solves it.
Only FEASIBLE/OPTIMAL with the correct variable value returns `operational` and
exit 0. The check does not access the user database. It classifies missing
packages, explicit policy blocks, other load failures, invalid configuration,
native crashes/initialization failures and timeouts. An infeasible self-test is
a failed probe, not evidence that the user's schedule is infeasible.

`GET /api/solver-health` exposes this real check: HTTP 200 when operational,
HTTP 503 otherwise, concise public fields and full details in local logs.
`GET /health` remains process/workspace liveness only.

The Windows launcher performs this probe and writes
`logs/solver-health-<timestamp>.json` plus `.err.log`. It can open the workspace
while explicitly warning that scheduling is unavailable. **Workspace ready** is
distinct from **Scheduling ready**. For a strict startup check:

```powershell
powershell -NoProfile -File scripts\launch.ps1 -NoBrowser -SmokeTest -RequireScheduler
```

Use the existing launcher normally if your PowerShell execution policy requires
its established launch method. `-RequireScheduler` exits unsuccessfully before
starting the workspace when the solver probe fails. It does not change policy.

After the trust issue is legitimately resolved, repeat the probe and the real
November 13 Medium generation. Then run the dedicated five-workload browser
regression and full backend suite. Workload levels remain per-date metadata;
they never substitute for Balanced/Deadline First/Deep Work or change objectives.
