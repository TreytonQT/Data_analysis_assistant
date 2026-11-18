from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import product_operations as ops
from dashboard.data_processing import AGING_STOCK_COLUMNS, AGING_CAPITAL_COLUMNS, GROSS_PROFIT_REQUIRED_COLUMNS
from tests.test_product_operations import workbook
from backend.listing_prices import persist_listing_snapshot


TODAY = date(2026, 11, 17)


def operational(sku="SKU", asin="A", developer="甲", units=0, ages=(10, 20, 30, 40, 50)):
    return {"MSKU": sku, "ASIN": asin, "开发员": developer, "本地SKU名称": "测试中文产品", "店铺名称": "DE店铺", "可售": 100,
            "日均销量": 1, "7天销量": 1, "30天销量": 2, "90天销量": units,
            **dict(zip(AGING_STOCK_COLUMNS, ages)), **dict(zip(AGING_CAPITAL_COLUMNS, [v * 10 for v in ages]))}


def financial(sku="SKU", asin="A", country="DE", sales=100, profit=5, units=1):
    row = {column: 0 for column in GROSS_PROFIT_REQUIRED_COLUMNS}
    row.update({"MSKU": sku, "ASIN": asin, "国家": country, "毛利润": profit, "销售额--FBA销售额": sales, "销量--FBA销量": units})
    return row


def catalog(rows=None, gross=None, launches=None, listing=None):
    result = ops.build_catalog(pd.DataFrame(rows or [operational()]), pd.DataFrame(gross or []), pd.DataFrame(listing or []),
        pd.DataFrame(launches or []), pd.DataFrame(), pd.DataFrame(), TODAY)
    result.update(revision="test", sources={key: {"available": True} for key in ("operational_sales", "gross_profit", "listing", "sales_volume_detail")})
    return result


