from __future__ import annotations

import unittest
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import dashboard_api


def build_bundle(*, developers=None, launch_stage="all", status="all", search=None):
    rows = []
    for index in range(60):
        rows.append({
            "SKU": f"SKU-{index:03d}",
            "ASIN": f"ASIN-{index:03d}",
            "开发员": "甲" if index % 2 == 0 else "乙",
            "开售时间": "2026-10-12",
            "开售天数": 1,
            "可售数量": index + 1,
            "日均销量": 1,
            "可售覆盖天数": index + 1,
            "昨天销量": 1,
            "7天销量": 7,
            "14天销量": 14,
            "30天销量": 30,
            "90天销量": 90,
            "监控状态": "建议涨价" if index % 2 == 0 else "建议降价",
            "提醒原因": "测试",
        })
    frame = pd.DataFrame(rows)
    if developers:
        frame = frame[frame["开发员"].isin(developers.split(","))]
    if launch_stage != "all":
        start, end = {"0-6": (0, 6), "7-29": (7, 29), "30-59": (30, 59), "60-100": (60, 100)}[launch_stage]
        frame = frame[frame["开售天数"].between(start, end)]
    if search:
        frame = frame[frame.astype(str).apply(lambda column: column.str.contains(search, case=False, regex=False)).any(axis=1)]
    copy_lists = {
        "raise_skus": frame.loc[frame["监控状态"].eq("建议涨价"), "SKU"].tolist(),
        "lower_skus": frame.loc[frame["监控状态"].eq("建议降价"), "SKU"].tolist(),
        "calculation_date": "2026-10-13",
    }
    if status != "all":
        label = {"raise": "建议涨价", "lower": "建议降价"}[status]
        frame = frame[frame["监控状态"].eq(label)]
    return {
        "title": "新品监控",
        "has_data": not frame.empty,
        "message": None,
        "filters": {"developers": ["甲", "乙"]},
        "selected": {},
        "metrics": [],
        "calculation_date": "2026-10-13",
        "copy_lists": copy_lists,
        "sections": [dashboard_api.section("detail", "新品监控明细", frame)],
    }


class NewProductDashboardApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()
        app.include_router(dashboard_api.router)
        cls.client = TestClient(app)

    def setUp(self):
        dashboard_api._cached_new_product_bundle.cache_clear()
        dashboard_api._cached_new_product_base.cache_clear()

    def tearDown(self):
        dashboard_api._cached_new_product_bundle.cache_clear()
        dashboard_api._cached_new_product_base.cache_clear()

    def test_developer_filter_preserves_cross_developer_sku_aggregate_and_conflicts(self):
        operational = pd.DataFrame([
            {"MSKU": "SHARED", "ASIN": "A1", "开发员": "甲", "可售": 2, "日均销量": 1},
            {"MSKU": "SHARED", "ASIN": "A2", "开发员": "乙", "可售": 1, "日均销量": 1},
            {"MSKU": "BAD-DATE", "ASIN": "A3", "开发员": "乙", "可售": 5, "日均销量": 1},
        ])
        launches = pd.DataFrame([{"SKU": "SHARED", "开售时间": "2026-10-12"}])
        dashboard_api._cached_new_product_bundle.cache_clear()
        with (
            patch.object(dashboard_api, "load_source_frame", side_effect=lambda key, _title: operational if key == "operational_sales" else (_ for _ in ()).throw(RuntimeError("optional source unavailable"))),
            patch.object(dashboard_api, "_product_launch_rows", return_value=launches),
            patch.object(dashboard_api, "_optional_sku_image_map", return_value=pd.DataFrame()),
            patch.object(dashboard_api, "_sku_image_lookup", return_value={}),
            patch.object(dashboard_api, "load_latest_source_record", return_value=pd.DataFrame()),
            patch.object(dashboard_api, "_batch_monitor_updated_timestamp", return_value=None),
            patch.object(dashboard_api, "_new_product_source_paths", return_value=[]),
        ):
            selected = dashboard_api._cached_new_product_bundle("甲", "all", "all", None, "revision-a", "2026-10-13")
            row = selected["sections"][0]["frame"].iloc[0]
            self.assertEqual(row["SKU"], "SHARED")
            self.assertEqual(row["可售数量"], 3)
            self.assertEqual(row["开发员"], "乙；甲")
            self.assertEqual(row["ASIN"], "多个 ASIN")
            self.assertEqual(row["监控状态"], "数据异常")
            self.assertEqual(selected["excluded_invalid_launch_count"], 0)

            other_developer = dashboard_api._cached_new_product_bundle("乙", "all", "all", None, "revision-a", "2026-10-13")
            self.assertEqual(other_developer["excluded_invalid_launch_count"], 1)

            developer_name_search = dashboard_api._cached_new_product_bundle("甲", "all", "all", "甲", "revision-a", "2026-10-13")
            self.assertFalse(developer_name_search["has_data"])
        dashboard_api._cached_new_product_bundle.cache_clear()

    def test_section_filters_and_paginates_before_returning_rows(self):
        with patch.object(dashboard_api, "_new_product_bundle", side_effect=build_bundle):
            response = self.client.get(
                "/api/dashboard/new-products/sections/detail",
                params={"status": "raise", "page": 2, "page_size": 10},
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["total"], 30)
        self.assertEqual(len(payload["rows"]), 10)
        self.assertEqual(payload["rows"][0]["SKU"], "SKU-020")
        self.assertTrue(all(row["监控状态"] == "建议涨价" for row in payload["rows"]))

    def test_export_contains_all_filtered_rows_beyond_first_page(self):
        with patch.object(dashboard_api, "_new_product_bundle", side_effect=build_bundle):
            response = self.client.get(
                "/api/dashboard/new-products/sections/detail/export.csv",
                params={"status": "lower", "page": 1, "page_size": 1},
            )
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.content.decode("utf-8-sig").splitlines()
        self.assertEqual(len(rows), 31)
        self.assertIn("SKU-059", rows[-1])

    def test_copy_lists_ignore_status_and_page_and_return_every_matching_sku(self):
        with patch.object(dashboard_api, "_new_product_bundle", side_effect=build_bundle) as builder:
            response = self.client.get(
                "/api/dashboard/new-products/copy-lists",
                params={"status": "raise", "page": 2, "page_size": 1},
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["raise_skus"]), 30)
        self.assertEqual(len(payload["lower_skus"]), 30)
        self.assertEqual(payload["raise_skus"][0], "SKU-000")
        self.assertEqual(payload["lower_skus"][-1], "SKU-059")
        self.assertEqual(builder.call_args.kwargs["status"], "all")


    def test_combined_view_keeps_full_lists_while_status_and_page_filter_details(self):
        with patch.object(dashboard_api, "_new_product_bundle", side_effect=build_bundle) as builder:
            response = self.client.get(
                "/api/dashboard/new-products/view",
                params={"status": "raise", "page": 2, "page_size": 10},
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["sections"]), 1)
        detail = payload["sections"][0]
        self.assertEqual(detail["total"], 30)
        self.assertEqual(detail["rows"][0]["SKU"], "SKU-020")
        self.assertEqual(len(detail["rows"]), 10)
        self.assertEqual(len(payload["copy_lists"]["raise_skus"]), 30)
        self.assertEqual(len(payload["copy_lists"]["lower_skus"]), 30)
        self.assertEqual(builder.call_count, 1)

    def test_concurrent_filters_share_base_and_rebuild_for_revision_or_business_day(self):
        operational = pd.DataFrame([
            {"MSKU": "ZERO", "ASIN": "A1", "开发员": "甲", "可售": 20, "日均销量": 0},
            {"MSKU": "FAST", "ASIN": "A2", "开发员": "乙", "可售": 2, "日均销量": 1},
        ])
        launches = pd.DataFrame([
            {"SKU": "ZERO", "开售时间": "2026-10-07"},
            {"SKU": "FAST", "开售时间": "2026-10-12"},
        ])
        actual_build = dashboard_api.build_new_product_monitor_table

        def slow_build(*args, **kwargs):
            time.sleep(0.03)
            return actual_build(*args, **kwargs)

        def load_source(key, _title):
            if key == "operational_sales":
                return operational
            raise RuntimeError("optional source unavailable")

        with (
            patch.object(dashboard_api, "load_source_frame", side_effect=load_source) as source_loader,
            patch.object(dashboard_api, "build_new_product_monitor_table", side_effect=slow_build) as builder,
            patch.object(dashboard_api, "_product_launch_rows", return_value=launches),
            patch.object(dashboard_api, "_optional_sku_image_map", return_value=pd.DataFrame()),
            patch.object(dashboard_api, "_sku_image_lookup", return_value={}),
            patch.object(dashboard_api, "load_latest_source_record", return_value=pd.DataFrame()),
            patch.object(dashboard_api, "_batch_monitor_updated_timestamp", return_value=0),
            patch.object(dashboard_api, "_new_product_source_paths", return_value=[]),
        ):
            scopes = [("甲", "all"), ("乙", "raise"), ("甲", "observing")]
            with ThreadPoolExecutor(max_workers=3) as pool:
                pending = [pool.submit(dashboard_api._cached_new_product_bundle,
                                       developer, "all", status, None, "v1", "2026-10-13")
                           for developer, status in scopes]
                results = [future.result() for future in pending]
            self.assertEqual(builder.call_count, 1)
            self.assertEqual(sum(call.args[0] == "operational_sales" for call in source_loader.call_args_list), 1)
            self.assertEqual(results[0]["sections"][0]["frame"].iloc[0]["监控状态"], "新品观察中")

            dashboard_api._cached_new_product_bundle("甲", "all", "all", None, "v2", "2026-10-13")
            self.assertEqual(builder.call_count, 2)
            next_day = dashboard_api._cached_new_product_bundle("甲", "all", "all", None, "v2", "2026-10-14")
            self.assertEqual(builder.call_count, 3)
            self.assertEqual(next_day["sections"][0]["frame"].iloc[0]["监控状态"], "建议降价")
            self.assertEqual(next_day["copy_lists"]["lower_skus"], ["ZERO"])
            self.assertEqual(results[0]["copy_lists"]["lower_skus"], [])


    def test_revision_tracks_related_source_uploads_and_arrivals_only(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            keys = ("operational_sales", "gross_profit", "rating", "sku_image_map")
            sources = {key: root / f"{key}.csv" for key in keys}
            indices = {key: root / f"{key}-index.csv" for key in keys}
            for path in [*sources.values(), *indices.values()]:
                path.write_text("initial", encoding="utf-8")
            with (
                patch.object(dashboard_api, "get_latest_source_path", side_effect=lambda key: sources.get(key)),
                patch.object(dashboard_api, "latest_source_index_path", side_effect=lambda key: indices[key]),
                patch.object(dashboard_api, "batch_monitor_revision", return_value="arrival-v1") as arrival_revision,
            ):
                original = dashboard_api._new_product_revision()
                (root / "unrelated-listing.csv").write_text("new listing", encoding="utf-8")
                self.assertEqual(dashboard_api._new_product_revision(), original)
                sources["operational_sales"].write_text("changed operational rows", encoding="utf-8")
                updated_source = dashboard_api._new_product_revision()
                self.assertNotEqual(updated_source, original)
                indices["operational_sales"].write_text("new upload timestamp", encoding="utf-8")
                updated_upload = dashboard_api._new_product_revision()
                self.assertNotEqual(updated_upload, updated_source)
                sources["rating"].write_text("new optional rating", encoding="utf-8")
                updated_rating = dashboard_api._new_product_revision()
                self.assertNotEqual(updated_rating, updated_upload)
                arrival_revision.return_value = "arrival-v2"
                self.assertNotEqual(dashboard_api._new_product_revision(), updated_rating)


if __name__ == "__main__":
    unittest.main()