from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from backend.dashboard_api import dashboard_revision
from backend.promotions import promotion_revision
from backend.batch_monitor import batch_monitor_revision
from dashboard.data_processing import CONFIG_DIR
from dashboard.parquet_cache import revision_digest
from dashboard.report_store import DATA_DIR


router = APIRouter(prefix="/api", tags=["app-revisions"])


def _existing_paths(paths: list[Path]) -> list[Path]:
    return [path for path in paths if path.is_file()]


def config_revision() -> str:
    paths = sorted((path for path in CONFIG_DIR.glob("*.csv") if path.is_file()), key=str)
    return revision_digest("app-configs", paths) if paths else "empty"


def reports_revision() -> str:
    paths = [DATA_DIR / "upload_records.csv"]
    paths.extend((DATA_DIR / "reports").glob("*.csv"))
    paths.extend((DATA_DIR / "sources").glob("*_source.csv"))
    return revision_digest("app-reports", _existing_paths(paths))


@router.get("/app-revisions")
def app_revisions() -> dict[str, str]:
    """Return stable, domain-scoped revisions for client-side page reuse."""
    return {
        "dashboard": dashboard_revision(),
        "promotions": promotion_revision(),
        "reports": reports_revision(),
        "configs": config_revision(),
        "batch_monitor": batch_monitor_revision(),
    }
