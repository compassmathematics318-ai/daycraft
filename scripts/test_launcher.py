"""Windows launcher integration checks using an isolated temporary database.

Run after building the frontend: .venv\Scripts\python.exe scripts/test_launcher.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "test-results" / "launcher"


def health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
            return json.load(response).get("app") == "schedule-builder"
    except (OSError, urllib.error.URLError):
        return False


def wait_for(predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise AssertionError("Timed out waiting for launcher state")


def main():
    if os.name != "nt":
        raise SystemExit("Windows-only integration checks")
    assert (ROOT / "frontend" / "dist" / "index.html").is_file(), "Build the frontend first"
    RESULTS.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update(SCHEDULE_BUILDER_DB=str(RESULTS / "launcher.db"),
                       SCHEDULE_BUILDER_ROUTE_CACHE=str(RESULTS / "routes.sqlite"),
                       SCHEDULE_BUILDER_RUNTIME_DIR=str(RESULTS / "runtime"),
                       SCHEDULE_BUILDER_OFFLINE="1", SCHEDULE_BUILDER_NONINTERACTIVE="1")
    # Never assume the preferred testing port is free on the user's machine.
    base = next(port for port in range(9175, 9275, 2) if not health(port) and not health(port + 1))
    environment["SCHEDULE_BUILDER_PORT"] = str(base)
    command = ["cmd.exe", "/d", "/c", "Launch Schedule Builder.cmd", "-NoBrowser", "-SmokeTest"]

    def smoke(expected):
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=120)
        print(result.stdout)
        assert result.returncode == 0, result.stderr + result.stdout
        assert expected in result.stdout
        return result

    smoke(f"Workspace ready: http://127.0.0.1:{base}")
    wait_for(lambda: not health(base))
    print("PASS exact .cmd: dependency reuse, safe migration, health, compiled frontend, smoke cleanup")

    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", base))
        occupied.listen()
        smoke(f"Workspace ready: http://127.0.0.1:{base + 1}")
        wait_for(lambda: not health(base + 1))
    print("PASS occupied port selects the next port")

    output = RESULTS / "parent.out.log"
    errors = RESULTS / "parent.err.log"
    with output.open("w") as stdout, errors.open("w") as stderr:
        parent = subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                   str(ROOT / "scripts" / "launch.ps1"), "-NoBrowser"],
                                  cwd=ROOT, env=environment, stdout=stdout, stderr=stderr,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            wait_for(lambda: health(base))
            reused = smoke(f"already running at http://127.0.0.1:{base}")
            assert "Database migrations complete" not in reused.stdout, "Reuse must precede migration"
            assert health(base), "Reuse must not stop the original server"
            print("PASS second launch reuses the running instance")
            strict = subprocess.run(command + ["-RequireScheduler"], cwd=ROOT, env=environment,
                                    capture_output=True, text=True, timeout=40)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{base}/api/solver-health", timeout=20) as response:
                    operational = json.load(response)["status"] == "operational"
            except urllib.error.HTTPError:
                operational = False
            assert (strict.returncode == 0) == operational, strict.stdout + strict.stderr
            assert health(base), "Strict reuse must not stop the original server"
            print("PASS strict reuse reflects actual running solver health")
            parent.terminate()
            parent.wait(timeout=10)
            wait_for(lambda: not health(base), seconds=15)
            print("PASS server stops when launcher parent is terminated")
        finally:
            if parent.poll() is None:
                parent.terminate()
                parent.wait(timeout=10)
    print("All Windows launcher integration checks passed.")


if __name__ == "__main__":
    main()
