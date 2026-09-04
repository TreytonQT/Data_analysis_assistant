from __future__ import annotations

import importlib
import socket
import subprocess
import time
import urllib.request
import webbrowser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
APP_URL = "http://127.0.0.1:8000"
HEALTH_URL = f"{APP_URL}/api/health"
RUNTIME_DIR = PROJECT_ROOT / ".tmp"
STDOUT_LOG = RUNTIME_DIR / "dashboard.stdout.log"
STDERR_LOG = RUNTIME_DIR / "dashboard.stderr.log"
PID_FILE = RUNTIME_DIR / "dashboard.pid"
LAUNCHER_LOG = RUNTIME_DIR / "dashboard-launcher.log"
REQUIRED_MODULES = ("fastapi", "uvicorn", "multipart", "pandas", "pyarrow", "openpyxl", "xlrd")


def report(message: str) -> None:
    """Record launcher progress without relying on a visible Python console."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LAUNCHER_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def dashboard_ready() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def port_in_use() -> bool:
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", 8000)) == 0


def dependencies_available() -> bool:
    try:
        for module in REQUIRED_MODULES:
            importlib.import_module(module)
        return True
    except ImportError:
        return False


def detached_flags() -> int:
    return (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    )


def spawn_server() -> subprocess.Popen[bytes]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.unlink(missing_ok=True)
    with STDOUT_LOG.open("wb") as stdout, STDERR_LOG.open("wb") as stderr:
        command = [str(SERVER_PYTHON), "-m", "backend.server_runtime"]
        kwargs = {
            "cwd": str(PROJECT_ROOT),
            "stdin": subprocess.DEVNULL,
            "stdout": stdout,
            "stderr": stderr,
            "close_fds": False,
            "creationflags": detached_flags(),
        }
        try:
            return subprocess.Popen(command, **kwargs)
        except OSError:
            # Codex may run inside a Windows job that does not permit breakaway.
            # The desktop shortcut is Explorer-owned, but keep a safe fallback.
            kwargs["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
            return subprocess.Popen(command, **kwargs)


def wait_for_health(timeout_seconds: float = 30) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if dashboard_ready():
            return True
        time.sleep(0.5)
    return False


def main() -> int:
    if dashboard_ready():
        webbrowser.open(APP_URL)
        return 0
    if not SERVER_PYTHON.exists():
        report(f"[ERROR] Background Python executable was not found: {SERVER_PYTHON}")
        report("Create it with: py -3.12 -m venv .venv")
        return 1
    if not (PROJECT_ROOT / "frontend" / "dist" / "index.html").exists():
        report("[ERROR] The React production build was not found at frontend\\dist\\index.html.")
        report("Run: cd frontend && npm.cmd ci && npm.cmd run build")
        return 1
    if not dependencies_available():
        report("[ERROR] Python dependencies are incomplete.")
        report("Run: .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        return 1
    if port_in_use():
        report("[ERROR] Port 8000 is already occupied by another process.")
        report("Inspect it with: netstat -ano | findstr :8000")
        return 1

    report(f"Starting the local dashboard at {APP_URL} ...")
    process = spawn_server()
    if not wait_for_health():
        process.terminate()
        report("[ERROR] The API did not become healthy within 30 seconds.")
        report(f"Logs: {STDOUT_LOG} and {STDERR_LOG}")
        return 1
    webbrowser.open(APP_URL)
    report("Dashboard is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
