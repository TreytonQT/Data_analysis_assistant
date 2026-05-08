import unittest

import pandas as pd

from dashboard.data_processing import (
    compute_commission_table,
    compute_metric_table,
    merge_business_config,
    normalize_commission_config,
    normalize_report,
    select_metric_config,
)


class DataProcessingTests(unittest.TestCase):
    def commission_metrics(self):
        return pd.DataFrame(
            [
                {
                    "指标名称": "销售额",
                    "显示分组": "开发员分析",
                    "公式": 'range_sum("销售额--FBA销售额", "COD")',
                },
                {"指标名称": "毛利润", "显示分组": "开发员分析", "公式": "sum([毛利润])"},
                {
                    "指标名称": "毛利率",
                    "显示分组": "开发员分析",
                    "公式": 'safe_divide(sum([毛利润]), range_sum("销售额--FBA销售额", "COD"))',
                },
            ]
        )

    def test_grouped_metrics_use_configured_formulas(self):
        data = pd.DataFrame(
            {
                "销售专员": ["A", "A", "B"],
                "月份": ["2026-01-01~2026-01-31"] * 3,
                "店铺": ["6-ZXU 德国", "7-YIP 法国", "6-ZXU 德国"],
                "销售额--FBA销售额": [100, 200, 50],
                "销售额--FBM销售额": [0, 0, 0],
                "买家运费--FBA买家运费": [10, 0, 5],
                "COD": [1, 2, 3],
                "毛利润": [20, 30, 5],
                "广告费-SP广告": [-10, -20, -5],
            }
        )
        metrics = pd.DataFrame(
            [
                {
                    "指标名称": "销售额",
                    "显示分组": "开发员分析",
                    "公式": 'range_sum("销售额--FBA销售额", "COD")',
                },
                {
                    "指标名称": "毛利率",
                    "显示分组": "开发员分析",
                    "公式": "safe_divide(sum([毛利润]), sum([销售额--FBA销售额]))",
                },
                {
                    "指标名称": "低毛利标记",
                    "显示分组": "开发员分析",
                    "公式": "if(safe_divide(sum([毛利润]), sum([销售额--FBA销售额])) < 0.15, 1, 0)",
                },
            ]
        )

        normalized = normalize_report(data)
        result = compute_metric_table(normalized, metrics, ["销售专员"]).set_index("销售专员")

        self.assertEqual(result.loc["A", "销售额"], 313)
        self.assertAlmostEqual(result.loc["A", "毛利率"], 50 / 300)
        self.assertEqual(result.loc["B", "低毛利标记"], 1)

    def test_web_target_config_accepts_percent_number(self):
        report = normalize_report(
            pd.DataFrame(
                {
                    "销售专员": ["A"],
                    "月份": ["2026-01"],
                    "店铺": ["6-ZXU 德国"],
                }
            )
        )
        store_config = pd.DataFrame({"店铺名": ["ZXU"], "店铺类型": ["中企"], "是否计数": ["是"], "店铺所属部门": ["运营部"]})
        target_config = pd.DataFrame({"开发员": ["A"], "目标业绩": [100], "目标毛利率": [23]})

        merged = merge_business_config(report, store_config, target_config)

        self.assertEqual(merged.loc[0, "销售额目标"], 100)
        self.assertAlmostEqual(merged.loc[0, "毛利率目标"], 0.23)

    def test_commission_config_accepts_percent_variants(self):
        config = normalize_commission_config(
            pd.DataFrame(
                {
                    "月份": ["2026-01", "2026-01", "2026-01"],
                    "开发员": ["A", "B", "C"],
                    "费用率": ["8%", "0.08", "8"],
                    "库存计提": ["1", "2", "3"],
                    "弃置": [0, 0, 0],
                    "职位提点": ["8%", "0.08", "8"],
                }
            )
        )

        self.assertTrue((config["费用率"].round(4) == 0.08).all())
        self.assertTrue((config["职位提点"].round(4) == 0.08).all())

    def test_commission_calculates_by_month_developer_and_marks_missing_config(self):
        report = normalize_report(
            pd.DataFrame(
                {
                    "销售专员": ["A", "A"],
                    "月份": ["2026-01", "2026-02"],
                    "店铺": ["6-ZXU 德国", "6-ZXU 德国"],
                    "销售额--FBA销售额": [100, 200],
                    "COD": [0, 0],
                    "毛利润": [30, 60],
                }
            )
        )
        config = pd.DataFrame(
            {
                "月份": ["2026-01"],
                "开发员": ["A"],
                "费用率": ["10%"],
                "库存计提": [5],
                "弃置": [1],
                "职位提点": ["20%"],
            }
        )

        result = compute_commission_table(report, self.commission_metrics(), config)
        jan = result[result["月份"].eq("2026-01")].iloc[0]
        feb = result[result["月份"].eq("2026-02")].iloc[0]

        self.assertAlmostEqual(jan["提成预估"], 2.8)
        self.assertEqual(jan["配置状态"], "已配置")
        self.assertTrue(pd.isna(feb["提成预估"]))
        self.assertEqual(feb["配置状态"], "缺配置")

    def test_commission_keeps_negative_result(self):
        report = normalize_report(
            pd.DataFrame(
                {
                    "销售专员": ["A"],
                    "月份": ["2026-01"],
                    "店铺": ["6-ZXU 德国"],
                    "销售额--FBA销售额": [100],
                    "COD": [0],
                    "毛利润": [5],
                }
            )
        )
        config = pd.DataFrame(
            {
                "月份": ["2026-01"],
                "开发员": ["A"],
                "费用率": ["10%"],
                "库存计提": [0],
                "弃置": [0],
                "职位提点": ["20%"],
            }
        )

        result = compute_commission_table(report, self.commission_metrics(), config)

        self.assertAlmostEqual(result.iloc[0]["提成预估"], -1.0)

    def test_store_type_sales_uses_configured_sales_formula(self):
        report = normalize_report(
            pd.DataFrame(
                {
                    "销售专员": ["A", "A"],
                    "月份": ["2026-01", "2026-01"],
                    "店铺": ["6-ZXU 德国", "7-YIP 法国"],
                    "店铺类型": ["中企", "本土"],
                    "销售额--FBA销售额": [100, 200],
                    "COD": [1, 2],
                    "毛利润": [10, 20],
                }
            )
        )
        sales_metric = select_metric_config(self.commission_metrics(), ["销售额"])

        result = compute_metric_table(report, sales_metric, ["销售专员", "店铺类型"]).set_index("店铺类型")

        self.assertEqual(result.loc["中企", "销售额"], 101)
        self.assertEqual(result.loc["本土", "销售额"], 202)


if __name__ == "__main__":
    unittest.main()
