# Runtime trust investigation — November 12, 2026

An official, metadata-compatible Pandas 3.0.6 build passed a real CP-SAT solve
and the application's exact solver-health check in a clean isolated environment
while Smart App Control remained enforced. This isolated investigation phase
changed no active packages. The lead records subsequent active dependency
activation and live verification separately; the isolated results alone do not
establish that live generation is repaired.

## Rechecked Windows evidence

The installed OS is Windows 11 25H2, build **26200.9711**. The registry's legacy
`ProductName` string still reads `Windows 10 Home`; build and DisplayVersion are
recorded explicitly to avoid using that string as the OS identification.
`VerifiedAndReputablePolicyState` remains **1** (enforcement).

Fresh active-runtime checks returned exit 1, `windows_policy_blocked`, on
`pandas/_libs/algos.cp311-win_amd64.pyd`. New project event 3077 records beyond
the previous investigation identify the same
`{0283ac0f-fff1-49ae-ada1-8a933130cad6}` SAC policy; the evidence retains their
timestamps and original XML. The virtualenv and base Python executables still
have valid Python Software Foundation signatures. The blocked Pandas extensions
still report `NotSigned` and have the same hashes as previously recorded.

Evidence: `test-results/runtime-repair/windows-current-evidence.json` and
`solver-self-test.json`. No security setting, interpreter executable, application
data, or active package was changed during these checks.

An additional exact-path raw Windows loader check at **23:54 UTC** distinguished
the two previously denied binaries: `ctypes.WinDLL` successfully loaded the
active **pandas_parser** file, while **algos** returned explicit **WinError 4551**,
"An Application Control policy has blocked this file." A fresh correlated event
3077 for algos is record **64150**, **23:54:11.5488511 UTC**. The archived parser
3077 remains historical evidence; it is inaccurate to say both binaries are
currently blocked. Raw parser load success does not initialize its Python module
or establish that full Pandas/OR-Tools import succeeds: the active complete import
remains blocked at algos. Unchanged file hashes alone do not establish unchanged
cloud reputation. Evidence: `exact-active-native-load-check.json` and
`exact-active-native-latest-events.json` (the immediate time-filtered event query
returned no rows before the new event appeared in the channel).

## Official distribution provenance

The earlier installed RECORD comparison established internal consistency only.
This investigation downloaded the exact official PyPI CPython 3.11 Windows x64
wheels into isolated evidence storage, verified each wheel against the SHA256
published by the PyPI JSON API over HTTPS, and compared every native `.pyd` and
`.dll` entry with the installed bytes. **All compared installed native files
matched their official wheel bytes** for Pandas 3.1.1, NumPy 2.4.6 and OR-Tools
9.14.6206. Reinstalling those same bytes has no supported repair rationale.

| Official wheel | Verified wheel SHA256 |
| --- | --- |
| pandas 3.1.1 cp311 win_amd64 | `48066660db2f0d652b0f4df5743ca975e9b568043084c86e575b0eda648f7c64` |
| numpy 2.4.6 cp311 win_amd64 | `1e254a00cdf42b1e4d5b3d68d33af63268d41340d8885df2ab6470f2e1500147` |
| ortools 9.14.6206 cp311 win_amd64 | `ca60877830a631545234e83e7f6bd55830334a4d0c2b51f1669b1f2698d58b84` |

