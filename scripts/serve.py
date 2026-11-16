"""Serve one Daycraft instance and shut down gracefully with its launcher."""
import argparse
from pathlib import Path
import socket
import sys
import threading
from uuid import UUID, uuid4

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.runtime_control import ParentHandle, RuntimeControl  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--parent", type=int)
    parser.add_argument("--parent-start", type=int)
    parser.add_argument("--instance", default=None)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    instance = UUID(args.instance).hex if args.instance else uuid4().hex
    parent = ParentHandle(args.parent, args.parent_start) if args.parent else None
    finished = threading.Event()
    watcher = None
    control = None
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Reserve the listener before startup can migrate data or publish state.
        if sys.platform == "win32":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", args.port))
        listener.listen(128)
        # Retain and verify the parent before importing/opening the database.
        from backend.app.main import app
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port,
                                              timeout_graceful_shutdown=15))
        control = RuntimeControl(app, server, args.port, instance)
        server.config.app = control
        if parent:
            watcher = threading.Thread(target=parent.watch, args=(server, finished), daemon=True)
            watcher.start()
        server.run(sockets=[listener])
    finally:
        finished.set()
        if watcher:
            watcher.join(timeout=2)
        elif parent:
            parent.close()
        if control:
            control.cleanup()
        listener.close()


if __name__ == "__main__":
    main()
