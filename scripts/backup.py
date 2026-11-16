"""Portable source/data backups using SQLite's online backup API (stdlib only)."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = {"backend", "frontend", "e2e", "scripts", "docs", "intelligent_schedule_building_guide"}
ROOT_SUFFIXES = {".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".cmd", ".ps1", ".py"}
ALWAYS_EXCLUDED = {
    "test-results", "playwright-report", "__pycache__",
    ".pytest_cache", ".ruff_cache", ".cache", ".npm-cache", ".mypy_cache",
    ".aws", ".ssh", ".azure", ".codex", ".agents",
}
ROOT_EXCLUDED = {"data", "logs"}
REINSTALLABLE = {".venv", "venv", "node_modules", ".git"}
DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
SECRET_FILENAMES = {
    ".npmrc", ".pypirc", ".netrc", "credentials", "credentials.json",
    "secrets.json", "token.json", "tokens.json", "id_rsa", "id_ed25519",
}


class BackupError(RuntimeError):
    pass


def configured_value(root: Path, key: str) -> str:
    """Match launch.ps1's literal .env override without executing its content."""
    value = os.environ.get(key, "")
    dotenv = root / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"^\s*" + re.escape(key) + r"\s*=\s*(.*?)\s*$", line, re.IGNORECASE)
            if match:
                value = match[1].strip('"').strip("'")
    return value


def configured_database(root: Path, explicit: str | None = None) -> Path:
    value = configured_value(root, "SCHEDULE_BUILDER_DB")
    path = Path(explicit if explicit is not None else value or "data/schedule_builder.db")
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def snapshot_database(source: Path, destination: Path, timeout: float = 30) -> dict:
    if not source.is_file():
        raise BackupError(f"Personal database does not exist: {source}. No empty database was created.")
    deadline = time.monotonic() + timeout

    def progress(_status, _remaining, _total):
        if time.monotonic() >= deadline:
            raise BackupError(f"Database snapshot exceeded {timeout:g} seconds; retry when writes settle.")

    # mode=ro prevents accidental creation or writes to the user's source DB.
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1)) as original:
        with closing(sqlite3.connect(destination)) as snapshot:
            original.backup(snapshot, pages=256, progress=progress, sleep=0.05)
            # Produce one standalone DB, with no dependency on a WAL sidecar.
            snapshot.execute("PRAGMA journal_mode=DELETE")
            integrity = [row[0] for row in snapshot.execute("PRAGMA integrity_check")]
            foreign_keys = snapshot.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != ["ok"] or foreign_keys:
                raise BackupError("Snapshot validation failed: integrity=" + repr(integrity)
                                  + ", foreign_key_violations=" + str(len(foreign_keys)))
            tables = [row[0] for row in snapshot.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )]
            counts = {}
            for table in tables:
                quoted = '"' + table.replace('"', '""') + '"'
                counts[table] = snapshot.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
            versions = []
            if "alembic_version" in tables:
                versions = [row[0] for row in snapshot.execute("SELECT version_num FROM alembic_version")]
    return {"method": "sqlite3.Connection.backup (read-only source)",
            "original_path": str(source), "archive_path": "data/schedule_builder.db",
            "integrity_check": integrity, "foreign_key_violations": len(foreign_keys),
            "table_counts": counts, "alembic_versions": versions}


def excluded_file(path: Path, full: bool) -> bool:
    lower = path.name.lower()
    if path.suffix.lower() in DATABASE_SUFFIXES or any(
        lower.endswith(suffix) for suffix in ("-wal", "-shm", "-journal", ".pyc", ".pyo", ".log", ".zip", ".partial")
    ):
        return True
    if not full and (lower == ".env" or lower.startswith(".env.") and lower != ".env.example"
                     or lower in SECRET_FILENAMES
                     or path.suffix.lower() in {".pem", ".key", ".pfx", ".p12"}):
        return True
    return False


def source_files(root: Path, full: bool, database: Path):
    """Prune runtime/data trees before walking; never follow links or junctions."""
    omitted_links = []
    files = []
    runtime = Path(configured_value(root, "SCHEDULE_BUILDER_RUNTIME_DIR") or "logs/runtime")
    runtime = (root / runtime).resolve()
    if runtime == root or runtime in root.parents:
        raise BackupError("Runtime state directory covers the source root. Configure a dedicated runtime subdirectory before backing up.")
    for current, directories, names in os.walk(root, followlinks=False):
        directory = Path(current)
        relative = directory.relative_to(root)
        retained = []
        for name in sorted(directories):
            child = directory / name
            # Windows junctions are not reported as symlinks on older Python.
            attributes = getattr(child.lstat(), "st_file_attributes", 0)
            if child.is_symlink() or attributes & 0x400:
                omitted_links.append(child.relative_to(root).as_posix())
                continue
            if (name in ALWAYS_EXCLUDED or relative == Path(".") and name in ROOT_EXCLUDED
                    or child.resolve() == runtime or name.startswith(".daycraft-backup-")
                    or not full and name in REINSTALLABLE):
                continue
            if relative == Path(".") and not full and name not in SOURCE_DIRS:
                continue
            retained.append(name)
        directories[:] = retained
        for name in sorted(names):
            path = directory / name
            archive_path = path.relative_to(root)
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                omitted_links.append(archive_path.as_posix())
                continue
            if path.resolve() == database or excluded_file(path, full):
                continue
            if relative == Path(".") and not full and not (
                path.suffix.lower() in ROOT_SUFFIXES or name in {".gitignore", ".env.example"}
            ):
                continue
            if archive_path.as_posix() == "BACKUP_MANIFEST.json":
                continue
            files.append((path, archive_path.as_posix()))
    return files, omitted_links