Sources: official PyPI JSON for
[Pandas](https://pypi.org/pypi/pandas/3.1.1/json),
[NumPy](https://pypi.org/pypi/numpy/2.4.6/json), and
[OR-Tools](https://pypi.org/pypi/ortools/9.14.6206/json).
Machine evidence and reproducible comparison code are `pypi-provenance.json`
and `compare_official_wheels.py` under `test-results/runtime-repair/`.

## Bounded compatible alternative investigation

OR-Tools' official metadata requires Pandas >=2.0.0. The official 3.0.6 release
is a recent maintenance patch released September 17, 2026, as documented in the
[Pandas release notes](https://pandas.pydata.org/docs/whatsnew/v3.0.6.html).
Its official PyPI metadata specifies Python >=3.11 and NumPy >=1.26.0 for this
Python version. Its `cp311-cp311-win_amd64` wheel matches this interpreter's ABI
and architecture. NumPy 2.4.6 and the application's pinned OR-Tools satisfy those
metadata requirements. This is a concrete compatibility basis for testing it;
an older version's age alone is not a trust argument.

Pandas 3.0.6 official wheel SHA256:
`2e5fa32ff162dfdbc280157d664f44d23049ae414725af9676df339c501d82cd`.

Signature-only inspection found 45 unsigned native files and one valid Microsoft
runtime DLL in that wheel. Pandas 2.3.3 was inspected as a second official
distribution example (44 unsigned files and one valid Microsoft runtime DLL),
but was not installed or executed because no stronger current support case was
established for that older line. Neither is a publisher-signed Pandas replacement.
The installed OR-Tools/NumPy native files likewise include 45 unsigned files and
one valid Microsoft runtime DLL. Independent NumPy 2.4.6 import succeeded.
Unsigned status alone therefore does not predict SAC's reputation decision.

Under the user's authorization for isolated official-build testing, a clean
virtualenv was created at
`test-results/runtime-repair/solver-env-3.0.6/`, using the same signed Python
3.11.9 base and with system site-packages disabled. Only official wheels were
installed. Two initial standard health probes exceeded the 15-second timeout
during cold setup; those failures are retained. A bounded diagnostic then
imported real NumPy 2.4.6, Pandas 3.0.6 and OR-Tools 9.14.6206 and solved a real
known-feasible model with **OPTIMAL**, x=1, in 6.66 seconds. The unchanged standard
`python -m backend.app.solver_health` subsequently returned **operational / ready
/ OPTIMAL**, exit 0.

The complete application's pinned dependency set was then installed into this
isolated environment using `candidate-requirements.lock.txt`, differing from
the active lock only in Pandas 3.0.6. This restored tzdata to the application's
2025.2 pin (the initial solver-only resolution had used 2026.6). `pip check`
passed and the exact health check again returned **OPTIMAL**, exit 0.

Evidence: `alternative-wheel-metadata.json`, `native-signature-analysis.json`,
`isolated-3.0.6-extended-probe.json`, `isolated-3.0.6-health-final.json`,
`candidate-install-report.json`, `candidate-pip-check.log`, and
`candidate-health-full-app.log` under `test-results/runtime-repair/`.

The frozen environment comparison confirms that **only Pandas differs among
all 34 active locked packages** and every candidate Pandas native file matches
the verified official wheel. The full backend suite executed with this isolated
interpreter: **640 passed, 12 failed, one warning, 116.82 seconds**. The failing
assertions expose application integration issues now reachable through the real
solver, including returned block metadata rejected on save, legacy task
completion/deletion expectations, and one overloaded three-second solver timeout.
The overloaded test passed when rerun alone (**1 passed, 3.60 seconds**), so its
first failure does not establish a deterministic candidate-runtime defect.
No failed assertion is described as passing and no active promotion occurred.
Evidence: `candidate-environment-comparison.json`, `candidate-verification.json`,
`full-backend.log`, and `overloaded-solver-rerun.log`.

Follow-up review established that the completion/deletion failures reflected
stale test clocks or superseded lifecycle contracts. Their tests now explicitly
set the instant before pending work or at the saved end before confirmation;
deletion verifies tombstoning and preservation of confirmed evidence. Original
test files are retained in `pre-test-audit/`. The returned related-entity fields
were a real production roundtrip bug, addressed by the lead without stripping
them from test payloads. All 11 deterministic failing cases then passed together
(**11 passed, one warning, 7.46 seconds**) in
`focused-audit-after-fixes.log`. The three modified test files passed Ruff.
This focused result does not substitute for the final complete suite.

Final candidate coverage then passed: **653 passed, one deselected, one existing
warning, 142.32 seconds**, exit 0. The exact command was
`solver-env-3.0.6/Scripts/python.exe -m pytest backend/tests -q -k 'not overloaded_task_list_starts_with_meaningful_feasible_progress'`.
Only the already independently passed three-second overloaded test was excluded
while simultaneous real browser generation could contend for CPU. Together with
that unchanged standalone test result, all **654** backend cases executed and
passed across these final checks. These are separate executed runs, not a claim
that one uninterrupted 654-test command passed. Exact evidence:
`final-candidate-backend.log`, `final-candidate-backend-result.json`, and
`overloaded-solver-rerun.log`. The integration lead owns the subsequent exact
full-suite command against the active interpreter after browser contention ends.

Post-test SAC state remained **1**. No event 3077 matching the isolated candidate
environment was found in the queried test interval (`sac-after-candidate-test.json`).
Read-only process inventory after the cold-probe timeouts found only the running
test harness and its actual pytest redirector/base process pairs; no worker from
the earlier timed-out probes remained. This observation is not a general proof
of Windows timeout process-tree behavior (`python-process-inventory.json`).

Pandas' published [version policy](https://pandas.pydata.org/docs/development/policies.html)
describes major/minor compatibility and Python support; it does not promise a
specific long-term security-maintenance window for 3.0.6. This investigation
therefore calls it an official compatible recent patch, rather than claiming
an independently established long-term-support guarantee. Its successful load
is evidence of acceptance on this machine at test time; it does not establish
why Microsoft's reputation decision differs or guarantee future acceptance.

Independent final archive rereading reconfirmed the 3.0.6 wheel hash, ABI tag and
dependency metadata. Daycraft's backend has no direct Pandas/NumPy imports; the
Pandas dependency enters through the official OR-Tools wrapper. The recommendation
at this handoff is to treat 3.0.6 as a suitable official compatible replacement
candidate, conditional on complete application verification and ordinary reviewed
dependency activation. It is not a recommendation to bypass SAC or to call the
unsigned Pandas extensions publisher-signed. The final integration owner records
the live activation and final suite results separately.

## Current Microsoft guidance and this build's caveat

The current Microsoft [Smart App Control FAQ](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions)
still says there is no individual-app exception. It now also says recent
Windows updates allow SAC to be enabled again without a clean installation.
Microsoft's [March 26 release note](https://support.microsoft.com/en-us/servicing/os/windows-11/2026/03/march-26-2026-kb5079391-os-builds-26200-8116-and-26100-8116-preview)
documents rollout of that change. The older blanket statement that disabling
SAC always requires resetting Windows to re-enable it is no longer accurate.

However, this PC's installed build **26200.9711** is specifically covered by
Microsoft's [KB5127648 known issue](https://support.microsoft.com/en-us/servicing/os/windows-11/2026/10/kb5127648-windows-11-24h2-25h2-26h2-security-update):
some devices cannot turn SAC on after it is turned off, because On is grayed
out. Microsoft documents a fix for 25H2 in
[KB5127936, build 26200.9818](https://support.microsoft.com/en-us/servicing/os/windows-11/2026/10/kb5127936-windows-11-25h2-26h2-update)
and later updates. Consequently, this investigation does **not** promise a
reversible SAC toggle on the currently installed build. No update or toggle was
performed. Windows updates address that settings regression; they are not proof
that these specific Pandas binaries will receive a different trust decision.

A security change is unnecessary if the independently validated official
compatible build passes full application verification and is adopted through
normal dependency management. If that path fails, supported user-controlled
choices include maintaining protection while reporting the legitimate package
block through Feedback Hub / upstream maintainers, obtaining a publisher-signed
compatible distribution, or explicitly deciding whether to change the system's
SAC setting after checking current Windows updates and eligibility. No local
per-file approval, self-signing, policy edits, renamed binaries, Pandas stubs,
or protection changes were attempted.
