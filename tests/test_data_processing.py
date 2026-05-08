import unittest

import pandas as pd

from dashboard.data_processing import (
    compute_commission_table,
    compute_metric_table,
    compute_stopped_commission_table,
    merge_business_config,
    normalize_commission_config,
    normalize_department_fee_config,
    normalize_report,
    normalize_store_config,
    select_metric_config,
    split_counted_and_stopped_data,
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

    def test_legacy_store_count_flag_does_not_migrate_to_stop_month(self):
        config = normalize_store_config(
            pd.DataFrame(
                {
                    "店铺名": ["ZXU", "SGE"],
                    "店铺类型": ["中企", "本土"],
                    "是否计数": ["是", "否"],
                    "店铺所属部门": ["运营部", "运营部"],
                }
            )
        )

        self.assertEqual(config["停提款时间"].tolist(), ["", ""])

    def test_stop_withdrawal_month_splits_counted_and_stopped_data(self):
        report = normalize_report(
            pd.DataFrame(
                {
                    "销售专员": ["A", "A", "A"],
                    "月份": ["2026-02", "2026-03", "2026-04"],
                    "店铺": ["6-ZXU 德国", "6-ZXU 德国", "6-ZXU 德国"],
                }
            )
        )
        store_config = pd.DataFrame({"店铺名": ["ZXU"], "店铺类型": ["中企"], "停提款时间": ["2026-03"], "店铺所属部门": ["运营部"]})
        merged = merge_business_config(report, store_config, pd.DataFrame())

        counted, stopped = split_counted_and_stopped_data(merged)

        self.assertEqual(counted["月份"].tolist(), ["2026-02"])
        self.assertEqual(stopped["月份"].tolist(), ["2026-03", "2026-04"])

    def test_department_fee_config_accepts_percent_variants(self):
        config = normalize_department_fee_config(
            pd.DataFrame(
                {
                    "月份": ["2026-01", "2026-01", "2026-01"],
                    "部门": ["D1", "D2", "D3"],
                    "费用率": ["8%", "0.08", "8"],
                }
            )
        )

        self.assertTrue((config["费用率"].round(4) == 0.08).all())

    def test_commission_config_keeps_developer_costs_without_fee_rate(self):
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

        self.assertNotIn("费用率", config.columns)
        self.assertTrue((config["职位提点"].round(4) == 0.08).all())

    def test_commission_calculates_by_month_developer_and_marks_missing_config(self):
        report = normalize_report(
            pd.DataFrame(
                {
                    "销售专员": ["A", "A"],
                    "月份": ["2026-01", "2026-02"],
                    "店铺": ["6-ZXU 德国", "6-ZXU 德国"],
                    "部门": ["D1", "D1"],
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
                "库存计提": [5],
                "弃置": [1],
                "职位提点": ["20%"],
            }
        )
        fee_config = pd.DataFrame({"月份": ["2026-01"], "部门": ["D1"], "费用率": ["10%"]})

        result = compute_commission_table(report, self.commission_metrics(), config, fee_config)
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
                    "部门": ["D1"],
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
                "库存计提": [0],
                "弃置": [0],
                "职位提点": ["20%"],
            }
        )
        fee_config = pd.DataFrame({"月份": ["2026-01"], "部门": ["D1"], "费用率": ["10%"]})

        result = compute_commission_table(report, self.commission_metrics(), config, fee_config)

        self.assertAlmostEqual(result.iloc[0]["提成预估"], -1.0)

    def test_commission_uses_department_fee_rates_before_developer_summary(self):
        report = normalize_report(
            pd.DataFrame(
                {
                    "销售专员": ["A", "A"],
                    "月份": ["2026-01", "2026-01"],
                    "店铺": ["6-ZXU 德国", "7-YIP 法国"],
                    "部门": ["联合部门", "运营二十部"],
                    "销售额--FBA销售额": [100, 300],
                    "COD": [0, 0],
                    "毛利润": [30, 90],
                }
            )
        )
        commission = pd.DataFrame(
            {
                "月份": ["2026-01"],
                "开发员": ["A"],
                "库存计提": [40],
                "弃置": [20],
                "职位提点": ["20%"],
            }
        )
        department_fee = pd.DataFrame(
            {
                "月份": ["2026-01", "2026-01"],
                "部门": ["联合部门", "运营二十部"],
                "费用率": ["10%", "20%"],
            }
        )

        result = compute_commission_table(report, self.commission_metrics(), commission, department_fee)

        self.assertAlmostEqual(result.iloc[0]["费用率"], 0.175)
        self.assertAlmostEqual(result.iloc[0]["提成预估"], -2.0)

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

    def test_stopped_commission_calculates_per_store_and_allocates_fixed_costs(self):
        report = normalize_report(
            pd.DataFrame(
                {
                    "销售专员": ["A", "A"],
                    "月份": ["2026-03", "2026-03"],
                    "店铺": ["6-ZXU 德国", "7-YIP 法国"],
                    "销售额--FBA销售额": [100, 300],
                    "COD": [0, 0],
                    "毛利润": [30, 90],
                }
            )
        )
        store_config = pd.DataFrame(
            {
                "店铺名": ["ZXU", "YIP"],
                "店铺类型": ["中企", "本土"],
                "停提款时间": ["2026-03", "2026-03"],
                "店铺所属部门": ["运营部", "运营部"],
            }
        )
        merged = merge_business_config(report, store_config, pd.DataFrame())
        _, stopped = split_counted_and_stopped_data(merged)
        commission = pd.DataFrame(
            {
                "月份": ["2026-03"],
                "开发员": ["A"],
                "库存计提": [40],
                "弃置": [20],
                "职位提点": ["20%"],
            }
        )
        department_fee = pd.DataFrame({"月份": ["2026-03"], "部门": ["运营部"], "费用率": ["10%"]})

        result = compute_stopped_commission_table(stopped, self.commission_metrics(), commission, department_fee).set_index("店铺编码")

        self.assertAlmostEqual(result.loc["ZXU", "库存计提分摊"], 10)
        self.assertAlmostEqual(result.loc["ZXU", "弃置分摊"], 5)
        self.assertAlmostEqual(result.loc["ZXU", "缺提成预估"], 1)
        self.assertAlmostEqual(result.loc["YIP", "库存计提分摊"], 30)
        self.assertAlmostEqual(result.loc["YIP", "弃置分摊"], 15)
        self.assertAlmostEqual(result.loc["YIP", "缺提成预估"], 3)

    def test_stopped_commission_marks_missing_config(self):
        report = normalize_report(
            pd.DataFrame(
                {
                    "销售专员": ["A"],
                    "月份": ["2026-03"],
                    "店铺": ["6-ZXU 德国"],
                    "销售额--FBA销售额": [100],
                    "COD": [0],
                    "毛利润": [30],
                }
            )
        )
        store_config = pd.DataFrame({"店铺名": ["ZXU"], "店铺类型": ["中企"], "停提款时间": ["2026-03"], "店铺所属部门": ["运营部"]})
        merged = merge_business_config(report, store_config, pd.DataFrame())
        _, stopped = split_counted_and_stopped_data(merged)

        department_fee = pd.DataFrame({"月份": ["2026-03"], "部门": ["运营部"], "费用率": ["10%"]})

        result = compute_stopped_commission_table(stopped, self.commission_metrics(), pd.DataFrame(), department_fee)

        self.assertEqual(result.iloc[0]["配置状态"], "缺配置")
        self.assertTrue(pd.isna(result.iloc[0]["缺提成预估"]))


if __name__ == "__main__":
    unittest.main()
