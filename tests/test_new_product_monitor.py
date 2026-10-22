from __future__ import annotations

import unittest
from datetime import date, timedelta

import pandas as pd

from dashboard.data_processing import build_new_product_monitor_table


class NewProductMonitorTests(unittest.TestCase):
    reference = date(2026, 10, 13)

    def build(self, items):
        operational = []
        launches = []
        for sku, asin, age, stock, average, developer in items:
            operational.append({
                "MSKU": sku,
                "ASIN": asin,
                "开发员": developer,
                "可售": stock,
                "日均销量": average,
                "昨天销量": 1,
                "前天销量": 0,
                "上前销量": 0,
                "7天销量": 7,
                "14天销量": 12,
                "30天销量": 20,
                "90天销量": 45,
            })
            if age is not None:
                launches.append({
                    "SKU": sku,
                    "开售时间": (self.reference - timedelta(days=age)).isoformat(),
                })
        return build_new_product_monitor_table(
            pd.DataFrame(operational),
            pd.DataFrame(launches, columns=["SKU", "开售时间"]),
            reference_date=self.reference,
        )

    def test_stock_cover_thresholds_and_zero_sales_boundary(self):
        rows = self.build([
            ("RAISE", "A1", 0, 4, 1, "甲"),
            ("FIVE", "A2", 1, 5, 1, "甲"),
            ("NINETY", "A3", 1, 90, 1, "乙"),
            ("LOWER", "A4", 1, 91, 1, "乙"),
            ("OBSERVE", "A5", 6, 20, 0, "丙"),
            ("ZERO-LOWER", "A6", 7, 20, 0, "丙"),
            ("OUT", "A7", 1, 0, 2, "丁"),
        ])
        by_sku = rows.set_index("SKU")
        self.assertEqual(by_sku.loc["RAISE", "监控状态"], "建议涨价")
        self.assertEqual(by_sku.loc["FIVE", "监控状态"], "正常")
        self.assertEqual(by_sku.loc["NINETY", "监控状态"], "正常")
        self.assertEqual(by_sku.loc["LOWER", "监控状态"], "建议降价")
        self.assertEqual(by_sku.loc["OBSERVE", "监控状态"], "新品观察中")
        self.assertEqual(by_sku.loc["ZERO-LOWER", "监控状态"], "建议降价")
        self.assertEqual(by_sku.loc["OUT", "监控状态"], "已断货")
        self.assertTrue(pd.isna(by_sku.loc["OBSERVE", "可售覆盖天数"]))

    def test_launch_window_includes_day_zero_and_day_one_hundred(self):
        rows = self.build([
            ("TODAY", "A1", 0, 1, 1, "甲"),
            ("DAY-7", "A2", 7, 1, 1, "甲"),
            ("DAY-100", "A3", 100, 100, 1, "甲"),
            ("DAY-101", "A4", 101, 100, 1, "甲"),
            ("FUTURE", "A5", -1, 1, 1, "甲"),
            ("NO-DATE", "A6", None, 1, 1, "甲"),
        ])
        self.assertEqual(set(rows["SKU"]), {"TODAY", "DAY-7", "DAY-100"})
        self.assertEqual(rows.attrs["excluded_invalid_launch_count"], 2)

    def test_missing_negative_and_conflicting_core_values_are_not_recommendations(self):
        rows = self.build([
            ("MISSING-AVG", "A1", 1, 1, None, "甲"),
            ("NEGATIVE-STOCK", "A2", 1, -1, 1, "甲"),
            ("CONFLICT", "A3", 1, 1, 1, "甲"),
            ("CONFLICT", "A4", 1, 2, 1, "乙"),
            ("NO-ASIN", "", 1, 1, 1, "丙"),
        ])
        by_sku = rows.set_index("SKU")
        self.assertEqual(by_sku.loc["MISSING-AVG", "监控状态"], "数据异常")
        self.assertEqual(by_sku.loc["NEGATIVE-STOCK", "监控状态"], "数据异常")
        self.assertEqual(by_sku.loc["CONFLICT", "监控状态"], "数据异常")
        self.assertEqual(by_sku.loc["NO-ASIN", "监控状态"], "数据异常")
        self.assertFalse(by_sku["监控状态"].isin(["建议涨价", "建议降价"]).any())

    def test_duplicate_sku_rows_are_summed_and_developers_are_merged(self):
        operational = pd.DataFrame([
            {"MSKU": " same ", "ASIN": "A1", "开发员": "甲", "可售": 2, "日均销量": 0.5},
            {"MSKU": "SAME", "ASIN": "A1", "开发员": "乙", "可售": 2, "日均销量": 0.5},
        ])
        launches = pd.DataFrame([{"SKU": "same", "开售时间": (self.reference - timedelta(days=1)).isoformat()}])
        rows = build_new_product_monitor_table(operational, launches, reference_date=self.reference)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.loc[0, "SKU"], "same")
        self.assertEqual(rows.loc[0, "开发员"], "乙；甲")
        self.assertEqual(rows.loc[0, "可售数量"], 4)
        self.assertEqual(rows.loc[0, "日均销量"], 1)
        self.assertEqual(rows.loc[0, "监控状态"], "建议涨价")

    def test_default_order_prioritizes_raise_then_zero_sales_and_longer_cover_lower(self):
        rows = self.build([
            ("RAISE-4", "A1", 1, 4, 1, "甲"),
            ("RAISE-2", "A2", 1, 2, 1, "甲"),
            ("LOWER-91", "A3", 1, 91, 1, "甲"),
            ("LOWER-120", "A4", 1, 120, 1, "甲"),
            ("ZERO-SALES", "A5", 7, 10, 0, "甲"),
            ("NORMAL", "A6", 1, 10, 1, "甲"),
        ])
        self.assertEqual(rows["SKU"].tolist(), [
            "RAISE-2", "RAISE-4", "ZERO-SALES", "LOWER-120", "LOWER-91", "NORMAL",
        ])


if __name__ == "__main__":
    unittest.main()