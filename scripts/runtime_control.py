"""Instance-scoped local lifecycle control; never kills a process by PID."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CONTROL_PATH = "/_daycraft/runtime"


def path_identity(path):
    return hashlib.sha256(os.path.normcase(str(Path(path).resolve())).encode()).hexdigest()


def database_identity():
    return path_identity(os.environ.get("SCHEDULE_BUILDER_DB", ROOT / "data" / "schedule_builder.db"))


def state_directory():
    directory = Path(os.environ.get("SCHEDULE_BUILDER_RUNTIME_DIR") or "logs/runtime")
    return (ROOT / directory).resolve()


def request(port, method="GET", token=None, timeout=2):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(f"http://127.0.0.1:{port}{CONTROL_PATH}",
                                         method=method, headers=headers), timeout=timeout) as response:
        return json.load(response)


def stop_instance(port, instance=None, timeout=20):
    """Authenticate exact instance from disk and request graceful shutdown only."""
    path = state_directory() / f"{port}.json"
    if not path.is_file():
        raise RuntimeError(f"No managed instance record for port {port}; no process was stopped.")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("workspace") != path_identity(ROOT) or record.get("port") != port:
        raise RuntimeError("Runtime record belongs to a different workspace or port.")
    if instance and record.get("instance") != instance:
        raise RuntimeError("Runtime instance changed; refusing to stop its replacement.")
    public = {key: record[key] for key in ("workspace", "database", "instance", "pid", "port")}
    try:
        current = request(port)
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("Recorded instance is not reachable; no process was stopped.") from exc
    if any(current.get(key) != value for key, value in public.items()):
        raise RuntimeError("Listening instance does not match the runtime record; refusing shutdown.")
    result = request(port, "POST", record["token"])
    if result.get("instance") != record["instance"]:
        raise RuntimeError("Shutdown acknowledgement does not match the requested instance.")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if not path.exists() or json.loads(path.read_text(encoding="utf-8")).get("instance") != record["instance"]:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise RuntimeError("Graceful shutdown timed out; no forced termination was attempted.")


class ParentHandle:
    """Retain a Windows process object, checking creation time against PID reuse."""

    def __init__(self, pid, expected_start):
        if sys.platform != "win32":
            raise RuntimeError("Launcher parent monitoring requires Windows.")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        self.kernel.GetProcessTimes.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.OpenProcess(0x00100000 | 0x1000, False, pid)
        if not self.handle:
            raise RuntimeError("Launcher parent has exited or cannot be verified.")
        values = [wintypes.FILETIME() for _ in range(4)]
        if not self.kernel.GetProcessTimes(self.handle, *(ctypes.byref(value) for value in values)):
            self.close()
            raise RuntimeError("Cannot verify launcher parent creation time.")
        created = (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
        if expected_start is None or created != expected_start:
            self.close()
            raise RuntimeError("Launcher parent identity changed; refusing to start an orphan server.")

    def watch(self, server, finished):
        try:
            while not finished.is_set():
                result = self.kernel.WaitForSingleObject(self.handle, 250)
                if result != 258:
                    server.should_exit = True
                    return
        finally:
            self.close()

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class RuntimeControl:
    def __init__(self, app, server, port, instance):
        self.app = app
        self.server = server
        self.token = secrets.token_urlsafe(32)
        self.public = {"app": "schedule-builder", "workspace": path_identity(ROOT),
                       "database": database_identity(), "instance": instance,
                       "pid": os.getpid(), "port": port}
        self.path = state_directory() / f"{port}.json"

    def publish(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f".{self.public['instance']}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as file:
                os.chmod(temporary, 0o600)
                json.dump({**self.public, "token": self.token}, file)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def cleanup(self):
        # Windows can briefly deny unlink while stop clients or a scanner read it.
        for attempt in range(40):
            try:
                if json.loads(self.path.read_text(encoding="utf-8")).get("instance") == self.public["instance"]:
                    self.path.unlink()
                return
            except (FileNotFoundError, ValueError):
                return
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.05)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            async def lifecycle_send(message):
                if message["type"] == "lifespan.startup.complete":
                    self.publish()
                await send(message)
            return await self.app(scope, receive, lifecycle_send)
        if scope["type"] != "http" or scope["path"] != CONTROL_PATH:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        local = (scope.get("client") or (None,))[0] == "127.0.0.1"
        hosts = {f"127.0.0.1:{self.public['port']}".encode(), f"localhost:{self.public['port']}".encode()}
        permitted = (local and headers.get(b"host") in hosts and b"origin" not in headers
                     and headers.get(b"sec-fetch-site") not in {b"cross-site", b"same-site"})
        status = 200
        payload = self.public
        if not permitted:
            status, payload = 403, {"error": "Local lifecycle clients only"}
        elif scope["method"] == "POST":
            expected = f"Bearer {self.token}".encode()
            if not hmac.compare_digest(headers.get(b"authorization", b""), expected):
                status, payload = 403, {"error": "Invalid instance credential"}
            else:
                self.server.should_exit = True
                payload = {"status": "stopping", "instance": self.public["instance"]}
        elif scope["method"] != "GET":
            status, payload = 405, {"error": "Method not allowed"}
        body = json.dumps(payload).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})
