"""Focused real-process lifecycle checks, confined to temporary databases/ports."""
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import runtime_control as runtime  # noqa: E402


def wait_for(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for isolated runtime")


@pytest.fixture
def managed(tmp_path, monkeypatch):
    database = tmp_path / "personal-copy.sqlite"
    monkeypatch.setenv("SCHEDULE_BUILDER_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("SCHEDULE_BUILDER_DB", str(database))
    monkeypatch.setenv("SCHEDULE_BUILDER_OFFLINE", "1")
    monkeypatch.setenv("SCHEDULE_BUILDER_ROUTE_CACHE", str(tmp_path / "routes.sqlite"))
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    log = (tmp_path / "server.log").open("w")
    process = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "serve.py"), "--port", str(port)],
                               cwd=ROOT, stdout=log, stderr=log)
    record_path = runtime.state_directory() / f"{port}.json"
    try:
        wait_for(lambda: record_path.exists() and runtime.request(port).get("pid"))
        record = json.loads(record_path.read_text())
        yield process, port, record_path, record, database
    finally:
        if process.poll() is None:
            # Restore only our exact record if a test deliberately made it stale.
            record_path.write_text(json.dumps(record), encoding="utf-8")
            runtime.stop_instance(port, record["instance"])
            process.wait(timeout=10)
        log.close()


def test_authenticated_stop_preserves_database_and_closes_wal(managed):
    process, port, record_path, record, database = managed
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute("CREATE TABLE lifecycle_marker (value TEXT)")
            connection.execute("INSERT INTO lifecycle_marker VALUES ('saved personal work')")
    result = subprocess.run(["cmd.exe", "/d", "/c", "Stop Daycraft.cmd", "--port", str(port)],
                            cwd=ROOT, capture_output=True, text=True, timeout=25,
                            env={**os.environ, "SCHEDULE_BUILDER_NONINTERACTIVE": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    process.wait(timeout=10)
    assert process.returncode == 0
    assert not record_path.exists()
    assert not database.with_name(database.name + "-wal").exists()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT value FROM lifecycle_marker").fetchone()[0] == "saved personal work"
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": "Bearer wrong"},
    {"Origin": "http://hostile.invalid"}, {"Sec-Fetch-Site": "cross-site"},
    {"Host": "hostile.invalid"},
])
def test_browser_and_unauthenticated_shutdown_rejected(managed, headers):
    process, port, _, record, _ = managed
    if "Origin" in headers or "Sec-Fetch-Site" in headers or "Host" in headers:
        headers["Authorization"] = f"Bearer {record['token']}"
    request = urllib.request.Request(f"http://127.0.0.1:{port}{runtime.CONTROL_PATH}", method="POST", headers=headers)
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2)
    assert error.value.code == 403
    assert process.poll() is None
    assert "token" not in runtime.request(port)


def test_stale_pid_instance_and_wrong_workspace_are_never_stopped(managed):
    process, port, record_path, record, _ = managed
    for changed in ({"pid": 1}, {"instance": "reused-instance"}, {"workspace": "other-project"}):
        record_path.write_text(json.dumps({**record, **changed}), encoding="utf-8")
        with pytest.raises(RuntimeError):
            runtime.stop_instance(port)
        assert process.poll() is None
    record_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(RuntimeError, match="replacement"):
        runtime.stop_instance(port, instance="old-instance")
    assert process.poll() is None


def test_occupied_port_does_not_migrate_or_overwrite_owner(managed, tmp_path):
    process, port, record_path, record, _ = managed
    other_database = tmp_path / "must-not-create.sqlite"
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "serve.py"), "--port", str(port)],
                            cwd=ROOT, env={**os.environ, "SCHEDULE_BUILDER_DB": str(other_database)},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert not other_database.exists()
    assert json.loads(record_path.read_text()) == record
    assert process.poll() is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows parent handle identity")
def test_reused_parent_pid_refused_before_database_open(tmp_path):
    database = tmp_path / "must-not-create.sqlite"
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "serve.py"),
                             "--parent", str(os.getpid()), "--parent-start", "1"],
                            cwd=ROOT, env={**os.environ, "SCHEDULE_BUILDER_DB": str(database)},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "parent identity changed" in result.stderr
    assert not database.exists()


def test_legacy_instance_refused_without_starting_duplicate(tmp_path):
    class LegacyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"app":"schedule-builder","status":"ok"}')

        def log_message(self, *_):
            pass

    legacy = ThreadingHTTPServer(("127.0.0.1", 0), LegacyHandler)
    thread = threading.Thread(target=legacy.serve_forever, daemon=True)
    thread.start()
    database = tmp_path / "must-not-create.sqlite"
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(ROOT / "scripts" / "launch.ps1"), "-NoBrowser", "-SmokeTest"],
                                cwd=ROOT, env={**os.environ, "SCHEDULE_BUILDER_DB": str(database),
                                              "SCHEDULE_BUILDER_PORT": str(legacy.server_port)},
                                capture_output=True, text=True, timeout=15)
        assert result.returncode != 0
        assert "Close its original launcher" in result.stdout
        assert not database.exists()
    finally:
        legacy.shutdown()
        legacy.server_close()
        thread.join(timeout=2)
