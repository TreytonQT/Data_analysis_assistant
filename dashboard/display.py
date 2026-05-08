from __future__ import annotations

from pathlib import Path


ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
SIDEBAR_BANNER_PATH = ASSETS_DIR / "sidebar-dashboard-banner.png"


def month_label(value) -> str:
    text = str(value)
    parts = text.split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]) % 100}年{int(parts[1])}月"
    return text
