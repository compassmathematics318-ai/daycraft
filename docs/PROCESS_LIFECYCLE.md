# Daycraft Windows process lifecycle

The existing `Launch Schedule Builder.cmd` remains the normal entry point. It
starts a hidden project Python child bound to `127.0.0.1` and keeps its launcher
window open. Closing that window or pressing Ctrl+C requests graceful Uvicorn
shutdown. `Stop Daycraft.cmd` can also stop managed instances from this workspace
without finding or terminating unrelated Python programs.

```powershell
& '.\Stop Daycraft.cmd'
& '.\Stop Daycraft.cmd' --port 8765
```

With no port, Stop visits the managed runtime records for this workspace.
Repeated Stop with no remaining records reports that nothing was stopped.
Explicitly naming a stale or missing record returns an error. It never escalates
to forced termination. If a long request prevents graceful shutdown, inspect the
server log before taking further action; the helper reports its bounded timeout.

## Diagnosis and repair

The previous launcher used `Stop-Process` in `finally`, immediately terminating
the Python launcher child instead of allowing application lifespan cleanup. On
Windows the virtualenv Python executable can also be a redirector with a separate
actual Python server child. A PID-only stop therefore did not establish that the
application had completed shutdown. The old parent watcher retained a process
handle but accepted a bare PID without verifying its creation time. The old
reuse check trusted any `schedule-builder` health response and ran migrations
before checking for an existing instance.

The repaired launcher serializes setup and startup with a workspace-specific
Windows mutex. Before setup/migration, it reuses only a healthy instance with the
same canonical workspace and database identities. Reuse checks the running
instance's actual solver probe; `-RequireScheduler` fails when that probe is
unavailable. A recognizable older Daycraft server without managed identity is
refused with instructions to close its original launcher. It is never silently
replaced or stopped. Other programs occupying the preferred port still cause
bounded localhost port fallback.

The child verifies the launcher's PID **and Windows process creation time**, then
retains that exact process handle. It requests shutdown when the retained process
object exits; PID reuse cannot make it track a replacement process. The child
reserves its localhost listener before importing the application, preventing an
occupied port from migrating a database or overwriting another instance's state.

## Graceful control and data safety

`scripts/serve.py` wraps the application with a private lifecycle interface;
normal backend app instances do not gain a shutdown route. The wrapper's
`GET /_daycraft/runtime` exposes only public instance identity, including hashes
of workspace/database paths and the actual server PID. A successful startup
writes `logs/runtime/<port>.json` containing that identity and an unpredictable
per-instance shutdown credential. The credential is never returned by HTTP or
printed. Stop verifies the record against the listener's complete identity before
an authenticated POST asks Uvicorn to drain requests and run lifespan shutdown.
It never kills by PID or executable name. Browser Origin/cross-site requests,
unexpected Host headers, non-loopback clients and missing/wrong credentials are
rejected. These controls protect against unrelated/browser requests; a local
account already able to read the project's private files can use the stop helper.

Application lifespan now disposes the SQLAlchemy engine in `finally`, including
startup/shutdown errors. Normal final SQLite connection closure checkpoints and
releases the WAL. No data or journal files are deleted by lifecycle code. The
runtime record is removed only after server shutdown, with bounded retries for
Windows file-sharing races. Stop waits for this removal to confirm completion.

`SCHEDULE_BUILDER_RUNTIME_DIR` optionally relocates runtime records. Launch and
Stop both honor its simple `KEY=VALUE` entry in `.env` without executing content;
the project's `.env` has precedence over the inherited process environment.
Keep that directory private and exclude it from backups. The normal `logs/`
directory, including runtime credentials, is excluded by the backup helper.
Never share a live runtime record. Stale records are not authority to stop a
different process: mismatched instance, PID, workspace or listener identity is
refused. Legacy/direct Uvicorn servers without these records are outside this
helper's management.

## Verification on November 12, 2026

All lifecycle tests used isolated temporary/copy databases and ports. No personal
database was edited by these tests and no existing personal/QA server was stopped.
Read-only process inspection found the separate QA Python redirector/server
processes; no listener was present on the default 8765 port at inspection time.
Initial CIM process inventory was denied; normal process inspection and the
lead's read-only TCP inventory supplied the usable evidence.

- `python -m pytest scripts/test_process_lifecycle.py -q`: **10 passed**. Real
  Stop command, preserved committed data, SQLite integrity/foreign keys, WAL
  release, rejected browser/auth requests, stale PID/instance/workspace records,
  occupied-port isolation, parent creation-time mismatch and legacy refusal.
- Focused Ruff for lifecycle scripts: passed.
- `python scripts/test_launcher.py`: exact CMD startup, migration/build smoke,
  occupied-port fallback, repeated launch reuse before migrations, strict reuse
  reflecting actual solver readiness and parent-exit graceful cleanup all passed
  on isolated ports 9175/9176 (exit 0).

Those initial lifecycle checks ran before dependency replacement and correctly
reported scheduling unavailable. After the verified Pandas 3.0.6 replacement,
the lead reran the launcher integration successfully: new startup and strict
reuse both reported an actual successful solver check, and every test instance
stopped gracefully. See `test-results/runtime-repair/active-launcher.log` and
`WINDOWS_RUNTIME.md`. Lifecycle repair changes no Windows security policy.
