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

from backend import price_monitor as monitor
from backend.listing_prices import persist_listing_snapshot, load_listing_index
from backend.product_filters import filter_margin, filter_new_sales


class ProductFilterTests(unittest.TestCase):
    def test_margin_bands_boundaries_and_small_samples(self):
        frame = pd.DataFrame({"毛利率": [-.1, 0, .04999, .05, .12, .20, None], "销量": [1, 0, 4, 5, 10, 1, 0]})
        expected = {"negative": [0], "0-5": [1, 2], "5-12": [3], "12-20": [4], "20-plus": [5], "missing": [6]}
        for band, indices in expected.items():
            self.assertEqual(filter_margin(frame, band, 0).index.tolist(), indices)
        self.assertEqual(len(filter_margin(frame, "all", 0)), 7)
        self.assertEqual(filter_margin(frame, "negative,0-5,5-12,12-20", 5).index.tolist(), [3, 4])
        with self.assertRaises(ValueError):
            filter_margin(frame, "bad", 0)

    def test_new_sales_range_does_not_turn_missing_into_zero(self):
        frame = pd.DataFrame({"90天销量": [0, 4, 5, 9, 10, None]})
        self.assertEqual(filter_new_sales(frame, 5, 10).index.tolist(), [2, 3])
        self.assertEqual(filter_new_sales(frame, 0, 1).index.tolist(), [0])
        self.assertEqual(len(filter_new_sales(frame, None, None)), 6)
        with self.assertRaises(ValueError):
            filter_new_sales(frame, 10, 5)


def workbook(price: float, country="DE", currency="EUR") -> bytes:
    output = io.BytesIO()
    pd.DataFrame([["SKU", "ASIN", country, currency, price, 0, 0, price, price]], columns=[
        "MSKU", "ASIN", "国家", "币种", "售价(总价)", "运费", "积分", "价格", "优惠价",
    ]).to_excel(output, index=False)
    return output.getvalue()


class PriceMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = patch("dashboard.derived_table_cache.DATA_DIR", self.root)
        self.cache.start()
        self.addCleanup(self.cache.stop)
        monitor._base.cache_clear()

    def test_decimal_price_bucket_boundaries(self):
        for old, new, expected in [(100, 95, 5), (100, 105, 5), (100, 90, 10), (100, 104.99, 0), (100, 350, 250)]:
            self.assertEqual(monitor.price_band(old, new), expected)

    def test_retention_is_180_calendar_days_and_same_day_replaces(self):
        end = date(2026, 11, 17)
        for days in (180, 179, 0):
            day = end - timedelta(days=days)
            persist_listing_snapshot("Listing" + day.strftime("%Y%m%d") + ".xlsx", workbook(100), self.root)
        self.assertEqual(load_listing_index(self.root)["日期"].tolist(), [(end - timedelta(days=179)).isoformat(), end.isoformat()])
        persist_listing_snapshot("Listing20261117.xlsx", workbook(90), self.root)
        self.assertEqual(len(load_listing_index(self.root)), 2)

    def test_latest_change_selected_before_direction_and_date_filters(self):
        for day, price in [("20261101", 100), ("20261102", 95), ("20261103", 105)]:
            persist_listing_snapshot("Listing" + day + ".xlsx", workbook(price), self.root)
        base = monitor._base("test", str(self.root), "2026-11-17")
        self.assertEqual(len(base["events"]), 2)
        self.assertEqual(len(base["frame"]), 1)
        self.assertEqual(len(monitor.filtered(base, "down")), 0)
        self.assertEqual(len(monitor.filtered(base, "up", date_end="2026-11-02")), 0)
        with patch("backend.price_monitor.load_snapshot", side_effect=AssertionError("cached pairs should not reopen snapshots")):
            self.assertEqual(len(monitor._event_frame(self.root)), 2)

    def test_base_cache_reuses_sources_and_invalidates_same_day_replacement(self):
        persist_listing_snapshot("Listing20261101.xlsx", workbook(100), self.root)
        persist_listing_snapshot("Listing20261102.xlsx", workbook(95), self.root)
        with patch.object(monitor, "_event_frame", wraps=monitor._event_frame) as events:
            first = monitor.base_data(self.root)
            self.assertIs(first, monitor.base_data(self.root))
            self.assertEqual(events.call_count, 1)
            persist_listing_snapshot("Listing20261102.xlsx", workbook(90), self.root)
            updated = monitor.base_data(self.root)
            self.assertEqual(updated["frame"].iloc[0]["new_effective_price"], 90)
            self.assertEqual(events.call_count, 2)

    def test_currency_changes_are_not_price_events(self):
        persist_listing_snapshot("Listing20261101.xlsx", workbook(100), self.root)
        persist_listing_snapshot("Listing20261102.xlsx", workbook(110, currency="USD"), self.root)
        self.assertTrue(monitor._event_frame(self.root).empty)

    def test_pair_cache_keeps_more_than_four_days_without_recovering_variants(self):
        start = date(2026, 11, 1)
        for i in range(8):
            day = start + timedelta(days=i)
            persist_listing_snapshot("Listing" + day.strftime("%Y%m%d") + ".xlsx", workbook(100 + i), self.root)
            normalized = self.root / "listing_prices" / (day.isoformat() + ".csv")
            frame = pd.read_csv(normalized).drop(columns=["父ASIN", "变体属性", "Rating总数", "评分"])
            frame.to_csv(normalized, index=False, encoding="utf-8-sig")
        with patch.object(monitor, "load_snapshot", side_effect=AssertionError("price observations must not recover variant fields")):
            self.assertEqual(len(monitor._event_frame(self.root)), 7)
        with patch.object(monitor, "_price_snapshot", side_effect=AssertionError("retained pair cache should be reused")):
            self.assertEqual(len(monitor._event_frame(self.root)), 7)

    def test_sales_are_exact_country_sum_shops_dedup_rows_and_preserve_missing(self):
        end = date(2026, 11, 16)
        rows = []
        for country, shop, units in [("DE", "A", 1), ("DE", "B", 2), ("FR", "A", 9)]:
            row = {"msku": "SKU", "asin": "ASIN", "国家": country, "店铺": shop}
            row.update({(end - timedelta(days=i)).strftime("%m-%d") + "销量": units for i in range(30)})
            rows.append(row)
        source = self.root / "sources"
        source.mkdir()
        pd.DataFrame([*rows, rows[0]]).to_csv(source / "sales_volume_detail.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame([{"数据源": "销量明细", "原始文件名": "销量_2026-10-18 ~ 2026-11-16.csv", "保存文件名": "sales_volume_detail.csv", "上传时间": "2026-11-17 10:00:00", "文件大小": 1}]).to_csv(source / "sales_volume_detail_source.csv", index=False, encoding="utf-8-sig")
        trends, as_of, warnings = monitor.sales_trends(self.root, date(2026, 11, 17))
        self.assertEqual(as_of, "2026-11-16")
        self.assertEqual(warnings, [])
        by_country = trends.set_index("country")
        self.assertEqual(by_country.loc["DE", "units_30"], 90)
        self.assertEqual(by_country.loc["FR", "units_7"], 63)
        self.assertEqual(by_country.loc["DE", "t_value"], 0)
        rows[0]["11-16销量"] = None
        pd.DataFrame(rows).to_csv(source / "sales_volume_detail.csv", index=False, encoding="utf-8-sig")
        trends, _, _ = monitor.sales_trends(self.root, date(2026, 11, 17))
        self.assertTrue(pd.isna(trends.set_index("country").loc["DE", "t_value"]))

    def test_sales_cross_year_and_excludes_today(self):
        frame = pd.DataFrame([{"msku": "SKU", "asin": "ASIN", "国家": "DE", "12-31销量": 1, "01-01销量": 2}])
        dated = monitor._dated_sales(frame, date(2027, 1, 1))
        self.assertIn("2026-12-31", dated)
        self.assertIn("2027-01-01", dated)

    def test_monthly_history_fills_only_dates_outside_latest_export(self):
        source = self.root / "sources"; source.mkdir()
        end = date(2026, 11, 17)
        row = {"msku": "SKU", "asin": "ASIN", "国家": "DE"}
        row.update({(end - timedelta(days=i)).strftime("%m-%d") + "销量": 2 for i in range(30)})
        pd.DataFrame([row]).to_csv(source / "sales_volume_detail.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame([{"数据源": "销量明细", "原始文件名": "销量_2026-10-19 ~ 2026-11-17.csv", "保存文件名": "sales_volume_detail.csv", "上传时间": "2026-11-17", "文件大小": 1}]).to_csv(source / "sales_volume_detail_source.csv", index=False, encoding="utf-8-sig")
        history = self.root / "sales_history"; history.mkdir()
        historical = {"msku": "SKU", "asin": "ASIN", "国家": "DE"}
        historical.update({f"10-{i:02d}销量": 9 for i in range(1, 32)})
        pd.DataFrame([historical]).to_csv(history / "2026-10.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame([{"月份": "2026-10", "保存文件名": "2026-10.csv"}]).to_csv(self.root / "sales_history_records.csv", index=False, encoding="utf-8-sig")
        trends, as_of, _ = monitor.sales_trends(self.root, end)
        self.assertEqual(as_of, "2026-11-16")
        self.assertEqual(trends.iloc[0]["units_30"], 67)
        self.assertEqual(trends.iloc[0]["units_7"], 14)

    def test_summary_sort_paging_export_and_validation(self):
        rows = []
        for sku, t in [("UP", 2), ("DOWN", -4), ("MISSING", None)]:
            rows.append({"sku": sku, "asin": "A", "country": "DE", "date": "2026-11-16", "direction": "up", "developer": "甲", "band": 5,
                         "t_value": t, "abs_t": abs(t) if t is not None else None, "trend": "missing" if t is None else "up" if t > 0 else "down"})
        base = {"frame": pd.DataFrame(rows), "events": pd.DataFrame(), "as_of": "2026-11-16", "coverage": {"start": "2026-11-01", "end": "2026-11-17"}, "developers": ["甲"], "warnings": []}
        app = FastAPI(); app.include_router(monitor.router)
        with patch("backend.price_monitor.base_data", return_value=base), TestClient(app) as client:
            data = client.get("/api/pricing/monitor?page_size=1").json()
            self.assertEqual(data["total"], 3)
            self.assertEqual(data["rows"][0]["sku"], "DOWN")
            self.assertEqual(data["buckets"][0]["up_ratio"], .5)
            self.assertEqual(data["metrics"]["missing"], 1)
            csv = client.get("/api/pricing/monitor/export.csv").content.decode("utf-8-sig")
            self.assertEqual(len(pd.read_csv(io.StringIO(csv))), 3)
            for query in ("sort_by=bad", "direction=bad", "country=US", "date_start=bad", "date_start=2026-11-17&date_end=2026-11-01"):
                self.assertEqual(client.get("/api/pricing/monitor?" + query).status_code, 422)

    def test_empty_base(self):
        base = monitor._base("empty", str(self.root), "2026-11-17")
        self.assertTrue(base["frame"].empty)
        self.assertTrue(monitor.filtered(base, "up").empty)


if __name__ == "__main__":
    unittest.main()
