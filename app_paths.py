from __future__ import annotations

import os
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent

if getattr(sys, "frozen", False):
    APP_ROOT = Path(sys.executable).resolve().parent
    RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT)).resolve()
else:
    APP_ROOT = SOURCE_ROOT
    RESOURCE_ROOT = SOURCE_ROOT


def _configured_path(variable: str, default: Path) -> Path:
    configured = os.environ.get(variable, "").strip()
    return Path(configured).expanduser().resolve() if configured else default


DATA_DIR = _configured_path("DATA_ANALYSIS_ASSISTANT_DATA_DIR", APP_ROOT / "data")
CONFIG_DIR = _configured_path("DATA_ANALYSIS_ASSISTANT_CONFIG_DIR", APP_ROOT / "configs")
FRONTEND_DIST = RESOURCE_ROOT / "frontend" / "dist"
RUNTIME_DIR = APP_ROOT / ".tmp"
