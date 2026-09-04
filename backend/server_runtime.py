from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol

import uvicorn

from app_paths import APP_ROOT, RUNTIME_DIR
from backend.main import app
from backend.system_control import SystemAction, system_controller


APP_HOST = "127.0.0.1"
APP_PORT = 8000
PID_FILE_NAME = "dashboard.pid"
STDOUT_LOG_NAME = "dashboard.stdout.log"
STDERR_LOG_NAME = "dashboard.stderr.log"


class RunnableServer(Protocol):
    def run(self) -> None: ...


def pid_file_path(runtime_dir: Path = RUNTIME_DIR) -> Path:
    return runtime_dir / PID_FILE_NAME


def write_runtime_pid(pid: int | None = None, runtime_dir: Path = RUNTIME_DIR) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pid_file_path(runtime_dir).write_text(f"{pid if pid is not None else os.getpid()}\n", encoding="ascii")


def clear_runtime_pid(pid: int | None = None, runtime_dir: Path = RUNTIME_DIR) -> None:
    target = pid_file_path(runtime_dir)
    if not target.exists():
        return
    if pid is not None:
        try:
            recorded = int(target.read_text(encoding="ascii").strip())
        except ValueError:
            recorded = None
        if recorded is not None and recorded != pid:
            return
    target.unlink(missing_ok=True)


def detached_flags(*, allow_breakaway: bool = True) -> int:
    flags = (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )
    if allow_breakaway:
        flags |= getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    return flags


def relaunch_process(
    runtime_dir: Path = RUNTIME_DIR,
    app_root: Path = APP_ROOT,
) -> subprocess.Popen[bytes]:
    """Start a detached replacement after the old socket has closed."""
    environment = os.environ.copy()
    environment["DATA_ANALYSIS_ASSISTANT_NO_BROWSER"] = "1"
    if getattr(sys, "frozen", False):
        args = [sys.executable]
    else:
        args = [sys.executable, "-m", "backend.server_runtime"]
    runtime_dir.mkdir(parents=True, exist_ok=True)
    with (runtime_dir / STDOUT_LOG_NAME).open("ab") as stdout, (runtime_dir / STDERR_LOG_NAME).open("ab") as stderr:
        kwargs = {
            "cwd": str(app_root),
            "env": environment,
            "stdin": subprocess.DEVNULL,
            "stdout": stdout,
            "stderr": stderr,
            "close_fds": False,
            "creationflags": detached_flags(),
        }
        try:
            return subprocess.Popen(args, **kwargs)
        except OSError:
            kwargs["creationflags"] = detached_flags(allow_breakaway=False)
            return subprocess.Popen(args, **kwargs)


def serve(server: RunnableServer) -> SystemAction | None:
    system_controller.bind(server)
    current_pid = os.getpid()
    write_runtime_pid(current_pid)
    action: SystemAction | None = None
    try:
        server.run()
    finally:
        action = system_controller.release(server)
        clear_runtime_pid(current_pid)
    return action


def run_server(host: str = APP_HOST, port: int = APP_PORT) -> int:
    config = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    action = serve(server)
    if action == "restart":
        relaunch_process()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_server())