def add_file(archive: zipfile.ZipFile, source: Path, name: str) -> dict:
    before = source.stat()
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as stream, archive.open(name, "w", force_zip64=True) as target:
        while chunk := stream.read(1024 * 1024):
            target.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or size != before.st_size:
        raise BackupError(f"Source changed during backup: {source}. Retry after edits finish.")
    return {"path": name, "bytes": size, "sha256": digest.hexdigest()}


def verify_archive(path: Path) -> dict:
    """Check ZIP CRC and every manifest SHA-256 before publishing or restoring."""
    with zipfile.ZipFile(path) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise BackupError(f"ZIP checksum failed: {corrupt}")
        manifest = json.loads(archive.read("BACKUP_MANIFEST.json"))
        if not isinstance(manifest, dict) or manifest.get("format") != "daycraft-backup-v1":
            raise BackupError("Unknown backup manifest format.")
        records = manifest.get("files")
        if not isinstance(records, list) or not all(
            isinstance(item, dict) and isinstance(item.get("path"), str)
            and isinstance(item.get("sha256"), str) and isinstance(item.get("bytes"), int)
            for item in records
        ):
            raise BackupError("Invalid backup file manifest.")
        names = archive.namelist()
        expected = [item["path"] for item in manifest["files"]]
        if (len(names) != len(set(names)) or len(expected) != len(set(expected))
                or set(names) != set(expected) | {"BACKUP_MANIFEST.json"}):
            raise BackupError("Archive members do not match its manifest.")
        for item in manifest["files"]:
            digest = hashlib.sha256()
            size = 0
            with archive.open(item["path"]) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            if digest.hexdigest() != item["sha256"] or size != item["bytes"]:
                raise BackupError(f"Archive content hash failed: {item['path']}")
    return manifest


def create_backup(root: Path = ROOT, *, database: Path | None = None,
                  output: Path | None = None, full: bool = False, timeout: float = 30) -> Path:
    root = root.resolve()
    database = database.resolve() if database is not None else configured_database(root)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    kind = "full-environment" if full else "source-data"
    output = (output or root / "data" / "backups" /
              f"daycraft-{kind}-{stamp}-{uuid.uuid4().hex[:8]}.zip").resolve()
    if output.exists():
        raise BackupError(f"Output already exists; it will not be overwritten: {output}")
    if output.suffix.lower() != ".zip":
        raise BackupError("Output must have a .zip extension.")
    if not database.is_file():
        raise BackupError(f"Personal database does not exist: {database}")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Same-volume staging allows atomic, fail-if-exists hard-link publication.
    with tempfile.TemporaryDirectory(prefix=".daycraft-backup-", dir=output.parent) as scratch:
        temporary = Path(scratch)
        snapshot = temporary / "snapshot.db"
        db_info = snapshot_database(database, snapshot, timeout)
        files, omitted_links = source_files(root, full, database)
        staged = temporary / "archive.partial"
        manifest = {
            "format": "daycraft-backup-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
            "kind": kind, "source_root": str(root), "database": db_info,
            "contains_sensitive_environment": full,
            "source_consistency": "Source files checked for changes while copied; source tree is not transactional.",
            "excluded": {"runtime_and_data_directories": sorted(ALWAYS_EXCLUDED),
                         "root_runtime_and_data_directories": sorted(ROOT_EXCLUDED),
                         "reinstallable_directories": [] if full else sorted(REINSTALLABLE),
                         "raw_databases_journals_logs_archives": True,
                         "dotenv_and_private_key_files": not full,
                         "known_credential_filenames": [] if full else sorted(SECRET_FILENAMES),
                         "configured_runtime_directory": str((root / Path(configured_value(root, "SCHEDULE_BUILDER_RUNTIME_DIR") or "logs/runtime")).resolve()),
                         "unlisted_root_directories": not full, "links": omitted_links},
            "recovery": "Extract into a NEW folder. Read docs/BACKUP.md. Stop all Daycraft processes before replacing any personal database.",
            "files": [],
        }
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                             allowZip64=True) as archive:
            for path, name in files:
                manifest["files"].append(add_file(archive, path, name))
            manifest["files"].append(add_file(archive, snapshot, "data/schedule_builder.db"))
            archive.writestr("BACKUP_MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
        verify_archive(staged)
        with staged.open("r+b") as handle:
            os.fsync(handle.fileno())
        try:
            # os.replace/rename can overwrite existing archives on some platforms.
            os.link(staged, output)
        except FileExistsError as exc:
            raise BackupError(f"Output appeared during backup; not overwritten: {output}") from exc
        except OSError as exc:
            raise BackupError("Could not publish archive without overwriting. Choose an NTFS/local "
                              f"destination supporting hard links: {exc}") from exc
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", help="Explicit personal SQLite path (overrides .env and process setting).")
    parser.add_argument("--output", type=Path, help="New ZIP path; existing files are never overwritten.")
    parser.add_argument("--full", action="store_true", help="Also include installed environments, .git and .env; private and much larger.")
    parser.add_argument("--timeout", type=float, default=30, help="Database snapshot timeout in seconds (default 30).")
    parser.add_argument("--verify", type=Path, help="Verify an existing archive without creating or restoring anything.")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        if args.verify:
            manifest = verify_archive(args.verify)
            print(f"Verified {args.verify}: {len(manifest['files'])} files; manifest hashes and ZIP checksums match.")
        else:
            output = create_backup(database=configured_database(ROOT, args.database), output=args.output,
                                   full=args.full, timeout=args.timeout)
            print(f"Backup created and verified: {output}")
            print("Contains personal data. Keep a copy on another device or trusted storage.")
        return 0
    except (BackupError, OSError, sqlite3.Error, zipfile.BadZipFile, KeyError, ValueError) as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
