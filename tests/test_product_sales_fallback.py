from __future__ import annotations

import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import price_monitor as prices, product_operations as ops
from tests.test_product_operations_rebuild import catalog, operational, financial


class SalesFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.latest = self.root / "sources"
        self.latest.mkdir()
        self.history = self.root / "sales_history"
        self.history.mkdir()
        pd.DataFrame([{"月份": "2026-10", "保存文件名": "2026-10.csv"}]).to_csv(self.root / "sales_history_records.csv", index=False)

    def write(self, latest_sku="SKU", write_latest=True):
        historical = [{"msku": "SKU", "asin": "A", "国家": country, **{f"10-{day:02d}销量": value for day in range(1, 32)}} for country, value in (("DE", 9), ("FR", 99))]
        pd.DataFrame(historical).to_csv(self.history / "2026-10.csv", index=False)
        if write_latest:
            row = {"msku": latest_sku, "asin": "A", "国家": "DE", **{f"10-{day:02d}销量": 2 for day in range(2, 32)}}
            row["10-10销量"] = None
            row["10-11销量"] = 0
            pd.DataFrame([row]).to_csv(self.latest / "sales_volume_detail.csv", index=False)
            pd.DataFrame([{"原始文件名": "销量_2026-10-02 ~ 2026-10-31.csv", "保存文件名": "sales_volume_detail.csv", "上传时间": "2026-11-01"}]).to_csv(self.latest / "sales_volume_detail_source.csv", index=False)

    def test_fill_missing_cells_from_same_market_history_and_keep_latest_zero(self):
        self.write()
        frame, as_of, warnings = prices.sales_trends(self.root, date(2026, 11, 1))
        row = frame.set_index("country").loc["DE"]
        self.assertEqual(as_of, "2026-10-31")
        self.assertEqual(warnings, [])
        self.assertEqual(row["units_30"], 65)
        self.assertEqual(row["units_7"], 14)
        self.assertEqual(row["units_30_source"], "销量明细＋往月销量")
        self.assertEqual(row["units_7_source"], "销量明细")

    def test_fill_identity_absent_in_latest_without_using_another_sku(self):
        self.write(latest_sku="OTHER")
        frame, _, _ = prices.sales_trends(self.root, date(2026, 11, 1))
        row = frame.loc[frame["sku"].eq("SKU") & frame["country"].eq("DE")].iloc[0]
        self.assertEqual(row["units_30"], 270)
        self.assertEqual(row["units_30_source"], "往月销量")

    def test_month_history_is_used_when_latest_source_is_absent(self):
        self.write(write_latest=False)
        frame, as_of, _ = prices.sales_trends(self.root, date(2026, 11, 1))
        self.assertEqual(as_of, "2026-10-31")
        self.assertEqual(frame.set_index("country").loc["DE", "units_30"], 270)

    def test_chart_and_window_calculation_use_the_same_cell_fallback(self):
        self.write()
        with patch("dashboard.derived_table_cache.DATA_DIR", self.root):
            series = ops._sku_series("fallback", "SKU", "A", "DE", 30, "2026-11-01", str(self.root))
        rows = {row["date"]: row["units"] for row in series["rows"]}
        self.assertEqual(rows["2026-10-10"], 9)
        self.assertEqual(rows["2026-10-11"], 0)
        self.assertEqual(sum(rows.values()), 65)

    def test_sku_reference_never_fills_or_counts_as_country_t(self):
        base = catalog([{**operational(), "7天销量": 70, "30天销量": 300}])
        frame = pd.DataFrame([{"sku": "SKU", "asin": "A", "country": country, "direction": "up", "date": "2026-11-01", "developer": "甲", "band": 5, "units_7": None, "units_30": None, "t_value": None, "abs_t": None, "trend": "missing"} for country in ("DE", "FR")])
        pricing = {"frame": frame, "as_of": "2026-11-16", "coverage": {"start": "2026-11-01", "end": "2026-11-17"}, "developers": ["甲"], "warnings": []}
        app = FastAPI(); app.include_router(ops.router)
        with patch.object(ops, "catalog_data", return_value=base), patch.object(prices, "base_data", return_value=pricing), TestClient(app) as client:
            data = client.get("/api/product-operations/prices").json()
            self.assertEqual(data["metrics"]["missing"], 2)
            self.assertEqual(data["metrics"]["sku_reference"], 2)
            self.assertIsNone(data["buckets"][0]["mean_t"])
            for row in data["rows"]:
                self.assertIsNone(row["t_value"])
                self.assertIsNone(row["units_7"])
                self.assertEqual(row["sku_units_7"], 70)
                self.assertEqual(row["sku_units_30"], 300)
                self.assertEqual(row["sku_t_value"], 0)
            response = client.get("/api/product-operations/prices/export.csv")
            exported = pd.read_csv(io.StringIO(response.content.decode("utf-8-sig")))
            self.assertEqual(len(exported), 2)
            self.assertTrue(exported["站点7天销量"].isna().all())
            self.assertEqual(exported["SKU汇总参考7天销量"].tolist(), [70, 70])

    def test_financial_fallback_requires_exact_period_country_and_preserves_zero(self):
        base = catalog(gross=[financial(asin="A", country="DE", units=300)])
        base["sources"]["gross_profit"].update(start="2026-10-18", end="2026-11-16")
        rows = [{"sku": "SKU", "asin": "A", "country": country, "direction": "up", "date": "2026-11-01", "developer": "甲", "band": 5, "units_7": 7, "units_30": None, "t_value": None, "abs_t": None, "trend": "missing"} for country in ("DE", "FR")]
        pricing = {"frame": pd.DataFrame(rows), "as_of": "2026-11-16", "coverage": {"start": "2026-11-01", "end": "2026-11-17"}, "developers": [], "warnings": []}
        with patch.object(ops, "catalog_data", return_value=base), patch.object(prices, "base_data", return_value=pricing):
            _, _, frame, _ = ops.price_frame()
            countries = frame.set_index("country")
            self.assertEqual(countries.loc["DE", "units_30"], 300)
            self.assertEqual(countries.loc["DE", "t_value"], -9)
            self.assertIn("毛利原始表", countries.loc["DE", "units_30_source"])
            self.assertTrue(pd.isna(countries.loc["FR", "units_30"]))
            self.assertTrue(pricing["frame"]["units_30"].isna().all())
            base["sources"]["gross_profit"]["start"] = "2026-10-17"
            self.assertTrue(ops.price_frame()[2]["units_30"].isna().all())
            base["sources"]["gross_profit"]["start"] = "2026-10-18"
            pricing["frame"].loc[pricing["frame"]["country"].eq("DE"), "units_30"] = 0
            self.assertEqual(ops.price_frame()[2].set_index("country").loc["DE", "units_30"], 0)
            pricing["frame"]["units_30"] = None
            base["markets"]["units"] = -1
            self.assertTrue(ops.price_frame()[2]["units_30"].isna().all())


if __name__ == "__main__":
    unittest.main()
