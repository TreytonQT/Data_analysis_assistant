from __future__ import annotations

import io
import unittest
from datetime import timedelta
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import product_operations as ops
from dashboard.data_processing import AVAILABLE_INVENTORY_STOCK_COLUMNS, build_replenishment_management_tables
from tests.test_product_operations_rebuild import TODAY, catalog, operational


def metric_row(sku="SKU", asin="A", age=90, **values):
    return {**operational(sku, asin), **dict.fromkeys(AVAILABLE_INVENTORY_STOCK_COLUMNS, 0),
            "可售": 10, "待调仓": 1, "调仓中": 2, "待入库": 3, "采购在途": 4, "本地库存": 5, "在途": 6, "计划入库": 7,
            "7天销量": 70, "14天销量": 28, "30天销量": 30,
            "上架时间": (TODAY - timedelta(days=age)).isoformat(), "单品重量(g)": 20, **values}


class ClearanceMetricsTests(unittest.TestCase):
    def test_89_90_day_weights_and_pending_inbound_twice(self):
        rows = [metric_row("NEW", age=89), metric_row("OLD", age=90)]
        facts = catalog(rows)["facts"].set_index("sku")
        self.assertAlmostEqual(facts.loc["NEW", "clearance_daily_units"], 9.19)
        self.assertAlmostEqual(facts.loc["OLD", "clearance_daily_units"], 6.7)
        self.assertEqual(facts.loc["NEW", "clearance_total_stock"], 41)
        self.assertAlmostEqual(facts.loc["NEW", "clearance_available_days"], 41 / 9.19)
        self.assertEqual(facts.loc["NEW", "daily_units"], 1)
        self.assertEqual(facts.loc["NEW", "coverage_days"], 10)

    def test_members_calibrate_before_sum_and_developer_duplicates_do_not_count(self):
        rows = [metric_row(age=89), metric_row(age=89, 开发员="乙"), metric_row(asin="B", age=90), metric_row("OTHER", asin="A", age=90)]
        base = catalog(rows)
        facts = base["facts"].set_index("sku")
        self.assertAlmostEqual(facts.loc["SKU", "clearance_daily_units"], 15.89)
        self.assertEqual(facts.loc["SKU", "clearance_total_stock"], 82)
        self.assertAlmostEqual(facts.loc["SKU", "clearance_available_days"], 82 / 15.89)
        self.assertAlmostEqual(facts.loc["OTHER", "clearance_daily_units"], 6.7)
        for scope in ("90", "180", "365"):
            selected = ops.queue_frame(base, age_scope=scope, developers="乙").iloc[0]
            self.assertAlmostEqual(selected["clearance_available_days"], 82 / 15.89)

    def test_full_sku_includes_stopped_store_but_clearance_funds_stay_excluded(self):
        rows = [metric_row(店铺名称="1-ZXU 德国"), metric_row(asin="B", 店铺名称="2-SGE 德国")]
        base = ops.build_catalog(pd.DataFrame(rows), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
                                 pd.DataFrame([{"店铺名": "SGE", "停提款时间": "2026-01"}]), TODAY)
        row = ops.queue_frame(base).iloc[0]
        self.assertEqual(row["scope_stock"], 150)
        self.assertEqual(row["clearance_total_stock"], 82)
        self.assertAlmostEqual(row["clearance_daily_units"], 13.4)

    def test_only_necessary_fields_and_no_partial_member_total(self):
        for missing in ("上架时间", "14天销量"):
            rows = [metric_row(), metric_row(asin="B", **{missing: None})]
            row = catalog(rows)["facts"].iloc[0]
            self.assertTrue(pd.isna(row["clearance_daily_units"]))
            self.assertTrue(pd.isna(row["clearance_available_days"]))
            self.assertEqual(row["clearance_total_stock"], 82)
        row = catalog([metric_row(待入库=None, **{"单品重量(g)": None})])["facts"].iloc[0]
        self.assertAlmostEqual(row["clearance_daily_units"], 6.7)
        self.assertTrue(pd.isna(row["clearance_total_stock"]))
        self.assertTrue(pd.isna(row["clearance_available_days"]))
        row = catalog([metric_row(**{"单品重量(g)": None})])["facts"].iloc[0]
        self.assertAlmostEqual(row["clearance_available_days"], 41 / 6.7)

    def test_zero_small_positive_and_future_date(self):
        row = catalog([metric_row(**{"7天销量": 0, "14天销量": 0, "30天销量": 0})])["facts"].iloc[0]
        self.assertEqual(row["clearance_daily_units"], 0)
        self.assertTrue(pd.isna(row["clearance_available_days"]))
        row = catalog([metric_row(**dict.fromkeys(AVAILABLE_INVENTORY_STOCK_COLUMNS, 0))])["facts"].iloc[0]
        self.assertEqual(row["clearance_available_days"], 0)
        row = catalog([metric_row(age=89, **{"7天销量": 0, "14天销量": 0, "30天销量": 1})])["facts"].iloc[0]
        self.assertAlmostEqual(row["clearance_available_days"], 123000)
        row = catalog([metric_row(age=-1)])["facts"].iloc[0]
        self.assertTrue(pd.isna(row["clearance_daily_units"]))

    def test_normal_data_matches_replenishment_sku_values(self):
        rows = [metric_row("NEW", age=89), metric_row("OLD", age=90)]
        original = pd.DataFrame(rows)
        replenishment = build_replenishment_management_tables(original, today=TODAY, only_needed=False)["sku_detail"].set_index("MSKU")
        facts = catalog(rows)["facts"].set_index("sku")
        for sku in ("NEW", "OLD"):
            self.assertAlmostEqual(facts.loc[sku, "clearance_daily_units"], replenishment.loc[sku, "校准日销量"])
            self.assertEqual(facts.loc[sku, "clearance_total_stock"], replenishment.loc[sku, "SKU总库存"])

    def test_sort_nulls_last_and_export_scope_units_and_selection(self):
        base = catalog([metric_row("FAST", age=89), metric_row("SLOW", age=90), metric_row("UNKNOWN", **{"上架时间": None})])
        app = FastAPI(); app.include_router(ops.router)
        with patch.object(ops, "catalog_data", return_value=base), TestClient(app) as client:
            data = client.get("/api/product-operations/workbench", params={"sort_by": "clearance_daily_units", "sort_order": "asc", "page_size": 1}).json()
            self.assertEqual(data["total"], 3)
            self.assertEqual(data["rows"][0]["sku"], "SLOW")
            desc = client.get("/api/product-operations/workbench?sort_by=clearance_daily_units&sort_order=desc").json()
            self.assertEqual([row["sku"] for row in desc["rows"]], ["FAST", "SLOW", "UNKNOWN"])
            for order, expected in (("asc", ["FAST", "SLOW", "UNKNOWN"]), ("desc", ["SLOW", "FAST", "UNKNOWN"])):
                days = client.get("/api/product-operations/workbench", params={"sort_by": "clearance_available_days", "sort_order": order}).json()
                self.assertEqual([row["sku"] for row in days["rows"]], expected)
            result = client.post("/api/product-operations/export.csv", json={"filters": {"sort_by": "clearance_available_days"}, "selected_skus": ["FAST"]})
            exported = pd.read_csv(io.StringIO(result.content.decode("utf-8-sig")))
            self.assertEqual(exported["SKU"].tolist(), ["FAST"])
            self.assertAlmostEqual(exported.iloc[0]["日均销量（补货口径，单/天）"], 9.19)
            self.assertEqual(exported.iloc[0]["补货口径总库存（件）"], 41)
            other = client.post("/api/product-operations/export.csv", json={"filters": {"scene": "new", "new_mode": "all"}})
            self.assertNotIn("补货口径总库存", other.content.decode("utf-8-sig"))

    def test_sort_keeps_precision_beyond_the_display_and_original_row_index(self):
        rows = [metric_row(sku, **{"7天销量": value * 7, "14天销量": value * 14, "30天销量": value * 30})
                for sku, value in (("A-HIGH", 1.0002), ("Z-LOW", 1.0001))]
        base = ops.build_catalog(pd.DataFrame(rows, index=[9, 3]), *[pd.DataFrame() for _ in range(5)], TODAY)
        self.assertEqual(ops.queue_frame(base, sort_by="clearance_daily_units", sort_order="asc")["sku"].tolist(), ["Z-LOW", "A-HIGH"])


if __name__ == "__main__":
    unittest.main()