class CatalogTests(unittest.TestCase):
    def test_multiple_developers_asins_countries_do_not_multiply_inventory(self):
        base = catalog([operational(), operational(developer="乙"), operational(asin="B", ages=(1, 2, 3, 4, 5))],
            [financial(country=country, asin=asin) for country in ("DE", "FR") for asin in ("A", "B")])
        row = base["facts"].iloc[0]
        self.assertEqual(row["capital_90"], 1650)
        self.assertEqual(row["stock"], 200)
        self.assertEqual(row["developer"], "甲；乙")
        self.assertEqual(row["asins"], ["A", "B"])
        matched = ops.queue_frame(base, "margin").iloc[0]
        self.assertEqual(matched["matched_markets"], 4)
        self.assertEqual(matched["capital_90"], 1650)

    def test_age_scope_changes_stock_capital_and_membership(self):
        base = catalog([operational("YOUNGER", ages=(20, 0, 0, 0, 0)), operational("OLDER")])
        self.assertEqual(len(ops.queue_frame(base)), 2)
        for scope, stock, capital in (("180", 140, 1400), ("365", 90, 900)):
            frame = ops.queue_frame(base, age_scope=scope)
            self.assertEqual(frame["sku"].tolist(), ["OLDER"])
            self.assertEqual(frame.iloc[0]["scope_stock"], stock)
            self.assertEqual(frame.iloc[0]["scope_capital"], capital)
        self.assertEqual(base["facts"].set_index("sku").loc["OLDER", "capital_90"], 1500)

    def test_margin_disjoint_bands_and_weighted_profit(self):
        bands = [("N", -.01, "negative"), ("Z", 0, "0-5"), ("F", .05, "5-12"), ("T", .12, "12-20"), ("H", .20, "20-plus")]
        base = catalog([operational(sku) for sku, _, _ in bands], [financial(sku, profit=margin * 100) for sku, margin, _ in bands])
        for sku, _, band in bands:
            self.assertEqual(ops.queue_frame(base, "margin", margin_bands=band)["sku"].tolist(), [sku])
        self.assertEqual(len(ops.queue_frame(base, "margin")), 4)
        base = catalog(gross=[financial(sales=100, profit=10), {**financial(sales=900, profit=0), "店铺": "另一家"}])
        self.assertAlmostEqual(base["markets"].iloc[0]["margin"], .01)

    def test_missing_evidence_stays_unknown_and_can_be_filtered(self):
        base = catalog([operational(units=None)])
        self.assertTrue(pd.isna(base["facts"].iloc[0]["units_90"]))
        frame = ops.queue_frame(base, "margin", margin_bands="missing")
        self.assertEqual(len(frame), 1)
        self.assertTrue(pd.isna(frame.iloc[0]["matched_profit"]))
        self.assertTrue(pd.isna(frame.iloc[0]["matched_units"]))
        self.assertEqual(len(ops.queue_frame(base, "margin")), 0)

    def test_financial_blank_cells_keep_existing_source_zero_semantics(self):
        base = catalog(gross=[financial(profit=None, units=None)])
        row = base["markets"].iloc[0]
        self.assertEqual(row["profit"], 0)
        self.assertEqual(row["units"], 0)
        self.assertEqual(row["margin"], 0)

    def test_new_99_100_day_boundary_unknown_units_and_ranges(self):
        values = [("N99", 99, 0), ("N100", 100, 0), ("N6", 6, 4), ("N5", 5, 5), ("N9", 8, 9), ("N10", 8, 10), ("MISS", 9, None)]
        base = catalog([operational(sku, units=units) for sku, _, units in values], launches=[{"sku": sku, "arrival_date": (TODAY - timedelta(days=age)).isoformat()} for sku, age, _ in values])
        self.assertEqual(ops.queue_frame(base, "new")["sku"].tolist(), ["N99", "N6"])
        self.assertEqual(ops.queue_frame(base, "new", sales_min=5, sales_max=10)["sku"].tolist(), ["N5", "N9"])
        self.assertEqual(len(ops.queue_frame(base, "new", new_mode="all")), 6)
        self.assertEqual(ops.queue_frame(base, "new", sales_min=0, sales_max=1)["sku"].tolist(), ["N99"])

    def test_search_and_developer_match_unified_identity(self):
        base = catalog([operational(developer="甲"), operational(developer="乙")], gross=[financial(asin="FINANCIAL-ASIN")])
        self.assertEqual(len(ops.queue_frame(base, developers="乙", search="中文")), 1)
        self.assertEqual(len(ops.queue_frame(base, search="financial-asin")), 1)
        self.assertEqual(len(ops.queue_frame(base, developers="丙")), 0)

    def test_partial_stock_is_not_presented_as_complete_total(self):
        row = operational(); row[AGING_CAPITAL_COLUMNS[4]] = None
        base = catalog([row])
        frame = ops.queue_frame(base)
        self.assertTrue(pd.isna(frame.iloc[0]["scope_capital"]))
        self.assertIsNone(ops.workbench_payload(base, frame, "clearance", 1, 50)["summary"]["scope_capital"])

    def test_stopped_stores_only_affect_actionable_clearance_scope(self):
        rows = [{**operational("KEEP"), "店铺名称": "1-ZXU 德国"}, {**operational("STOP"), "店铺名称": "6-SGE 美国"}]
        base = ops.build_catalog(pd.DataFrame(rows), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame([{"店铺名": "SGE", "停提款时间": "2026-01"}]), TODAY)
        self.assertEqual(ops.queue_frame(base)["sku"].tolist(), ["KEEP"])
        self.assertEqual(base["facts"].set_index("sku").loc["STOP", "capital_90"], 1500)

    def test_small_samples_are_counted_per_market_and_invalid_sales_are_unknown(self):
        base = catalog([operational(units=-1)], [financial(country="DE", units=1), financial(country="FR", units=10)])
        row = ops.queue_frame(base, "margin").iloc[0]
        self.assertEqual(row["matched_units"], 11)
        self.assertEqual(row["small_sample_markets"], 1)
        self.assertTrue(pd.isna(row["units_90"]))

    def test_optional_sources_and_empty_catalog_are_supported(self):
        base = ops.build_catalog(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), TODAY)
        for scene in ("clearance", "margin", "new"):
            self.assertTrue(ops.queue_frame(base, scene).empty)

    def test_financial_only_sku_keeps_profit_evidence_and_unknown_inventory(self):
        base = ops.build_catalog(pd.DataFrame(), pd.DataFrame([financial()]), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), TODAY)
        row = ops.queue_frame(base, "margin").iloc[0]
        self.assertEqual(row["sku"], "SKU")
        self.assertEqual(row["matched_sales"], 100)
        self.assertTrue(pd.isna(row["stock"]))
        self.assertTrue(pd.isna(row["capital_90"]))


class OperationsApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI(); self.app.include_router(ops.router)
        self.client = TestClient(self.app)
        self.base = catalog([operational("ONE"), operational("TWO")], [financial("ONE", country="DE"), financial("ONE", country="FR")])
        self.patcher = patch.object(ops, "catalog_data", return_value=self.base); self.patcher.start(); self.addCleanup(self.patcher.stop)

    def test_export_one_sku_per_row_selected_and_current_filters(self):
        result = self.client.post("/api/product-operations/export.csv", json={"filters": {"scene": "clearance"}, "selected_skus": ["ONE"]})
        self.assertEqual(result.status_code, 200)
        frame = pd.read_csv(io.StringIO(result.content.decode("utf-8-sig")))
        self.assertEqual(frame["SKU"].tolist(), ["ONE"])
        self.assertEqual(frame.iloc[0]["90天以上占用资金（元）"], 1500)
        self.assertIn("DE毛利率（比例）", frame)
        empty = self.client.post("/api/product-operations/export.csv", json={"filters": {"search": "TWO"}, "selected_skus": ["ONE"]})
        self.assertTrue(pd.read_csv(io.StringIO(empty.content.decode("utf-8-sig"))).empty)

    def test_invalid_filters_have_same_query_and_export_error_status(self):
        for filters in ({"scene": "bad"}, {"age_scope": "99"}, {"sales_min": -1}, {"sales_min": 10, "sales_max": 5, "scene": "new"}, {"margin_bands": "bad", "scene": "margin"}, {"sort_by": "bad"}, {"country": "US"}):
            self.assertEqual(self.client.get("/api/product-operations/workbench", params=filters).status_code, 422)
            self.assertEqual(self.client.post("/api/product-operations/export.csv", json={"filters": filters}).status_code, 422)

    def test_export_refuses_a_stale_data_revision(self):
        response = self.client.post("/api/product-operations/export.csv", json={"filters": {"revision": "old-version"}, "selected_skus": ["ONE"]})
        self.assertEqual(response.status_code, 409)

    def test_detail_retains_manual_history_without_writing_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / "app.db"
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE price_adjustments (sku TEXT, reason TEXT, created_at TEXT)")
                conn.execute("INSERT INTO price_adjustments VALUES ('ｏｎｅ','历史','2026-11-01')")
            conn.close()
            before = path.read_bytes()
            with patch.object(ops, "DATA_DIR", root):
                result = self.client.get("/api/product-operations/skus/one").json()
            self.assertEqual(result["records"][0]["reason"], "历史")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(result["discard_90"], 150 * 6 + 1500 * 1.5)
            self.assertEqual(result["discard_reference"]["180"], 140 * 6 + 1400 * 1.5)
            self.assertEqual(result["discard_reference"]["365"], 90 * 6 + 900 * 1.5)

    def test_price_distribution_retains_other_bands_after_selection(self):
        rows = []
        for sku, band, t in (("ONE", 0, 1), ("ONE", 5, -3), ("TWO", 5, None)):
            rows.append({"sku": sku, "asin": sku + str(band), "country": "DE", "direction": "up", "date": "2026-11-10", "developer": "甲", "band": band, "change": .05, "t_value": t, "abs_t": abs(t) if t is not None else None, "trend": "missing" if t is None else "up" if t > 0 else "down"})
        base = {"frame": pd.DataFrame(rows), "as_of": "2026-11-16", "coverage": {"start": "2026-11-01", "end": "2026-11-17"}, "developers": ["甲"], "warnings": []}
        with patch.object(ops.prices, "base_data", return_value=base):
            data = self.client.get("/api/product-operations/prices?band=5").json()
            self.assertEqual([row["t_value"] for row in data["rows"]], [-3, None])
            self.assertEqual(data["distribution_total"], 3)
            self.assertEqual(data["metrics"]["sku_count"], 2)
            self.assertEqual(data["buckets"][1]["missing"], 1)
            self.assertEqual(self.client.get("/api/product-operations/prices?search=中文").json()["total"], 3)
            self.base["facts"].loc[self.base["facts"]["sku"].eq("ONE"), "developer"] = "乙"
            filtered = self.client.get("/api/product-operations/prices?developers=乙").json()
            self.assertEqual(filtered["total"], 2)
            self.assertTrue(all(row["sku"] == "ONE" for row in filtered["rows"]))

    def test_archived_market_and_removed_sku_still_open_exact_history(self):
        events = pd.DataFrame([{"sku": sku, "asin": "OLD-ASIN", "country": "IT", "date": "2026-11-01", "currency": "EUR"} for sku in ("ONE", "REMOVED")])
        with patch.object(ops.prices, "_event_frame", return_value=events):
            for sku in ("ONE", "REMOVED"):
                data = self.client.get("/api/product-operations/skus/" + sku).json()
                self.assertIn("OLD-ASIN", data["identity"]["asins"])
                row = next(row for row in data["markets"] if row["asin"] == "OLD-ASIN")
                self.assertEqual(row["country"], "IT")
                self.assertTrue(row["historical_only"])
                self.assertIsNone(row["current_price"])
                self.assertEqual(data["identity"]["stock"], 100 if sku == "ONE" else None)

    def test_series_exact_market_and_missing_dates_have_no_interpolation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("dashboard.derived_table_cache.DATA_DIR", root):
                persist_listing_snapshot("Listing20261101.xlsx", workbook(100), root)
                persist_listing_snapshot("Listing20261103.xlsx", workbook(95), root)
                with patch.object(ops, "read_source", return_value=pd.DataFrame()):
                    result = ops._sku_series("gaps", "SKU", "ASIN", "DE", 30, "2026-11-17", str(root))
                rows = {row["date"]: row for row in result["rows"]}
                self.assertEqual(rows["2026-11-01"]["price"], 100)
                self.assertIsNone(rows["2026-11-02"]["price"])
                self.assertTrue(rows["2026-11-03"]["event"])
                self.assertAlmostEqual(result["events"][0]["change"], -.05)
                self.assertEqual(result["events"][0]["observation"], "间隔2天，首次观察到")
                self.assertTrue(all(row["units"] is None for row in rows.values()))
                other = ops._sku_series("gaps", "SKU", "ASIN", "FR", 30, "2026-11-17", str(root))
                self.assertTrue(all(row["price"] is None for row in other["rows"]))


if __name__ == "__main__":
    unittest.main()
