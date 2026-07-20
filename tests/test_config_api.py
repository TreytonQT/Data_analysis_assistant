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

    def test_lists_all_seven_configs_with_canonical_columns(self):
        response = self.client.get("/api/configs")
        self.assertEqual(response.status_code, 200)
        configs = {item["name"]: item for item in response.json()["configs"]}
        self.assertEqual(len(configs), 7)
        self.assertEqual(configs["store_config"]["columns"], ["店铺名", "店铺类型", "停提款时间", "店铺所属部门"])
        self.assertEqual(configs["replenishment_targets"]["columns"], ["ASIN", "目标可售天数", "箱规"])

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


if __name__ == "__main__":
    unittest.main()
