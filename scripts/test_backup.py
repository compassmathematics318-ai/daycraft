"""Backup checks use only temporary databases and synthetic personal records."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile

import pytest

from backup import BackupError, configured_database, create_backup, verify_archive


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "source"
    (root / "data").mkdir(parents=True)
    (root / "frontend" / "dist").mkdir(parents=True)
    (root / "frontend" / "src").mkdir()
    (root / "frontend" / "src" / "App.tsx").write_text("export default 42")
    (root / "frontend" / "dist" / "index.html").write_text("compiled app")
    (root / "README.md").write_text("restore guide")
    database = root / "data" / "schedule_builder.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE personal (id INTEGER PRIMARY KEY, payload TEXT)")
        connection.execute("INSERT INTO personal VALUES (1, 'preserved task')")
        connection.commit()
    return root, database


def test_online_wal_snapshot_preserves_source_and_excludes_runtime(project, tmp_path):
    root, database = project
    for directory in ["logs", "data/backups", ".cache", "frontend/node_modules", ".venv", "test-results", ".codex"]:
        (root / directory).mkdir(parents=True, exist_ok=True)
        (root / directory / "omit.txt").write_text("runtime or sensitive")
    (root / ".env").write_text("API_KEY=private")
    (root / ".env.example").write_text("API_KEY=")
    (root / "frontend" / ".env.production").write_text("TOKEN=private")
    (root / "frontend" / ".npmrc").write_text("//example/:_authToken=private")
    (root / "frontend" / "other.db").write_bytes(b"not an online snapshot")
    (root / "frontend" / "other.db-wal").write_bytes(b"journal")
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO personal VALUES (2, 'committed WAL task')")
        connection.commit()
        assert Path(str(database) + "-wal").is_file()
        connection.execute("BEGIN")
        connection.execute("INSERT INTO personal VALUES (3, 'uncommitted task')")
        before = connection.execute("SELECT * FROM personal ORDER BY id").fetchall()
        original_bytes = hashlib.sha256(database.read_bytes()).hexdigest()
        archive_path = create_backup(root, database=database)
        assert connection.execute("SELECT * FROM personal ORDER BY id").fetchall() == before
        assert hashlib.sha256(database.read_bytes()).hexdigest() == original_bytes
        manifest = verify_archive(archive_path)
        assert manifest["database"]["table_counts"] == {"personal": 2}
        assert manifest["database"]["integrity_check"] == ["ok"]
        assert manifest["database"]["foreign_key_violations"] == 0
        with zipfile.ZipFile(archive_path) as archive:
            assert set(archive.namelist()) == {
                "README.md", ".env.example", "frontend/src/App.tsx", "frontend/dist/index.html",
                "data/schedule_builder.db", "BACKUP_MANIFEST.json",
            }
            restored = tmp_path / "restored.db"
            restored.write_bytes(archive.read("data/schedule_builder.db"))
        with closing(sqlite3.connect(restored)) as restored_connection:
            assert restored_connection.execute("SELECT * FROM personal ORDER BY id").fetchall() == before[:2]
            assert restored_connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        connection.rollback()


def test_existing_output_not_overwritten(project):
    root, database = project
    output = root / "keep.zip"
    output.write_bytes(b"existing archive")
    with pytest.raises(BackupError, match="not be overwritten"):
        create_backup(root, database=database, output=output)
    assert output.read_bytes() == b"existing archive"


def test_collision_at_publish_cannot_overwrite(project, monkeypatch):
    root, database = project
    output = root / "collision.zip"
    import backup
    original_link = backup.os.link

    def race(source, destination):
        destination.write_bytes(b"another backup won")
        original_link(source, destination)

    monkeypatch.setattr(backup.os, "link", race)
    with pytest.raises(BackupError, match="appeared during backup"):
        create_backup(root, database=database, output=output)
    assert output.read_bytes() == b"another backup won"
    assert not list(root.glob(".daycraft-backup-*"))


@pytest.mark.parametrize("failure", ["missing", "corrupt", "foreign-key"])
def test_invalid_database_never_publishes_or_creates_source(project, failure):
    root, database = project
    if failure == "missing":
        database.unlink()
    elif failure == "corrupt":
        database.write_bytes(b"not a database")
    else:
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE child (parent INTEGER REFERENCES personal(id))")
            connection.execute("INSERT INTO child VALUES (999)")
            connection.commit()
    output = root / "failed.zip"
    with pytest.raises((BackupError, sqlite3.DatabaseError)):
        create_backup(root, database=database, output=output)
    assert not output.exists()
    assert not list(root.glob(".daycraft-backup-*"))
    if failure == "missing":
        assert not database.exists()


def test_full_includes_environment_but_never_raw_data_runtime_or_archives(project):
    root, database = project
    for name in [".venv/installed.txt", "frontend/node_modules/library.js", ".git/config", ".cache/runtime/token", "data/backups/old.zip"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    (root / ".env").write_text("TOKEN=sensitive")
    (root / "older.zip").write_bytes(b"old full backup")
    output = create_backup(root, database=database, output=root / "full.zip", full=True)
    manifest = verify_archive(output)
    names = {item["path"] for item in manifest["files"]}
    assert {".venv/installed.txt", "frontend/node_modules/library.js", ".git/config", ".env"} <= names
    assert not any(name.startswith((".cache/", "data/backups/", ".daycraft-backup-")) for name in names)
    assert "older.zip" not in names
    assert manifest["contains_sensitive_environment"] is True


def test_database_selection_matches_launcher_dotenv_overrides_environment(project, monkeypatch):
    root, _database = project
    monkeypatch.setenv("SCHEDULE_BUILDER_DB", "from-environment.db")
    assert configured_database(root) == root / "from-environment.db"
    (root / ".env").write_text("# ignored\nSCHEDULE_BUILDER_DB='from dotenv.db'\n")
    assert configured_database(root) == root / "from dotenv.db"
    assert configured_database(root, "explicit.db") == root / "explicit.db"
    (root / ".env").write_text("schedule_builder_db=lowercase.db\n")
    assert configured_database(root) == root / "lowercase.db"


def test_manifest_detects_tampered_content(project):
    root, database = project
    output = create_backup(root, database=database)
    with zipfile.ZipFile(output) as original:
        files = {name: original.read(name) for name in original.namelist()}
    files["README.md"] = b"changed after backup"
    tampered = root / "tampered.zip"
    with zipfile.ZipFile(tampered, "w") as target:
        for name, payload in files.items():
            target.writestr(name, payload)
    with pytest.raises(BackupError, match="content hash failed"):
        verify_archive(tampered)


def test_cli_verifies_archive_and_fails_usefully(project, monkeypatch, capsys):
    root, database = project
    output = root / "cli.zip"
    script = Path(__file__).with_name("backup.py")
    import backup
    monkeypatch.setattr(backup, "ROOT", root)
    assert backup.main(["--database", str(database), "--output", str(output)]) == 0
    result = subprocess.run([sys.executable, str(script), "--verify", str(output)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert "Verified" in result.stdout
    assert backup.main(["--database", str(database), "--output", str(output)]) == 1
    assert "not be overwritten" in capsys.readouterr().err
    assert json.loads(zipfile.ZipFile(output).read("BACKUP_MANIFEST.json"))["format"] == "daycraft-backup-v1"


def test_custom_runtime_tokens_excluded_even_in_full(project):
    root, database = project
    runtime = root / "frontend" / "custom-runtime"
    runtime.mkdir()
    (runtime / "8765.json").write_text('{"token":"private"}')
    (root / ".env").write_text("SCHEDULE_BUILDER_RUNTIME_DIR=frontend/custom-runtime")
    output = create_backup(root, database=database, full=True)
    names = {item["path"] for item in verify_archive(output)["files"]}
    assert "frontend/custom-runtime/8765.json" not in names


def test_invalid_manifest_fails_without_traceback(tmp_path, capsys):
    import backup
    path = tmp_path / "malformed.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("BACKUP_MANIFEST.json", "[]")
    assert backup.main(["--verify", str(path)]) == 1
    assert "Unknown backup manifest format" in capsys.readouterr().err


def test_runtime_directory_cannot_expose_root_tokens(project):
    root, database = project
    (root / ".env").write_text("SCHEDULE_BUILDER_RUNTIME_DIR=.")
    (root / "8765.json").write_text('{"token":"private"}')
    with pytest.raises(BackupError, match="covers the source root"):
        create_backup(root, database=database)
    assert not list((root / "data" / "backups").glob("*.zip"))


def test_source_data_directory_is_not_confused_with_personal_data(project):
    root, database = project
    path = root / "frontend" / "src" / "data" / "constants.ts"
    path.parent.mkdir()
    path.write_text("export const example=42")
    output = create_backup(root, database=database)
    assert path.relative_to(root).as_posix() in {item["path"] for item in verify_archive(output)["files"]}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows entry point")
def test_windows_cmd_entrypoint_verifies_archive_without_pause(project):
    root, database = project
    output = create_backup(root, database=database)
    actual_root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "SCHEDULE_BUILDER_NONINTERACTIVE": "1"}
    result = subprocess.run(["cmd.exe", "/d", "/c", "Backup Daycraft.cmd", "--verify", str(output)],
                            cwd=actual_root, env=environment, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Verified" in result.stdout
