from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app


class ConfigApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_lists_replenishment_rule_configs_with_canonical_columns(self):
        response = self.client.get("/api/configs")
        self.assertEqual(response.status_code, 200)
        configs = {item["name"]: item for item in response.json()["configs"]}
        self.assertEqual(len(configs), 8)
        self.assertEqual(configs["store_config"]["columns"], ["店铺名", "店铺类型", "停提款时间", "店铺所属部门"])
        self.assertEqual(configs["replenishment_coverage_rules"]["columns"], ["运输方式", "重量下限", "重量上限", "头程时效", "预警天数", "补货频次", "是否启用"])
        self.assertNotIn("replenishment_group_exceptions", configs)
        self.assertNotIn("replenishment_column_order", configs)
        self.assertEqual(configs["replenishment_switches"]["columns"], ["ASIN", "是否补货", "关闭原因"])
        self.assertEqual(configs["replenishment_product_tags"]["columns"], ["ASIN", "产品标签", "标签颜色", "是否启用", "备注"])
        self.assertEqual(self.client.get("/api/config/replenishment_group_exceptions").status_code, 404)
        self.assertEqual(self.client.get("/api/config/replenishment_column_order").status_code, 404)

    def test_saves_and_normalizes_store_config(self):
        with tempfile.TemporaryDirectory() as directory, patch("backend.config_api.CONFIG_DIR", Path(directory)):
            response = self.client.put(
                "/api/config/store_config",
                json=[{"店铺名": " TEST ", "店铺类型": "中企", "停提款时间": "2026年7月", "店铺所属部门": "测试部"}],
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["rows"][0]["停提款时间"], "2026-07")
            self.assertTrue((Path(directory) / "store_config.csv").exists())

    def test_rejects_unknown_config(self):
        self.assertEqual(self.client.get("/api/config/not_allowed").status_code, 404)

    def test_rejects_invalid_operational_source_before_saving(self):
        response = self.client.post(
            "/api/reports/source/operational_sales",
            files={"file": ("invalid.csv", b"wrong,column\n1,2\n", "text/csv")},
        )
        self.assertEqual(response.status_code, 422)

    def test_rejects_overlapping_replenishment_coverage_rules(self):
        response = self.client.put(
            "/api/config/replenishment_coverage_rules",
            json=[
                {"运输方式": "空运", "重量下限": 0, "重量上限": 100, "头程时效": 30, "预警天数": 40, "补货频次": 10, "是否启用": "是"},
                {"运输方式": "卡航", "重量下限": 99, "重量上限": "", "头程时效": 40, "预警天数": 40, "补货频次": 10, "是否启用": "是"},
            ],
        )
        self.assertEqual(response.status_code, 422)

    def test_saves_asin_product_tags_and_rejects_invalid_colors(self):
        with tempfile.TemporaryDirectory() as directory, patch("backend.config_api.CONFIG_DIR", Path(directory)):
            saved = self.client.put(
                "/api/config/replenishment_product_tags",
                json=[{"ASIN": " B001 ", "产品标签": " 爆款 ", "标签颜色": "#16A34A", "是否启用": "是", "备注": "重点"}],
            )
            invalid = self.client.put(
                "/api/config/replenishment_product_tags",
                json=[{"ASIN": "B002", "产品标签": "季节品", "标签颜色": "green", "是否启用": "是", "备注": ""}],
            )

        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["rows"][0]["产品标签"], "爆款")
        self.assertEqual(invalid.status_code, 422)

    def test_replenishment_switch_config_requires_reason_and_writes_asin_schema(self):
        with tempfile.TemporaryDirectory() as directory, patch("backend.config_api.CONFIG_DIR", Path(directory)):
            invalid = self.client.put(
                "/api/config/replenishment_switches",
                json=[{"ASIN": "B001", "是否补货": "否", "关闭原因": ""}],
            )
            saved = self.client.put(
                "/api/config/replenishment_switches",
                json=[{"补货组ID": " b001 ", "是否补货": "否", "关闭原因": "停售"}],
            )

            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()["rows"], [{"ASIN": "B001", "是否补货": False, "关闭原因": "停售"}])
            header = (Path(directory) / "replenishment_switches.csv").read_text(encoding="utf-8-sig").splitlines()[0]
            self.assertEqual(header, "ASIN,是否补货,关闭原因")


if __name__ == "__main__":
    unittest.main()
