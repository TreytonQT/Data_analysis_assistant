from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app


class ReportsSafetyApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_exact_duplicate_sales_detail_is_preserved_and_ignored_for_calculation(self):
        content = (
            "msku,店铺,开发专员,07-15销量\n"
            "A,6-ZXU 德国,运营六部-甲,2\n"
            "A,6-ZXU 德国,运营六部-甲,2\n"
        ).encode("utf-8-sig")
        with (
            patch("backend.reports_api.persist_latest_source", return_value=Path("volume.csv")) as persist,
            patch("backend.reports_api._invalidate_dashboard_cache"),
            patch("backend.reports_api._warm_source_cache"),
        ):
            response = self.client.post(
                "/api/reports/source/sales_volume_detail",
                files={"file": ("volume.csv", content, "text/csv")},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["rows"], 2)
        self.assertEqual(payload["effective_rows"], 1)
        self.assertEqual(payload["duplicate_rows_ignored"], 1)
        self.assertIn("计算时会自动去重", payload["warnings"][0])
        persist.assert_called_once()

    def test_bad_non_empty_numeric_value_is_rejected_before_persisting(self):
        content = "ASIN,国家,Rating总数,评分\nA,德国,坏值,4.5\n".encode("utf-8-sig")
        with patch("backend.reports_api.persist_latest_source") as persist:
            response = self.client.post(
                "/api/reports/source/rating",
                files={"file": ("rating.csv", content, "text/csv")},
            )
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "invalid_numeric_values")
        self.assertEqual(detail["examples"][0]["column"], "Rating总数")
        persist.assert_not_called()

    def test_sku_image_map_rejects_non_https_before_persisting(self):
        content = (
            "库存SKU,虚拟SKU,库存图片链接\n"
            "LOCAL-1,SKU-1,http://cdn.example.com/1.jpg\n"
        ).encode("utf-8-sig")
        with patch("backend.reports_api.persist_latest_source") as persist:
            response = self.client.post(
                "/api/reports/source/sku_image_map",
                files={"file": ("images.csv", content, "text/csv")},
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn("HTTPS", response.json()["detail"])
        persist.assert_not_called()

    def test_sku_image_map_merges_exact_duplicates_and_keeps_latest_source_only(self):
        content = (
            "库存SKU,虚拟SKU,库存图片链接\n"
            "LOCAL-1,SKU-1,https://cdn.example.com/1.jpg\n"
            "LOCAL-1,SKU-1,https://cdn.example.com/1.jpg\n"
        ).encode("utf-8-sig")
        with (
            patch("backend.reports_api.persist_latest_source", return_value=Path("sku_image_map.xlsx")) as persist,
            patch("backend.reports_api.get_latest_source_path", return_value=None),
            patch("backend.reports_api._invalidate_dashboard_cache"),
            patch("backend.reports_api._warm_source_cache"),
        ):
            response = self.client.post(
                "/api/reports/source/sku_image_map",
                files={"file": ("images.csv", content, "text/csv")},
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["rows"], 2)
        self.assertEqual(payload["effective_rows"], 1)
        self.assertEqual(payload["duplicate_rows_ignored"], 1)
        self.assertIn("已合并", payload["warnings"][0])
        persist.assert_called_once()

    def test_sku_image_map_skips_empty_image_urls_with_warning(self):
        content = (
            "库存SKU,虚拟sku,库存图片链接\n"
            "LOCAL-1,SKU-1,\n"
            "LOCAL-2,SKU-2,https://cdn.example.com/2.jpg\n"
        ).encode("utf-8-sig")
        with (
            patch("backend.reports_api.persist_latest_source", return_value=Path("sku_image_map.csv")) as persist,
            patch("backend.reports_api.get_latest_source_path", return_value=None),
            patch("backend.reports_api._invalidate_dashboard_cache"),
            patch("backend.reports_api._warm_source_cache"),
        ):
            response = self.client.post(
                "/api/reports/source/sku_image_map",
                files={"file": ("images.csv", content, "text/csv")},
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["rows"], 2)
        self.assertEqual(payload["effective_rows"], 1)
        self.assertEqual(payload["duplicate_rows_ignored"], 0)
        self.assertIn("跳过", "；".join(payload["warnings"]))
        persist.assert_called_once()


if __name__ == "__main__":
    unittest.main()
