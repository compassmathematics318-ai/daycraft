# Daycraft backups and recovery

Double-click **Backup Daycraft.cmd** to create a source/data ZIP in `data/backups/`.
The application may stay open. The helper uses Python's standard library, does
not import OR-Tools or Pandas, and does not install dependencies, modify personal
records, or delete previous backups. A successful run prints the exact new path.
Copy that archive to another device or trusted storage: an archive on the same
disk does not protect against disk failure.

For a terminal run without the final pause:

```powershell
.venv\Scripts\python.exe scripts\backup.py
```

The default is a portable **source/data backup**. It contains the backend,
frontend, migrations, tests, scripts, docs, the intelligent scheduling guide,
supported root project/configuration
files, lockfiles, the existing compiled frontend, and a consistent personal
database snapshot stored as `data/schedule_builder.db`. Installed Python/Node
dependencies are recreated from lockfiles when needed. Optional provider/path
settings from `.env` must be restored separately from a trusted copy or recreated
using `.env.example`; the normal app settings, tasks, project relationships,
calendar, schedules and completion records are inside the personal database.
Browser-profile state is not included. A browser-local theme preference can take
precedence over the saved server theme; reselect the desired theme after recovery.

The database is selected using the launcher's configuration order: explicit
`--database`, then `SCHEDULE_BUILDER_DB` in the project's literal `.env`, then the
process environment, then `data/schedule_builder.db`. Relative paths are resolved
from the project folder. The manifest records the original database path; even
an externally configured database is stored at the standard path in the ZIP.
If an already running process was launched with a different configuration,
specify its actual database explicitly.

```powershell
.venv\Scripts\python.exe scripts\backup.py --database 'D:\Daycraft\personal.db' --output 'C:\Users\YOUR_USERNAME\Documents\daycraft-safe-copy.zip'
```

The destination must be new and end in `.zip`. Timestamped default filenames
include a random suffix; neither an existing file nor a file created by another
backup during the run can be overwritten. Publication uses a same-volume hard
link after verification; use a local NTFS destination, then copy the completed
ZIP to storage that does not support hard links. Missing databases are errors;
the helper never creates an empty replacement personal database.

## What is verified

SQLite's online backup API reads committed data, including committed WAL content,
into a separate snapshot. Uncommitted work is excluded. The source database is
opened read-only; the helper never copies the active database, WAL, SHM or journal
files into the ZIP. The snapshot must pass `PRAGMA integrity_check` and
`PRAGMA foreign_key_check` before publication. Existing integrity/FK violations
fail the backup and leave the source intact. Snapshotting retries briefly under
contention and stops after 30 seconds; `--timeout 60` changes that bound.

`BACKUP_MANIFEST.json` records the backup type/time, original database path,
migration versions, snapshot table counts, validation results, omitted links and
exclusion policy. Every archived file has a byte count and SHA-256 hash. The
helper rereads the completed ZIP and verifies its CRCs and manifest hashes before
publishing. Recheck an archive at any time:

```powershell
.venv\Scripts\python.exe scripts\backup.py --verify 'data\backups\daycraft-source-data-EXAMPLE.zip'
```

This verification detects accidental changes; the manifest is not a digital
signature. Source files are checked for size/time changes while each is copied,
but a source tree is not transactional. Finish code edits and builds before
making a release backup. The database remains transactionally consistent even
while the app is open. Tests use temporary synthetic databases, including a live
WAL database with committed and uncommitted records.

## Full environment option and exclusions

For a separate, much larger local environment archive:

```powershell
.venv\Scripts\python.exe scripts\backup.py --full
```

This is labeled **full-environment** and additionally includes `.venv`,
`node_modules`, `.git` and `.env` when present. It can contain credentials and
machine-specific packages; keep it private. Python environments may contain
absolute paths, and native packages remain subject to Windows device policies.
Use the lockfiles to reinstall dependencies on a different machine or path.
The source/data backup is the smaller recovery option; a full environment ZIP is
an optional additional archive. Neither mode replaces or deletes existing full
copies or earlier database backups.

Both modes omit the existing `data/` tree (except the newly validated personal
snapshot), route/search caches, historical backup archives, logs, test results,
Playwright reports, Python/package/tool caches, raw database files and sidecars,
existing ZIPs, temporary backup staging, symlinks and Windows reparse points.
Runtime state/control tokens under `logs/runtime` and the configured
`SCHEDULE_BUILDER_RUNTIME_DIR` are always omitted. `.aws`, `.ssh`, `.azure`,
`.codex` and `.agents` directories are also always omitted. Historical backups
should be retained separately; they are not nested recursively in each new ZIP.
Route/search caches can be recreated and are not needed to restore personal data.

The portable mode also omits installed environments, `.git`, `.env` variants
except `.env.example`, common credential filenames/private-key extensions and
unlisted top-level directories. Arbitrary custom assets outside `backend/`,
`frontend/`, `e2e/`, `scripts/` or `docs/` need their own copy or the full option.
The helper is not a general secret scanner. Both archive types contain private
personal planning data.

For a literal full-folder archive, first use Stop Daycraft and confirm every
instance using the project has exited, then copy/compress the entire project to
a separate destination. Keep existing archives and database sidecars together;
do not delete them to make compression succeed. The online source/data backup
above is the supported way to package a consistent database while the app runs.

## Recover without overwriting the current workspace

1. Keep the original ZIP and verify it with `--verify`. Extract into a **new,
   empty folder**, not over the running project. Inspect `BACKUP_MANIFEST.json`
   and confirm the source snapshot, migration version and expected table counts.
2. Stop all Daycraft server/launcher processes before any in-place database
   replacement. Preserve the current project and its entire `data/` folder under
   a new name or on another disk. Never combine a restored DB with a prior
   database's `-wal`, `-shm` or `-journal` files. The ZIP's snapshot is standalone.
3. Prefer starting the extracted project as its own copy after stopping the old
   instance. Keep the extracted `data/schedule_builder.db` together with its
   matching source/migrations. Recreate `.env` as needed; remove obsolete custom
   `SCHEDULE_BUILDER_DB` overrides or deliberately point them at the recovered
   database. The manifest's `original_path` is guidance, not an instruction to
   overwrite that file. Also review inherited process environment overrides.
4. Launch `Launch Schedule Builder.cmd`. A portable copy needs Python/Node and
   may need Internet access to reinstall locked dependencies. The launcher may
   apply migrations; keep the original archive untouched so that the prior
   source/schema pair remains available. A full copy may also need its local
   environment recreated for its new location. Do not treat a copied native
   package as an exemption from device policy.
5. Check the expected settings, locations, calendar, tasks/projects, saved
   schedules and completion history in the UI. Keep the old workspace and ZIP
   until recovery is confirmed. Recovery does not require demo-data insertion.

For a data-only recovery into the existing project, first make a fresh verified
backup and stop every process using the target DB. Prefer moving the old whole
`data` folder aside intact, then creating a new `data` folder containing only the
snapshot. If your DB is external, preserve it and its sidecars together in a
separate folder before placing the snapshot at the configured path. Do not
delete journals or live data as a dependency-repair step. The helper deliberately
provides no automatic overwrite/restore command.
