from __future__ import annotations

import gzip
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from backend.dashboard_api import clear_dashboard_caches
from backend.main import app


PAGES = ("overview", "sales", "slow-moving", "products", "department", "replenishment")


def request_ms(client: TestClient, path: str):
    started = time.perf_counter()
    response = client.get(path)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    return response, elapsed_ms


def main() -> None:
    client = TestClient(app)
    print("page            cold_ms   hot_avg   hot_max  response_kb")
    for page in PAGES:
        clear_dashboard_caches()
        response, cold_ms = request_ms(client, f"/api/dashboard/{page}")
        hot_samples = [request_ms(client, f"/api/dashboard/{page}")[1] for _ in range(5)]
        print(
            f"{page:14} {cold_ms:9.1f} {statistics.mean(hot_samples):9.1f} "
            f"{max(hot_samples):9.1f} {len(response.content) / 1024:12.1f}"
        )

    request_ms(client, "/api/dashboard/products")
    detail, detail_ms = request_ms(client, "/api/dashboard/products/sections/detail?page=1&page_size=50")
    print(
        f"products/detail first page: {detail_ms:.1f}ms, "
        f"{len(detail.content) / 1024:.1f}KB, total={detail.json()['total']}"
    )

    dist_assets = ROOT / "frontend" / "dist" / "assets"
    javascript = sorted(dist_assets.glob("*.js")) if dist_assets.exists() else []
    if javascript:
        raw_bytes = sum(path.stat().st_size for path in javascript)
        gzip_bytes = sum(len(gzip.compress(path.read_bytes(), compresslevel=9)) for path in javascript)
        print(f"all JS chunks: raw={raw_bytes / 1024:.1f}KB, gzip={gzip_bytes / 1024:.1f}KB")


if __name__ == "__main__":
    main()
