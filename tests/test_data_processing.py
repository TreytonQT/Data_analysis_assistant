import unittest

import pandas as pd

from dashboard.data_processing import compute_metric_table, merge_business_config, normalize_report


class DataProcessingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
