from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from backend import config_api
from backend.main import app


class ConfigSafetyApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_duplicate_business_keys_are_rejected_before_normalization(self) -> None:
        rows = [
            {"店铺名": " SHOP-1 ", "店铺类型": "中企", "停提款时间": "", "店铺所属部门": "一部"},
            {"店铺名": "SHOP-1", "店铺类型": "香港", "停提款时间": "", "店铺所属部门": "二部"},
        ]
        with tempfile.TemporaryDirectory() as directory, patch.object(config_api, "CONFIG_DIR", Path(directory)):
            response = self.client.put("/api/config/store_config", json=rows)

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("重复业务键", response.json()["detail"])

    def test_invalid_enabled_metric_formula_is_rejected_without_writing(self) -> None:
        row = {
            "指标名称": "危险指标",
            "显示分组": "总览",
            "公式": "__import__('os').system('echo unsafe')",
            "格式": "数值",
            "排序": 1,
            "是否启用": "是",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(config_api, "CONFIG_DIR", root):
                response = self.client.put("/api/config/metrics_config", json=[row])

            self.assertEqual(response.status_code, 422, response.text)
            self.assertIn("公式非法", response.json()["detail"])
            self.assertFalse((root / "metrics_config.csv").exists())

    def test_atomic_replace_failure_preserves_old_config_and_removes_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "store_config.csv"
            old_bytes = b"old,config\nkeep,me\n"
            destination.write_bytes(old_bytes)
            replacement = pd.DataFrame(
                [{"店铺名": "NEW", "店铺类型": "中企", "停提款时间": "", "店铺所属部门": "一部"}]
            )

            with (
                patch.object(config_api, "CONFIG_DIR", root),
                patch("backend.config_api.os.replace", side_effect=OSError("simulated replace failure")),
            ):
                with self.assertRaises(OSError):
                    config_api._atomic_write_config("store_config", replacement)

            self.assertEqual(destination.read_bytes(), old_bytes)
            self.assertEqual(list(root.glob(".store_config-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
