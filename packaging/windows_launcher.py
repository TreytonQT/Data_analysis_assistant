from __future__ import annotations

import os
import socket
import threading
import time
import urllib.request
import webbrowser

from backend.server_runtime import run_server


APP_HOST = "127.0.0.1"
APP_PORT = int(os.environ.get("DATA_ANALYSIS_ASSISTANT_PORT", "8000"))
APP_URL = f"http://{APP_HOST}:{APP_PORT}"
HEALTH_URL = f"{APP_URL}/api/health"
OPEN_BROWSER = os.environ.get("DATA_ANALYSIS_ASSISTANT_NO_BROWSER") != "1"


def dashboard_ready() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def port_in_use() -> bool:
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex((APP_HOST, APP_PORT)) == 0


def open_browser_when_ready() -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if dashboard_ready():
            if OPEN_BROWSER:
                webbrowser.open(APP_URL)
            return
        time.sleep(0.5)
    print(f"启动超时，请检查窗口日志后手动访问：{APP_URL}")


def main() -> int:
    if dashboard_ready():
        if OPEN_BROWSER:
            webbrowser.open(APP_URL)
        return 0
    if port_in_use():
        print(f"端口 {APP_PORT} 已被其他程序占用，销售数据分析助手无法启动。")
        input("按回车键退出……")
        return 1

    print("销售数据分析助手正在启动……")
    print(f"就绪后会自动打开浏览器：{APP_URL}")
    print("使用完毕后，请关闭此窗口或按 Ctrl+C 停止程序。")
    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    run_server(host=APP_HOST, port=APP_PORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
