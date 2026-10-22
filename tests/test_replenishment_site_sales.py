import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from backend import dashboard_api as api
from dashboard.data_processing import build_replenishment_site_sales_summary


class ReplenishmentSiteSalesTests(unittest.TestCase):
    def source(self):
        row = {"asin": " b001 ", "msku": "SKU1", "店铺": "A", "国家": "法国", "开发专员": "甲",
               "12-31销量": 2, "01-01销量": 3, "小计": 9999}
        return pd.DataFrame([row, row, {**row, "msku": "SKU2", "店铺": "B"},
                             {**row, "msku": "SKU3", "国家": "德国", "12-31销量": 0, "01-01销量": 0}])

    def metadata(self):
        return {"source": "sales_volume_detail", "available": True,
                "period_start": "2025-12-31", "period_end": "2026-01-01", "day_count": 2}

    def test_aggregate_all_skus_stores_deduplicate_and_keep_zero(self):
        summary, dates = build_replenishment_site_sales_summary(
            self.source(), period_start="2025-12-31", period_end="2026-01-01")
        self.assertEqual([day.strftime("%Y-%m-%d") for day in dates], ["2025-12-31", "2026-01-01"])
        self.assertEqual(summary.iloc[0]["ASIN"], "B001")
        self.assertEqual(summary.iloc[0]["销量明细FR销量"], 10)
        self.assertEqual(summary.iloc[0]["销量明细DE销量"], 0)
        self.assertEqual(summary.iloc[0]["销量明细IT销量"], 0)

    def test_filename_range_wins_over_upload_year_and_fallback_uses_upload_date(self):
        for name, upload in [("销量统计_2025-12-31 ~ 2026-01-01.csv", "2027-02-01"),
                             ("销量统计.csv", "2026-01-02")]:
            with self.subTest(name=name), patch.object(api, "get_latest_source_path", return_value=Path("source.csv")), \
                 patch.object(api, "load_latest_source_record", return_value=pd.DataFrame([{"原始文件名": name, "上传时间": upload}])), \
                 patch.object(api, "load_source_frame", return_value=self.source()):
                summary, metadata = api._replenishment_site_sales_source()
                self.assertEqual(metadata, self.metadata())
                self.assertEqual(summary.iloc[0]["销量明细FR销量"], 10)

    def test_missing_source_or_association_columns_is_unavailable(self):
        with patch.object(api, "get_latest_source_path", return_value=None):
            summary, metadata = api._replenishment_site_sales_source()
            self.assertTrue(summary.empty)
            self.assertFalse(metadata["available"])
        with patch.object(api, "get_latest_source_path", return_value=Path("source.csv")), \
             patch.object(api, "load_latest_source_record", return_value=pd.DataFrame()), \
             patch.object(api, "load_source_frame", return_value=self.source().drop(columns="asin")):
            summary, metadata = api._replenishment_site_sales_source()
            self.assertTrue(summary.empty)
            self.assertFalse(metadata["available"])

    def test_history_does_not_gate_site_sales_or_fall_back_to_old_totals(self):
        summary, _ = build_replenishment_site_sales_summary(self.source(), reference_date="2026-01-02")
        row = summary.iloc[0].to_dict()
        row.update({"补货组ID": "B001", "SKU数量": 3, "建议补货数量": 123})
        parent = api._replenishment_group_rows(pd.DataFrame([row]), site_sales_metadata=self.metadata())[0]
        self.assertFalse(parent["history"]["available"])
        self.assertEqual(parent["history"]["site_sales"], {"DE": 0, "FR": 10, "ES": 0, "IT": 0})
        self.assertEqual(parent["recommendation"]["official_quantity"], 123)
        tables = {"detail": pd.DataFrame([row]), "sku_detail": pd.DataFrame([{"补货组ID": "B001"}]),
                  "history": pd.DataFrame(), "site_sales_metadata": self.metadata()}
        with patch.object(api, "_replenishment_tables", return_value=tables):
            detail = api.replenishment_group_details("B001")
        # Detail and group history both retain the full monthly series.
        self.assertEqual(detail["sales_history"], parent["history"])
        missing = api._replenishment_history({"DE总销量": 999, "DE近30天销量": 888}, site_sales_metadata=self.metadata())
        self.assertTrue(all(value is None for value in missing["site_sales"].values()))

    def test_cache_dependency_tracks_file_and_index(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "volume.csv"
            index = Path(directory) / "volume_source.csv"
            source.touch()
            index.touch()
            with patch.object(api, "get_latest_source_path", side_effect=lambda key: source if key == "sales_volume_detail" else None), \
                 patch.object(api, "latest_source_index_path", return_value=index):
                paths = api._replenishment_base_paths()
                self.assertIn(source, paths)
                self.assertIn(index, paths)

    def test_history_exposes_full_chronological_months_without_ranked_replacement(self):
        row = {}
        for index in range(1, 13):
            row[f"历史月份{index}"] = f"2026-{index:02d}"
            row[f"历史{index}月总销量"] = 0 if index == 4 else index * 10
            row[f"历史{index}月计入天数"] = 30
            row[f"历史{index}月日均销量"] = 0 if index == 4 else index / 3
        history = api._replenishment_history(row)
        self.assertEqual(len(history["months"]), 12)
        self.assertEqual([item["month"] for item in history["months"]], [f"2026-{index:02d}" for index in range(1, 13)])
        self.assertEqual(history["months"][3]["total_sales"], 0)
        self.assertEqual(history["peak_months"][0]["month"], "2026-12")
        self.assertEqual(api._replenishment_history({})["months"], [])


if __name__ == "__main__":
    unittest.main()
