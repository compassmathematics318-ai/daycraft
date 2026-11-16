"""Gracefully stop authenticated Daycraft instances from this workspace."""
import argparse
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.runtime_control import state_directory, stop_instance  # noqa: E402


def main():
    # Match the launcher's safe .env precedence for runtime discovery only.
    dotenv = Path(__file__).resolve().parents[1] / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8-sig").splitlines():
            match = re.fullmatch(r"\s*SCHEDULE_BUILDER_RUNTIME_DIR\s*=\s*(.*?)\s*", line, re.IGNORECASE)
            if match:
                os.environ["SCHEDULE_BUILDER_RUNTIME_DIR"] = match[1].strip('"').strip("'")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int)
    parser.add_argument("--instance")
    args = parser.parse_args()
    if args.instance and args.port is None:
        parser.error("--instance requires --port")
    if args.port is not None and not 1024 <= args.port <= 65535:
        parser.error("Invalid localhost port")
    records = [state_directory() / f"{args.port}.json"] if args.port else sorted(state_directory().glob("*.json"))
    if not records:
        print("No managed Daycraft instances are recorded. No process was stopped.")
        return 0
    failed = False
    for record in records:
        try:
            port = int(record.stem)
            stop_instance(port, args.instance)
            print(f"Daycraft at 127.0.0.1:{port} stopped gracefully.")
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            print(f"{record.name}: {exc}", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
