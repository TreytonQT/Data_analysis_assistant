"""Run a command with a hard deadline (including child processes)."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=85, choices=range(1, 91))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")
    process = subprocess.Popen(command, start_new_session=os.name != "nt")
    try:
        return process.wait(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False)
        else:
            import signal

            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        print(f"Command exceeded {args.timeout}s and was stopped: {command[0]}", file=sys.stderr)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
