from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from backend import dashboard_api
from backend.main import app


class DashboardContractApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    @staticmethod
    def _bundle(frame: pd.DataFrame) -> dict:
        return {
            "title": "测试看板",
            "has_data": not frame.empty,
            "filters": {"developers": ["甲", "乙"]},
            "selected": {"developers": ["甲", "乙"]},
            "metrics": [],
            "message": None,
            "sections": [
                dashboard_api.section(
                    "detail",
                    "测试明细",
                    frame,
                    chart={"kind": "bar", "x": "姓名", "series": ["销售额"]},
                    formats={"销售额": "金额", "毛利率": "百分比"},
                )
            ],
        }

    @staticmethod
    def _frame() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"姓名": "安娜", "地区": "华东", "销售额": 100.5, "毛利率": 0.10},
                {"姓名": "白露", "地区": "华南", "销售额": 200.5, "毛利率": 0.20},
                {"姓名": "陈晨", "地区": "华东", "销售额": 300.5, "毛利率": 0.30},
                {"姓名": "丁冬", "地区": "华东", "销售额": 400.5, "毛利率": 0.40},
            ]
        )

    def test_section_search_sort_and_pagination_are_applied_before_slicing(self) -> None:
        bundle = self._bundle(self._frame())
        with patch("backend.dashboard_api._bundle", return_value=bundle):
            response = self.client.get(
                "/api/dashboard/products/sections/detail",
                params={
                    "page": 2,
                    "page_size": 2,
                    "search": "华东",
                    "sort_by": "销售额",
                    "sort_order": "desc",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["page_size"], 2)
        self.assertEqual(payload["total"], 3)
        self.assertEqual([row["姓名"] for row in payload["rows"]], ["安娜"])

    def test_sales_store_summary_uses_all_filtered_rows_not_only_current_page(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "店铺编码": "KEEP-A",
                    "店铺类型": "本土",
                    "店铺状态": "正常",
                    "在售个数": 100,
                    "产品数占比": 0.6,
                    "昨日D值": 1.2,
                    "7天D值": 0.7,
                    "昨日订单": 120,
                    "-26订单": 20,
                    "7天日均": 70,
                    "30天日均": 60,
                    "总库存": 1000,
                    "占用资金": 10000,
                },
                {
                    "店铺编码": "KEEP-B",
                    "店铺类型": "中企",
                    "店铺状态": "正常",
                    "在售个数": 50,
                    "产品数占比": 0.3,
                    "昨日D值": 0.6,
                    "7天D值": 0.4,
                    "昨日订单": 30,
                    "-26订单": 5,
                    "7天日均": 20,
                    "30天日均": 15,
                    "总库存": 500,
                    "占用资金": 5000,
                },
                {
                    "店铺编码": "OTHER",
                    "店铺类型": "中企",
                    "店铺状态": "正常",
                    "在售个数": 25,
                    "产品数占比": 0.1,
                    "昨日D值": 2,
                    "7天D值": 1,
                    "昨日订单": 50,
                    "-26订单": 0,
                    "7天日均": 25,
                    "30天日均": 20,
                    "总库存": 250,
                    "占用资金": 2500,
                },
            ]
        )
        model = dashboard_api.section(
            "stores",
            "店铺明细",
            frame,
            summary_mode="sales_stores",
        )
        bundle = {**self._bundle(frame), "sections": [model]}

        with patch("backend.dashboard_api._bundle", return_value=bundle):
            response = self.client.get(
                "/api/dashboard/sales/sections/stores",
                params={"page": 1, "page_size": 1, "search": "KEEP"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["total"], 2)
        summary = payload["summary"]
        self.assertEqual(summary["店铺编码"], "合计")
        self.assertEqual(summary["在售个数"], 150)
        self.assertAlmostEqual(summary["产品数占比"], 0.9)
        self.assertAlmostEqual(summary["昨日D值"], 1)
        self.assertAlmostEqual(summary["7天D值"], 0.6)
        self.assertEqual(summary["昨日订单"], 150)
        self.assertEqual(summary["-26订单"], 25)
        self.assertEqual(summary["7天日均"], 90)
        self.assertEqual(summary["30天日均"], 75)
        self.assertEqual(summary["总库存"], 1500)
        self.assertEqual(summary["占用资金"], 15000)

    def test_section_rejects_unknown_sort_column_and_oversized_page(self) -> None:
        bundle = self._bundle(self._frame())
        with patch("backend.dashboard_api._bundle", return_value=bundle):
            unknown = self.client.get(
                "/api/dashboard/products/sections/detail",
                params={"sort_by": "不存在"},
            )
            oversized = self.client.get(
                "/api/dashboard/products/sections/detail",
                params={"page_size": 201},
            )

        self.assertEqual(unknown.status_code, 422)
        self.assertEqual(oversized.status_code, 422)

    def test_section_maps_display_label_to_key_and_sorts_formatted_numbers_before_paging(self) -> None:
        frame = pd.DataFrame(
            [
                {"person": "甲", "sales_amount": "1,200"},
                {"person": "乙", "sales_amount": "80"},
                {"person": "丙", "sales_amount": "未配置"},
                {"person": "丁", "sales_amount": "300"},
            ]
        )
        model = {
            "key": "detail",
            "title": "测试明细",
            "frame": frame,
            "columns": [
                {"key": "person", "label": "姓名", "type": "string", "format": "text", "sortable": True},
                {"key": "sales_amount", "label": "销售额", "type": "number", "format": "amount", "sortable": True},
            ],
            "chart": None,
        }
        bundle = {**self._bundle(frame), "sections": [model]}

        with patch("backend.dashboard_api._bundle", return_value=bundle):
            first_page = self.client.get(
                "/api/dashboard/products/sections/detail",
                params={"page": 1, "page_size": 2, "sort_by": "销售额", "sort_order": "asc"},
            )
            second_page = self.client.get(
                "/api/dashboard/products/sections/detail",
                params={"page": 2, "page_size": 2, "sort_by": "sales_amount", "sort_order": "asc"},
            )

        self.assertEqual(first_page.status_code, 200, first_page.text)
        self.assertEqual(second_page.status_code, 200, second_page.text)
        self.assertEqual([row["person"] for row in first_page.json()["rows"]], ["乙", "丁"])
        self.assertEqual([row["person"] for row in second_page.json()["rows"]], ["甲", "丙"])

    def test_replenishment_section_returns_structured_group_rows(self) -> None:
        frame = pd.DataFrame([{
            "补货组ID": "B001", "ASIN": "B001", "原SKU": "SKU-1", "跟卖SKU": "SKU-2；SKU-3",
            "SKU数量": 3, "店铺编码": "ZXU", "店铺状态": "ZXU·正常", "开发员": "甲",
            "产品标签": "爆款", "产品标签颜色": "#16A34A", "产品评价数": 120, "产品评分值": 4.5,
            "德国单量": 20, "德国毛利率": 0.25, "德国原因": "",
            "法国单量": 10, "法国毛利率": 0.15, "法国原因": "SKU-2: 广告炸",
            "西班牙单量": 0, "西班牙毛利率": 0.05, "西班牙原因": "",
            "意大利单量": 1, "意大利毛利率": -0.1, "意大利原因": "SKU-3: 退货多",
            "亚马逊可售": 30, "总可售": 50, "跟卖总可售": 50, "库龄90天以上": 5,
            "库龄180-365天": 2, "库龄365天以上": 1, "T值": 1.5, "校准日销量": 4,
            "最大重量(g)": 120, "库存覆盖天数": 90, "最近促销开始日期": "2026-08-01",
            "最近促销截止日期": "2026-08-10", "最近促销折扣": 10,
            "DE总销量": 120, "FR总销量": 80, "ES总销量": 60, "IT总销量": 40,
            **{
                key: value
                for month in range(1, 13)
                for key, value in (
                    (f"{month}月总销量", month * 10),
                    (f"{month}月出单天数", month),
                    (f"{month}月除0日均", 10),
                )
            },
            "目标库存": 360, "测算建议补货数量": 310, "建议补货数量": 310,
            "是否补货": True, "关闭原因": "", "数据状态": "正常", "数据异常": "",
        }])
        model = dashboard_api.section(
            "detail",
            "ASIN补货汇总",
            frame,
            row_serializer=dashboard_api._replenishment_group_rows,
        )
        payload = dashboard_api._serialized_section(model)

        self.assertEqual(payload["group_rows"][0]["identity"]["follower_skus"], ["SKU-2", "SKU-3"])
        self.assertEqual(payload["group_rows"][0]["identity"]["rating"], {"review_count": 120, "score": 4.5})
        self.assertEqual(payload["group_rows"][0]["countries"]["FR"]["margin"], 0.15)
        self.assertEqual(payload["group_rows"][0]["promotion"]["start_date"], "2026-08-01")
        self.assertEqual(payload["group_rows"][0]["history"]["site_sales"]["DE"], 120)
        self.assertEqual(payload["group_rows"][0]["history"]["peak_months"][0]["month"], 12)
        self.assertNotIn("remarks", payload["group_rows"][0]["identity"])
        self.assertEqual(payload["group_rows"][0]["recommendation"]["official_quantity"], 310)

    def test_numeric_sort_is_stable_and_percent_values_use_numeric_order(self) -> None:
        amount_frame = pd.DataFrame(
            [
                {"row": "first", "amount": "100"},
                {"row": "second", "amount": "100.00"},
                {"row": "third", "amount": "20"},
            ]
        )
        amount_columns = [
            {"key": "row", "label": "行", "format": "text", "sortable": True},
            {"key": "amount", "label": "金额", "type": "number", "format": "amount", "sortable": True},
        ]
        sorted_amounts = dashboard_api._query_frame(
            amount_frame,
            sort_by="amount",
            sort_order="asc",
            columns=amount_columns,
        )
        self.assertEqual(sorted_amounts["row"].tolist(), ["third", "first", "second"])

        percent_frame = pd.DataFrame(
            [{"rate": "8%"}, {"rate": 0.15}, {"rate": "12%"}, {"rate": "未配置"}]
        )
        percent_columns = [
            {"key": "rate", "label": "毛利率", "type": "percent", "format": "percent", "sortable": True}
        ]
        sorted_rates = dashboard_api._query_frame(
            percent_frame,
            sort_by="毛利率",
            sort_order="desc",
            columns=percent_columns,
        )
        self.assertEqual(sorted_rates["rate"].tolist(), [0.15, "12%", "8%", "未配置"])

    def test_section_rejects_sorting_a_non_sortable_column(self) -> None:
        frame = pd.DataFrame([{"internal": 2}, {"internal": 1}])
        model = {
            "key": "detail",
            "title": "测试明细",
            "frame": frame,
            "columns": [
                {"key": "internal", "label": "内部值", "type": "number", "format": "number", "sortable": False}
            ],
            "chart": None,
        }
        bundle = {**self._bundle(frame), "sections": [model]}
        with patch("backend.dashboard_api._bundle", return_value=bundle):
            response = self.client.get(
                "/api/dashboard/products/sections/detail",
                params={"sort_by": "内部值", "sort_order": "asc"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("不支持排序", response.json()["detail"])

    def test_summary_returns_only_first_fifty_rows_and_column_metadata(self) -> None:
        frame = pd.DataFrame(
            [
                {"姓名": f"人员-{index:03d}", "销售额": float(index), "毛利率": index / 1000}
                for index in range(75)
            ]
        )
        bundle = self._bundle(frame)
        with (
            patch("backend.dashboard_api._bundle", return_value=bundle),
            patch("backend.dashboard_api._revision_paths", return_value=[]),
        ):
            response = self.client.get("/api/dashboard/products")

        self.assertEqual(response.status_code, 200, response.text)
        section = response.json()["sections"][0]
        self.assertEqual(len(section["rows"]), 50)
        self.assertEqual(section["total"], 75)
        self.assertTrue(section["paginated"])

        columns = {column["key"]: column for column in section["columns"]}
        self.assertEqual(columns["姓名"]["format"], "text")
        self.assertEqual(columns["销售额"]["format"], "amount")
        self.assertEqual(columns["销售额"]["unit"], "万")
        self.assertEqual(columns["销售额"]["precision"], 2)
        self.assertEqual(columns["毛利率"]["format"], "percent")
        self.assertEqual(columns["毛利率"]["unit"], "%")
        self.assertTrue(all("sortable" in column for column in columns.values()))

        chart = section["chart"]
        self.assertEqual(chart["x"], "姓名")
        self.assertEqual(chart["series"][0]["key"], "销售额")
        self.assertEqual(chart["series"][0]["type"], "number")
        self.assertEqual(chart["series"][0]["format"], "amount")
        self.assertEqual(chart["series"][0]["unit"], "万")
        self.assertEqual(chart["series"][0]["precision"], 2)

    def test_chart_series_inherits_numeric_type_and_column_format(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "店铺编码": "ZXU",
                    "昨日订单": 122,
                    "30天日均": 120.1666666667,
                    "销售额": 6_781_658.6,
                }
            ]
        )
        model = dashboard_api.section(
            "stores",
            "店铺明细",
            frame,
            chart={"kind": "bar", "x": "店铺编码", "series": ["昨日订单", "30天日均", "销售额"]},
        )

        chart_series = {series["key"]: series for series in model["chart"]["series"]}
        yesterday_orders = chart_series["昨日订单"]
        self.assertEqual(yesterday_orders["type"], "number")
        self.assertEqual(yesterday_orders["format"], "integer")
        self.assertEqual(yesterday_orders["precision"], 0)

        thirty_day_average = chart_series["30天日均"]
        self.assertEqual(thirty_day_average["type"], "number")
        self.assertEqual(thirty_day_average["format"], "number")
        self.assertEqual(thirty_day_average["precision"], 2)

        sales_amount = chart_series["销售额"]
        self.assertEqual(sales_amount["type"], "number")
        self.assertEqual(sales_amount["format"], "amount")
        self.assertEqual(sales_amount["unit"], "万")
        self.assertEqual(sales_amount["precision"], 2)

        self.assertEqual(model["frame"].loc[0, "昨日订单"], 122)
        self.assertEqual(model["frame"].loc[0, "30天日均"], 120.1666666667)
        self.assertEqual(model["frame"].loc[0, "销售额"], 6_781_658.6)

    def test_amount_metadata_uses_wan_without_changing_raw_values(self) -> None:
        amount_values = {
            "销售额": 6_781_658.6,
            "营业额": 5_000_000,
            "毛利润": 1_459_274.8,
            "广告费": 372_935.27,
            "库存货值": 260_000,
            "提成金额": 125_000,
        }
        frame = pd.DataFrame([amount_values])
        model = dashboard_api.section(
            "amounts",
            "金额指标",
            frame,
            chart={"kind": "bar", "x": "销售额", "series": ["毛利润", "广告费"]},
        )

        columns = {column["key"]: column for column in model["columns"]}
        for name, raw_value in amount_values.items():
            with self.subTest(name=name):
                self.assertEqual(columns[name]["format"], "amount")
                self.assertEqual(columns[name]["unit"], "万")
                self.assertEqual(columns[name]["precision"], 2)
                self.assertEqual(model["frame"].loc[0, name], raw_value)

        chart_series = {series["key"]: series for series in model["chart"]["series"]}
        self.assertEqual(chart_series["毛利润"]["unit"], "万")
        self.assertEqual(chart_series["广告费"]["unit"], "万")

        advertising_ratio = dashboard_api.column_definition("广告费占比")
        self.assertEqual(advertising_ratio["format"], "percent")
        self.assertEqual(advertising_ratio["unit"], "%")
        self.assertEqual(advertising_ratio["precision"], 2)

        gross_profit = dashboard_api.metric("毛利润", amount_values["毛利润"], "amount")
        advertising_cost = dashboard_api.metric("广告费", amount_values["广告费"], "金额")
        self.assertEqual(gross_profit["unit"], "万")
        self.assertEqual(gross_profit["precision"], 2)
        self.assertEqual(gross_profit["value"], amount_values["毛利润"])
        self.assertEqual(advertising_cost["unit"], "万")
        self.assertEqual(advertising_cost["value"], amount_values["广告费"])

    def test_export_streams_all_filtered_rows_in_requested_order(self) -> None:
        bundle = self._bundle(self._frame())
        with patch("backend.dashboard_api._bundle", return_value=bundle):
            response = self.client.get(
                "/api/dashboard/products/sections/detail/export.csv",
                params={"search": "华东", "sort_by": "销售额", "sort_order": "desc"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        self.assertIn("filename*=UTF-8''", response.headers["content-disposition"])
        exported = pd.read_csv(io.BytesIO(response.content), encoding="utf-8-sig")
        self.assertEqual(exported["姓名"].tolist(), ["丁冬", "陈晨", "安娜"])
        self.assertEqual(exported["销售额"].tolist(), [400.5, 300.5, 100.5])

    def test_large_api_response_is_gzip_compressed(self) -> None:
        frame = pd.DataFrame(
            [
                {"姓名": f"人员-{index}", "备注": "重复内容" * 100, "销售额": index}
                for index in range(50)
            ]
        )
        bundle = self._bundle(frame)
        with (
            patch("backend.dashboard_api._bundle", return_value=bundle),
            patch("backend.dashboard_api._revision_paths", return_value=[]),
        ):
            response = self.client.get(
                "/api/dashboard/products",
                headers={"Accept-Encoding": "gzip"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers.get("content-encoding"), "gzip")
        self.assertIn("accept-encoding", response.headers.get("vary", "").lower())


if __name__ == "__main__":
    unittest.main()
