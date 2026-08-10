from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from backend import db
from backend import dashboard_api
from backend.dashboard_api import explicit_selected_values, latest_detail_date, performance_with_total, selected_values
from backend.main import app
from dashboard.report_store import get_latest_source_path, load_upload_records


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_selected_values_uses_all_options_by_default(self):
        self.assertEqual(selected_values(None, ["A", "B"]), ["A", "B"])
        self.assertEqual(selected_values("B", ["A", "B"]), ["B"])

    def test_explicit_selected_values_keeps_an_omitted_filter_visually_empty(self):
        self.assertEqual(explicit_selected_values(None, ["A", "B"]), [])
        self.assertEqual(explicit_selected_values("B", ["A", "B"]), ["B"])

    def test_section_search_handles_nullable_integer_columns(self):
        frame = pd.DataFrame(
            {
                "ASIN": ["B0D9L92YXY", "B000000000"],
                "开售天数": pd.Series([pd.NA, 3], dtype="Int64"),
            }
        )

        result = dashboard_api._query_frame(frame, search="b0d9l92yxy")

        self.assertEqual(result["ASIN"].tolist(), ["B0D9L92YXY"])
        self.assertTrue(pd.isna(result.loc[0, "开售天数"]))

    def test_overview_defaults_to_all_data_with_empty_visible_filters(self):
        home = pd.DataFrame(
            {
                "销售专员": ["甲", "乙"],
                "月份": ["2026-06", "2026-07"],
                "部门": ["一部", "二部"],
                "店铺类型": ["本土", "中企"],
            }
        )
        config = pd.DataFrame(columns=["显示分组", "指标名称", "格式"])
        computed_frames: list[pd.DataFrame] = []

        def empty_metric_table(frame, *_args, **_kwargs):
            computed_frames.append(frame.copy())
            group_columns = _args[1] if len(_args) > 1 else []
            return pd.DataFrame(columns=group_columns)

        with (
            patch("backend.dashboard_api.load_home_data", return_value=home),
            patch("backend.dashboard_api.load_metric_config", return_value=config),
            patch("backend.dashboard_api.compute_metric_table", side_effect=empty_metric_table),
            patch("backend.dashboard_api.split_counted_and_stopped_data", return_value=(home, pd.DataFrame())),
            patch("backend.dashboard_api.load_commission_config", return_value=pd.DataFrame()),
            patch("backend.dashboard_api.load_department_fee_config", return_value=pd.DataFrame()),
            patch("backend.dashboard_api.build_person_commission_summary", return_value=pd.DataFrame()),
            patch("backend.dashboard_api.build_alerts", return_value=pd.DataFrame()),
        ):
            payload = dashboard_api._build_overview(None, None, None, None)

        self.assertEqual(payload["selected"], {"developers": [], "months": [], "departments": [], "store_types": []})
        self.assertTrue(payload["has_data"])
        self.assertEqual(len(computed_frames[0]), 2)

    def test_sales_defaults_to_all_data_with_empty_visible_filter(self):
        operational = pd.DataFrame({"开发员": ["甲", "乙"]})
        stores = pd.DataFrame(
            [
                {
                    "在售个数": 2,
                    "昨日订单": 3,
                    "-26订单": 0,
                    "7天日均": 1.5,
                    "30天日均": 1.25,
                    "总库存": 20,
                }
            ]
        )
        tables = {"stores": stores, "source": operational, "levels": pd.DataFrame(), "date_compare": pd.DataFrame()}
        with (
            patch("backend.dashboard_api.load_source_frame", return_value=pd.DataFrame()),
            patch("backend.dashboard_api.normalize_operational_sales", return_value=operational),
            patch("backend.dashboard_api.load_business_config", return_value=(pd.DataFrame(), pd.DataFrame())),
            patch("backend.dashboard_api.build_sales_dashboard_tables", return_value=tables),
            patch("backend.dashboard_api.count_chen_26_onsale_skus", return_value=0),
        ):
            payload = dashboard_api._build_sales(None)

        self.assertEqual(payload["selected"], {"developers": []})
        self.assertEqual(payload["metrics"][0]["value"], 2)

    def test_slow_moving_filters_stores_configured_as_stopped_before_building_table(self):
        raw = pd.DataFrame({"开发员": ["保留", "已停款"]})
        filtered = pd.DataFrame({"开发员": ["保留"]})
        store_config = pd.DataFrame({"店铺名": ["SGE"], "停提款时间": ["2026-01"]})
        with (
            patch("backend.dashboard_api.load_source_frame", return_value=raw),
            patch("backend.dashboard_api.load_business_config", return_value=(store_config, pd.DataFrame())),
            patch("backend.dashboard_api.exclude_stopped_store_operational_rows", return_value=filtered) as exclude_rows,
            patch("backend.dashboard_api.build_slow_moving_inventory_table", return_value=pd.DataFrame()) as build_table,
        ):
            payload = dashboard_api._build_slow_moving(None, "90天以上")

        exclude_rows.assert_called_once_with(raw, store_config)
        build_table.assert_called_once()
        pd.testing.assert_frame_equal(build_table.call_args.args[0], filtered)
        self.assertEqual(build_table.call_args.args[1], "90天以上")
        self.assertFalse(payload["has_data"])

    def test_product_launch_data_unions_sources_and_preserves_product_rows(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            db, "DB_PATH", Path(directory) / "app.db"
        ):
            db.initialize_database()
            with db.connect() as conn:
                conn.execute(
                    """INSERT INTO batch_monitor_batches
                    (batch_no, artwork_completed_date, source_file_name, source_file_hash, created_at, updated_at)
                    VALUES ('BATCH-001', NULL, 'batch.xlsx', 'hash', '2026-08-01T00:00:00+08:00', '2026-08-01T00:00:00+08:00')"""
                )
                conn.executemany(
                    """INSERT INTO batch_monitor_skus
                    (sku, batch_no, de_price, fr_price, es_price, it_price,
                     developer_snapshot, monitor_basis, created_at)
                    VALUES (?, 'BATCH-001', ?, ?, ?, ?, '', 'creation_match', '2026-08-01T00:00:00+08:00')""",
                    [
                        ("SKU-A", 5.9, 6.99, 7.99, 8.99),
                        ("SKU-B", 9.9, None, None, None),
                    ],
                )
                conn.executemany(
                    """INSERT INTO sku_first_shipments
                    (sku, shipment_no, asin, arrival_date, updated_at)
                    VALUES (?, ?, ?, ?, '2026-08-03T00:00:00+08:00')""",
                    [
                        ("SKU-A", "FBA-A", "B000000001", "2026-08-03"),
                        ("SKU-C", "FBA-C", "B000000003", "2026-07-30"),
                    ],
                )
                conn.executemany(
                    """INSERT INTO sku_launch_prices
                    (sku, de_price, fr_price, es_price, it_price, source_file_hash, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'legacy-hash', '2026-08-03T00:00:00+08:00')""",
                    [
                        ("SKU-B", 8.8, 8.49, 8.59, 8.69),
                        ("SKU-D", 4.99, 5.99, 6.99, 7.99),
                    ],
                )

            launch_rows = dashboard_api._product_launch_rows()

        detail = pd.DataFrame(
            [
                {"SKU": " sku-a ", "ASIN": "B000000001", "Rating": "10(4.5)", "德国销量": 1},
                {"SKU": "SKU-B", "ASIN": "B000000002", "Rating": "", "德国销量": 2},
                {"SKU": "sku-c", "ASIN": "B000000003", "Rating": "", "德国销量": 3},
                {"SKU": "SKU-D", "ASIN": "B000000004", "Rating": "", "德国销量": 4},
            ]
        )
        result = dashboard_api.merge_product_launch_data(
            detail,
            launch_rows,
            today=date(2026, 8, 3),
        )

        self.assertEqual(result["SKU"].tolist(), [" sku-a ", "SKU-B", "sku-c", "SKU-D"])
        self.assertEqual(len(result), len(detail))
        self.assertEqual(result.loc[0, "德国开售价格"], 5.9)
        self.assertEqual(result.loc[0, "开售时间"], "2026-08-03")
        self.assertEqual(result.loc[0, "开售天数"], 0)
        self.assertEqual(result.loc[1, "德国开售价格"], 9.9)
        self.assertEqual(result.loc[1, "法国开售价格"], 8.49)
        self.assertTrue(pd.isna(result.loc[1, "开售时间"]))
        self.assertTrue(pd.isna(result.loc[1, "开售天数"]))
        self.assertTrue(pd.isna(result.loc[2, "德国开售价格"]))
        self.assertEqual(result.loc[2, "开售时间"], "2026-07-30")
        self.assertEqual(result.loc[2, "开售天数"], 4)
        self.assertEqual(result.loc[3, "德国开售价格"], 4.99)
        self.assertEqual(result.loc[3, "意大利开售价格"], 7.99)
        self.assertTrue(pd.isna(result.loc[3, "开售时间"]))
        self.assertTrue(pd.isna(result.loc[3, "开售天数"]))

    def test_product_page_revision_includes_batch_monitor_only_for_products(self):
        with (
            patch("backend.dashboard_api.dashboard_revision", return_value="dashboard-v1"),
            patch("backend.dashboard_api.batch_monitor_revision", return_value="batch-v2"),
        ):
            self.assertEqual(
                dashboard_api._page_revision("products"),
                "dashboard-v1:batch-v2",
            )
            self.assertEqual(
                dashboard_api._page_revision("sales"),
                "dashboard-v1",
            )

    def test_latest_detail_date_uses_latest_common_metric_day(self):
        volume = pd.DataFrame(columns=["07-06销量", "07-05销量"])
        amount = pd.DataFrame(columns=["07-06销售额", "07-04销售额"])
        result = latest_detail_date(volume, amount)
        self.assertEqual((result.month, result.day), (7, 6))

    def test_performance_total_row_is_inserted_first(self):
        frame = pd.DataFrame([
            {"开发员": "A", "在售SKU数量": 2, "库存总数": 20, "占用资金": 1000, "销售额贡献占比": 0.6, "7月12日销量": 10},
            {"开发员": "B", "在售SKU数量": 3, "库存总数": 30, "占用资金": 2000, "销售额贡献占比": 0.4, "7月12日销量": 20},
        ])
        result = performance_with_total(frame)
        self.assertEqual(result.iloc[0]["开发员"], "合计")
        self.assertEqual(result.iloc[0]["在售SKU数量"], 5)
        self.assertEqual(result.iloc[0]["库存总数"], 50)
        self.assertEqual(result.iloc[0]["占用资金"], 3000)
        self.assertEqual(result.iloc[0]["销售额贡献占比"], 1)
        self.assertEqual(result.iloc[0]["7月12日销量"], 30)

        store_result = performance_with_total(
            pd.DataFrame([{"店铺": "AEU", "在售SKU数量": 1, "销售额贡献占比": 1, "7月12日销量": 10}])
        )
        self.assertEqual(store_result.iloc[0]["店铺"], "合计")
        self.assertEqual(store_result.iloc[0]["在售SKU数量"], 1)

    def test_current_workspace_dashboard_pages_return_business_sections(self):
        required_sources = ["operational_sales", "gross_profit", "rating", "sales_volume_detail", "sales_amount_detail"]
        if load_upload_records().empty or any(get_latest_source_path(key) is None for key in required_sources):
            self.skipTest("workspace sample data is not available")
        for page in ["overview", "sales", "slow-moving", "products", "department", "replenishment"]:
            with self.subTest(page=page):
                response = self.client.get(f"/api/dashboard/{page}")
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertTrue(payload["has_data"])
                self.assertGreater(len(payload["sections"]), 0)
                if page == "products":
                    detail = next(section for section in payload["sections"] if section["key"] == "detail")
                    asin = next(row["ASIN"] for row in detail["rows"] if row.get("ASIN"))
                    searched = self.client.get(
                        "/api/dashboard/products/sections/detail",
                        params={"search": asin, "page": 1, "page_size": 20},
                    )
                    self.assertEqual(searched.status_code, 200, searched.text)
                    self.assertTrue(any(row.get("ASIN") == asin for row in searched.json()["rows"]))
                if page == "department":
                    titles = [section["title"] for section in payload["sections"]]
                    self.assertTrue(titles[0].endswith("人员提成汇总"))
                    self.assertEqual(titles[1:], ["开发员业绩排行", "部门业绩", "店铺业绩排行"])
                    for section in payload["sections"][1:]:
                        column_keys = [column["key"] for column in section["columns"]]
                        self.assertIn("在售SKU数量", column_keys)
                        self.assertEqual(
                            column_keys[1:5],
                            ["在售SKU数量", "库存总数", "占用资金", "销售额贡献占比"],
                        )
                        metadata = {column["key"]: column for column in section["columns"]}
                        self.assertEqual(metadata["库存总数"]["format"], "integer")
                        self.assertEqual(metadata["占用资金"]["format"], "amount")
                        self.assertNotIn("在售产品数", column_keys)
                    exported = self.client.get("/api/dashboard/department/sections/performance-0/export.csv")
                    self.assertEqual(exported.status_code, 200, exported.text)
                    exported_header = exported.content.decode("utf-8-sig").splitlines()[0]
                    self.assertIn("在售SKU数量,库存总数,占用资金,销售额贡献占比", exported_header)

    def test_replenishment_min_qty_filters_disabled_rows_before_metrics(self):
        detail = pd.DataFrame([
            {"补货组ID": "B001", "ASIN": "B001", "开发员": "甲", "建议补货数量": 20, "是否补货": True, "数据状态": "正常"},
            {"补货组ID": "B002", "ASIN": "B002", "开发员": "甲", "建议补货数量": 30, "是否补货": True, "数据状态": "正常"},
            {"补货组ID": "B003", "ASIN": "B003", "开发员": "乙", "建议补货数量": 100, "是否补货": False, "数据状态": "已关闭补货"},
            {"补货组ID": "B004", "ASIN": "B004", "开发员": "乙", "建议补货数量": pd.NA, "是否补货": True, "数据状态": "数据异常"},
        ])
        with (
            patch("backend.dashboard_api.load_source_frame", return_value=pd.DataFrame({"开发员": ["甲", "乙"]})),
            patch("backend.dashboard_api._replenishment_tables", return_value={"detail": detail}),
        ):
            payload = dashboard_api._build_replenishment(None, min_qty=30)

        visible = payload["sections"][0]["frame"]
        self.assertEqual(visible["ASIN"].tolist(), ["B002"])
        self.assertEqual(payload["metrics"][0]["value"], 1)
        self.assertEqual(payload["metrics"][1]["value"], 30)
        self.assertEqual(payload["metrics"][2]["value"], 0)

    def test_replenishment_switch_overlay_reuses_calculation_and_preserves_data_errors(self):
        detail = pd.DataFrame([
            {
                "补货组ID": "B001", "ASIN": "B001", "测算建议补货数量": 30,
                "建议补货数量": 30, "是否补货": True, "关闭原因": "",
                "数据状态": "正常",
            },
            {
                "补货组ID": "B002", "ASIN": "B002", "测算建议补货数量": pd.NA,
                "建议补货数量": pd.NA, "是否补货": True, "关闭原因": "",
                "数据状态": "数据异常",
            },
        ])
        switches = pd.DataFrame([
            {"ASIN": "B001", "是否补货": False, "关闭原因": "停售"},
            {"ASIN": "B002", "是否补货": False, "关闭原因": "资料缺失"},
        ])

        result = dashboard_api._apply_replenishment_switches(detail, switches).set_index("ASIN")

        self.assertFalse(result.loc["B001", "是否补货"])
        self.assertEqual(result.loc["B001", "建议补货数量"], 0)
        self.assertEqual(result.loc["B001", "数据状态"], "已关闭补货")
        self.assertEqual(result.loc["B001", "关闭原因"], "停售")
        self.assertFalse(result.loc["B002", "是否补货"])
        self.assertTrue(pd.isna(result.loc["B002", "建议补货数量"]))
        self.assertEqual(result.loc["B002", "数据状态"], "数据异常")

    def test_replenishment_switch_endpoint_upserts_asin_and_requires_reason(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("backend.dashboard_api.load_source_frame", return_value=pd.DataFrame({"ASIN": ["B001"]})),
            patch("backend.config_api.CONFIG_DIR", Path(directory)),
            patch("backend.config_api._invalidate_replenishment_view_cache") as invalidate,
        ):
            invalid = self.client.put(
                "/api/dashboard/replenishment/asins/B001/switch",
                json={"is_replenishment": False, "close_reason": ""},
            )
            first = self.client.put(
                "/api/dashboard/replenishment/asins/b001/switch",
                json={"is_replenishment": False, "close_reason": "停售"},
            )
            second = self.client.put(
                "/api/dashboard/replenishment/asins/B001/switch",
                json={"is_replenishment": False, "close_reason": "季节结束"},
            )

            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json()["ASIN"], "B001")
            saved = pd.read_csv(Path(directory) / "replenishment_switches.csv", encoding="utf-8-sig")
            self.assertEqual(saved.to_dict(orient="records"), [
                {"ASIN": "B001", "是否补货": False, "关闭原因": "季节结束"},
            ])
            self.assertEqual(invalidate.call_count, 2)


if __name__ == "__main__":
    unittest.main()
