from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

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

    def test_latest_detail_date_uses_latest_common_metric_day(self):
        volume = pd.DataFrame(columns=["07-06销量", "07-05销量"])
        amount = pd.DataFrame(columns=["07-06销售额", "07-04销售额"])
        result = latest_detail_date(volume, amount)
        self.assertEqual((result.month, result.day), (7, 6))

    def test_performance_total_row_is_inserted_first(self):
        frame = pd.DataFrame([
            {"开发员": "A", "在售产品数": 2, "销售额贡献占比": 0.6, "7月12日销量": 10},
            {"开发员": "B", "在售产品数": 3, "销售额贡献占比": 0.4, "7月12日销量": 20},
        ])
        result = performance_with_total(frame)
        self.assertEqual(result.iloc[0]["开发员"], "合计")
        self.assertEqual(result.iloc[0]["在售产品数"], 5)
        self.assertEqual(result.iloc[0]["销售额贡献占比"], 1)
        self.assertEqual(result.iloc[0]["7月12日销量"], 30)

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


if __name__ == "__main__":
    unittest.main()
