import unittest
import io
from datetime import date

import pandas as pd
from openpyxl import Workbook

from dashboard.data_processing import (
    build_available_inventory_monitor_table,
    build_department_performance_tables,
    build_low_margin_product_table,
    build_person_commission_summary,
    build_product_management_table,
    build_replenishment_rating_summary,
    build_replenishment_management_tables,
    build_sales_history_2025_summary,
    build_sales_dashboard_tables,
    build_slow_moving_inventory_table,
    compute_commission_table,
    compute_metric_table,
    compute_stopped_commission_table,
    count_chen_26_onsale_skus,
    duplicate_row_issues,
    merge_business_config,
    normalize_commission_config,
    normalize_available_inventory_monitor,
    normalize_config_number,
    normalize_department_fee_config,
    normalize_department_person_name,
    latest_department_detail_date,
    normalize_product_operational,
    normalize_operational_aging,
    exclude_stopped_store_operational_rows,
    normalize_operational_sales,
    normalize_sales_amount_detail,
    normalize_sales_volume_detail,
    normalize_report,
    normalize_replenishment_targets,
    normalize_replenishment_coverage_rules,
    normalize_replenishment_listing_dates,
    normalize_replenishment_product_tags,
    normalize_replenishment_switches,
    normalize_sales_history_2025,
    with_department_performance_total,
    normalize_store_config,
    product_level_for_daily_sales,
    select_metric_config,
    sort_product_management_table,
    split_counted_and_stopped_data,
)


class DataProcessingTests(unittest.TestCase):
    def test_current_month_partial_range_remains_available_to_dashboards(self):
        report = pd.DataFrame(
            {
                "销售专员": ["A"],
                "月份": ["2026-07-01~2026-07-21"],
                "店铺": ["6-ZXU 德国"],
                "销售额--FBA销售额": [100],
            }
        )

        normalized = normalize_report(report, today=date(2026, 7, 21))

        self.assertEqual(normalized.loc[0, "月份"], "2026-07")

    def test_past_month_partial_range_is_still_excluded_from_dashboards(self):
        report = pd.DataFrame(
            {
                "销售专员": ["A"],
                "月份": ["2026-06-01~2026-06-21"],
                "店铺": ["6-ZXU 德国"],
            }
        )

        normalized = normalize_report(report, today=date(2026, 7, 21))

        self.assertTrue(pd.isna(normalized.loc[0, "月份"]))

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

    def test_grouped_metrics_sum_dirty_numeric_text(self):
        data = pd.DataFrame(
            {
                "销售专员": ["A", "A"],
                "月份": ["2026-01", "2026-01"],
                "店铺": ["6-ZXU 德国", "6-ZXU 德国"],
                "销售额--FBA销售额": ["１，２００.50", "\u00a0￥300元"],
                "COD": ["0", "0"],
            }
        )
        metrics = pd.DataFrame(
            [{"指标名称": "销售额", "显示分组": "开发员分析", "公式": 'range_sum("销售额--FBA销售额", "COD")'}]
        )

        result = compute_metric_table(normalize_report(data), metrics, ["销售专员"]).set_index("销售专员")

        self.assertEqual(result.loc["A", "销售额"], 1500.5)

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

    def test_fixed_monthly_target_scales_with_selected_month_count(self):
        metrics = pd.DataFrame(
            [
                {"指标名称": "销售额目标", "公式": "max([销售额目标])"},
                {
                    "指标名称": "目标完成率",
                    "公式": 'safe_divide(range_sum("销售额--FBA销售额", "COD"), max([销售额目标]))',
                },
            ]
        )
        target_config = pd.DataFrame({"开发员": ["A"], "目标业绩": [200], "目标毛利率": [20]})
        store_config = pd.DataFrame({"店铺名": ["ZXU"], "店铺类型": ["中企"], "店铺所属部门": ["运营部"]})

        for month_count in [1, 3, 7]:
            with self.subTest(month_count=month_count):
                report = normalize_report(
                    pd.DataFrame(
                        {
                            "销售专员": ["A"] * month_count,
                            "月份": [f"2026-{month:02d}" for month in range(1, month_count + 1)],
                            "店铺": ["6-ZXU 德国"] * month_count,
                            "销售额--FBA销售额": [100] * month_count,
                            "COD": [0] * month_count,
                        }
                    )
                )
                merged = merge_business_config(report, store_config, target_config)
                result = compute_metric_table(merged, metrics, ["销售专员"]).iloc[0]

                self.assertEqual(result["销售额目标"], 200 * month_count)
                self.assertAlmostEqual(result["目标完成率"], 0.5)

    def test_missing_monthly_target_remains_missing_in_completion_rate(self):
        report = normalize_report(
            pd.DataFrame(
                {
                    "销售专员": ["B", "B"],
                    "月份": ["2026-01", "2026-02"],
                    "店铺": ["6-ZXU 德国", "6-ZXU 德国"],
                    "销售额--FBA销售额": [100, 100],
                    "COD": [0, 0],
                }
            )
        )
        merged = merge_business_config(report, pd.DataFrame(), pd.DataFrame())
        metrics = pd.DataFrame(
            [
                {"指标名称": "销售额目标", "公式": "max([销售额目标])"},
                {
                    "指标名称": "目标完成率",
                    "公式": 'safe_divide(range_sum("销售额--FBA销售额", "COD"), max([销售额目标]))',
                },
            ]
        )

        result = compute_metric_table(merged, metrics, ["销售专员"]).iloc[0]

        self.assertTrue(pd.isna(result["销售额目标"]))
        self.assertTrue(pd.isna(result["目标完成率"]))

    def test_duplicate_row_issues_reports_exact_duplicate_groups(self):
        frame = pd.DataFrame(
            {
                "msku": ["S1", "S1", "S2", "S2", "S2"],
                "店铺": ["A", "A", "B", "B", "B"],
                "销量": [1, 1, 0, 0, 0],
            }
        )

        issues = duplicate_row_issues(frame)

        self.assertEqual([issue["duplicate_count"] for issue in issues], [1, 2])
        self.assertEqual(issues[0]["row_numbers"], [1, 2])
        self.assertEqual(issues[0]["example"], {"msku": "S1", "店铺": "A", "销量": 1})
        self.assertEqual(duplicate_row_issues(frame.drop_duplicates()), [])

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

    def test_home_metrics_include_stopped_store_profit(self):
        report = normalize_report(
            pd.DataFrame(
                {
                    "销售专员": ["A", "A"],
                    "月份": ["2026-06", "2026-06"],
                    "店铺": ["6-ZXU 德国", "6-SGE 德国"],
                    "毛利润": [100, -30],
                }
            )
        )
        store_config = pd.DataFrame(
            {
                "店铺名": ["ZXU", "SGE"],
                "店铺类型": ["中企", "本土"],
                "停提款时间": ["", "2026-01"],
                "店铺所属部门": ["联合部门", "联合部门"],
            }
        )
        metric = pd.DataFrame([{"指标名称": "毛利润", "显示分组": "总览", "公式": "sum([毛利润])"}])
        merged = merge_business_config(report, store_config, pd.DataFrame())
        counted, stopped = split_counted_and_stopped_data(merged)

        self.assertEqual(compute_metric_table(merged, metric, []).loc[0, "毛利润"], 70)
        self.assertEqual(compute_metric_table(counted, metric, []).loc[0, "毛利润"], 100)
        self.assertEqual(compute_metric_table(stopped, metric, []).loc[0, "毛利润"], -30)

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

    def test_config_number_accepts_excel_and_copy_variants(self):
        result = normalize_config_number(pd.Series(["１，２００.50", "\u00a0￥300元", "(45.5)", "—", "D1"]))

        self.assertEqual(result.iloc[0], 1200.5)
        self.assertEqual(result.iloc[1], 300)
        self.assertEqual(result.iloc[2], -45.5)
        self.assertTrue(pd.isna(result.iloc[3]))
        self.assertTrue(pd.isna(result.iloc[4]))

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

    def test_person_commission_summary_merges_developer_variants_and_adds_total(self):
        report = normalize_report(
            pd.DataFrame(
                {
                    "销售专员": ["运营二十部-陈千潼", "运营二十部-陈千潼-26", "运营六部-陈千潼", "运营二十部-李四"],
                    "月份": ["2026-01", "2026-01", "2026-01", "2026-01"],
                    "店铺": ["6-ZXU 德国", "20-TIS 德国", "7-YIP 法国", "20-AEU 德国"],
                    "部门": ["联合部门", "运营二十部", "联合部门", "运营二十部"],
                    "销售额--FBA销售额": [100, 200, 300, 400],
                    "COD": [0, 0, 0, 0],
                    "毛利润": [30, 60, 90, 120],
                }
            )
        )
        commission = pd.DataFrame(
            {
                "月份": ["2026-01", "2026-01", "2026-01"],
                "开发员": ["运营二十部-陈千潼", "运营二十部-陈千潼-26", "运营六部-陈千潼"],
                "库存计提": [0, 0, 0],
                "弃置": [0, 0, 0],
                "职位提点": ["10%", "10%", "10%"],
            }
        )
        department_fee = pd.DataFrame(
            {
                "月份": ["2026-01", "2026-01"],
                "部门": ["联合部门", "运营二十部"],
                "费用率": ["10%", "10%"],
            }
        )

        result = build_person_commission_summary(report, self.commission_metrics(), commission, department_fee).set_index("人员")

        self.assertAlmostEqual(result.loc["陈千潼", "营业额"], 600)
        self.assertAlmostEqual(result.loc["陈千潼", "毛利润"], 180)
        self.assertAlmostEqual(result.loc["陈千潼", "毛利率"], 0.3)
        self.assertAlmostEqual(result.loc["陈千潼", "提成预估"], 12)
        self.assertEqual(result.loc["陈千潼", "缺配置月份数"], 0)
        self.assertTrue(pd.isna(result.loc["李四", "提成预估"]))
        self.assertEqual(result.loc["李四", "缺配置月份数"], 1)
        self.assertAlmostEqual(result.loc["合计", "营业额"], 1000)
        self.assertAlmostEqual(result.loc["合计", "毛利润"], 300)
        self.assertAlmostEqual(result.loc["合计", "毛利率"], 0.3)
        self.assertAlmostEqual(result.loc["合计", "提成预估"], 12)
        self.assertEqual(result.loc["合计", "缺配置月份数"], 1)

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

    def test_operational_sales_requires_expected_columns(self):
        with self.assertRaisesRegex(ValueError, "运营原始表缺少列"):
            normalize_operational_sales(pd.DataFrame({"MSKU": ["A"]}))

    def test_operational_sales_normalizes_numbers_and_store_codes(self):
        source = pd.DataFrame(
            {
                "MSKU": ["SKU1"],
                "店铺名称": ["6-ZXU 德国,7-YIP 本土法国"],
                "7天销量": ["1,400"],
                "30天销量": ["60"],
                "可售": ["10"],
                "本地库存": [""],
                "昨天销量": ["3"],
                "前天销量": ["2"],
                "上前销量": ["1"],
                "开发员": ["运营二十部-陈千潼-26"],
                "ASIN": ["B001"],
            }
        )

        result = normalize_operational_sales(source).sort_values("店铺编码").reset_index(drop=True)

        self.assertEqual(result["店铺编码"].tolist(), ["YIP", "ZXU"])
        self.assertTrue(result["是否多店铺编码"].all())
        self.assertEqual(result.loc[0, "7天销量"], 1400)
        self.assertEqual(result.loc[0, "本地库存"], 0)
        self.assertTrue(result.loc[0, "是否-26"])

    def test_sales_dashboard_store_summary_uses_confirmed_rules(self):
        source = pd.DataFrame(
            {
                "MSKU": ["SKU1", "SKU2", "SKU3"],
                "店铺名称": ["6-ZXU 德国", "6-ZXU 法国", "7-YIP 本土法国"],
                "7天销量": [14, 7, 21],
                "30天销量": [60, 0, 15],
                "可售": [10, 0, 5],
                "本地库存": [1, 2, 3],
                "0-60天占用资金": ["1,200.5", "300", "50"],
                "61-90天占用资金": [10, 20, 30],
                "465天占用资金": [100, 200, 300],
                "昨天销量": [3, 2, 1],
                "前天销量": [2, 1, 0],
                "上前销量": [1, 0, 0],
                "开发员": ["运营二十部-陈千潼-26", "运营二十部-陈千潼", "运营二十部-李四"],
                "ASIN": ["B001", "B002", "B003"],
            }
        )
        store_config = pd.DataFrame(
            {
                "店铺名": ["ZXU", "YIP"],
                "店铺类型": ["中企", "本土"],
                "停提款时间": ["", "2026-01"],
                "店铺所属部门": ["联合部门", "联合部门"],
            }
        )

        stores = build_sales_dashboard_tables(source, store_config)["stores"].set_index("店铺编码")

        self.assertEqual(stores.loc["ZXU", "在售个数"], 1)
        self.assertEqual(stores.loc["ZXU", "店铺状态"], "正常")
        self.assertEqual(stores.loc["ZXU", "产品数占比"], 1)
        self.assertEqual(stores.loc["ZXU", "昨日订单"], 5)
        self.assertEqual(stores.loc["ZXU", "-26订单"], 3)
        self.assertAlmostEqual(stores.loc["ZXU", "7天日均"], 3)
        self.assertAlmostEqual(stores.loc["ZXU", "30天日均"], 2)
        self.assertEqual(stores.loc["ZXU", "总库存"], 10)
        self.assertEqual(stores.loc["ZXU", "占用资金"], 1830.5)
        self.assertEqual(stores.loc["ZXU", "昨日D值"], 5)
        self.assertEqual(stores.loc["ZXU", "7天D值"], 3)
        self.assertEqual(stores.loc["YIP", "店铺状态"], "已封店")
        self.assertEqual(stores.loc["YIP", "在售个数"], 0)
        self.assertEqual(stores["在售个数"].sum(), 1)

    def test_sales_dashboard_counts_unique_chen_26_onsale_skus(self):
        source = pd.DataFrame(
            {
                "MSKU": ["SKU1", "SKU2", "SKU3", "SKU4"],
                "店铺名称": ["6-ZXU 德国,7-YIP 法国", "6-ZXU 法国", "7-YIP 法国", "20-TIS 德国"],
                "7天销量": [14, 7, 21, 1],
                "30天销量": [60, 0, 15, 2],
                "可售": [10, 0, 5, 8],
                "本地库存": [1, 2, 3, 4],
                "昨天销量": [3, 2, 1, 1],
                "前天销量": [2, 1, 0, 0],
                "上前销量": [1, 0, 0, 0],
                "开发员": ["运营二十部-陈千潼-26", "运营二十部-陈千潼-26", "运营二十部-付凯乐-26", "运营二十部-陈千潼"],
                "ASIN": ["B001", "B002", "B003", "B004"],
            }
        )

        normalized = normalize_operational_sales(source)

        self.assertEqual(count_chen_26_onsale_skus(source), 1)
        self.assertEqual(count_chen_26_onsale_skus(normalized), 1)

    def test_sales_dashboard_does_not_expand_normalized_data_twice(self):
        source = pd.DataFrame(
            {
                "MSKU": ["SKU1"],
                "店铺名称": ["6-ZXU 德国,7-YIP 本土法国"],
                "7天销量": [7],
                "30天销量": [30],
                "可售": [1],
                "本地库存": [0],
                "昨天销量": [1],
                "前天销量": [0],
                "上前销量": [0],
                "开发员": ["A"],
                "ASIN": ["B001"],
            }
        )
        normalized = normalize_operational_sales(source)

        stores = build_sales_dashboard_tables(normalized, pd.DataFrame())["stores"].set_index("店铺编码")

        self.assertEqual(stores.loc["ZXU", "昨日订单"], 1)
        self.assertEqual(stores.loc["YIP", "昨日订单"], 1)
        self.assertEqual(stores["昨日订单"].sum(), 2)

    def test_product_level_boundaries_and_summary(self):
        self.assertEqual(product_level_for_daily_sales(0), "0单")
        self.assertEqual(product_level_for_daily_sales(0.2), "0.2单以下")
        self.assertEqual(product_level_for_daily_sales(0.5), "0.2-0.5单")
        self.assertEqual(product_level_for_daily_sales(1), "0.5-1单")
        self.assertEqual(product_level_for_daily_sales(2), "1-2单")
        self.assertEqual(product_level_for_daily_sales(3), "2-3单")
        self.assertEqual(product_level_for_daily_sales(5), "3-5单")
        self.assertEqual(product_level_for_daily_sales(5.01), "5单以上")

        source = pd.DataFrame(
            {
                "MSKU": ["SKU1", "SKU2", "SKU3"],
                "店铺名称": ["6-ZXU 德国", "6-ZXU 法国", "7-YIP 本土法国"],
                "7天销量": [14, 7, 21],
                "30天销量": [60, 0, 15],
                "可售": [10, 0, 5],
                "本地库存": [1, 2, 3],
                "昨天销量": [3, 2, 1],
                "前天销量": [2, 1, 0],
                "上前销量": [1, 0, 0],
                "开发员": ["A", "B", "C"],
                "ASIN": ["B001", "B002", "B003"],
            }
        )

        levels = build_sales_dashboard_tables(source, pd.DataFrame())["levels"].set_index("产品等级")

        self.assertEqual(levels.loc["0单", "在售个数"], 0)
        self.assertEqual(levels.loc["0单", "昨日订单"], 2)
        self.assertEqual(levels.loc["0.2-0.5单", "在售个数"], 1)
        self.assertEqual(levels.loc["1-2单", "在售个数"], 1)
        self.assertEqual(levels.loc["总计", "在售个数"], 2)
        self.assertAlmostEqual(levels.loc["总计", "30天贡献占比"], 1)

    def product_operational_source(self):
        return pd.DataFrame(
            {
                "ASIN": ["B001", "B001", "B002"],
                "MSKU": ["SKU1", "SKU2", "SKU3"],
                "可售": [10, 20, 0],
                "可售天数": [5, 10, 0],
                "日均销量": [2, 3, 0],
                "昨天销量": [1, 2, 0],
                "前天销量": [3, 4, 0],
                "上前销量": [5, 6, 0],
                "7天销量": [14, 21, 0],
                "14天销量": [28, 42, 0],
                "30天销量": [60, 90, 0],
                "90天销量": [180, 270, 0],
                "开发员": ["A", "B", "C"],
            }
        )

    def gross_profit_source(self):
        return pd.DataFrame(
            {
                "ASIN": ["B001", "B001", "B001", "B002", "B003"],
                "MSKU": ["SKU1", "SKU2", "SKU1", "SKU3", "SKU4"],
                "国家": ["德国", "法国", "美国", "德国", "法国"],
                "开发员": ["A", "B", "A", "C", "D"],
                "销量--FBA销量": [1, 2, 3, 4, 4],
                "销量--FBM销量": [10, 20, 30, 40, 0],
                "销量--多渠道销量": [100, 200, 300, 400, 0],
                "销售额--FBA销售额": [100, 200, 300, 0, 100],
                "销售额--FBM销售额": [10, 20, 30, 0, 0],
                "COD": [0, 0, 0, 0, 0],
                "毛利润": [55, 44, 33, 0, 1],
                "广告费-SD广告": [-5, -4, -3, 0, 0],
                "广告费-SP广告": [-4, -3, -2, 0, 0],
                "广告费-SB广告": [-3, -2, -1, 0, 0],
                "广告费-SBV广告": [-2, -1, 0, 0, 0],
                "广告费--差异分摊": [-1, 0, 0, 0, 0],
            }
        )

    def rating_source(self):
        return pd.DataFrame(
            {
                "ASIN": ["B001", "B001", "B001", "B002", "B002"],
                "国家": ["德国", "德国", "法国", "德国", "法国"],
                "Rating总数": [170, 173, 188, 0, 8],
                "评分": [4.1, 4.3, 3.8, "", 4.6],
            }
        )

    def replenishment_operational_source(self):
        return pd.DataFrame(
            {
                "ASIN": ["B001", "B001", "B002", "B003"],
                "MSKU": ["SKU1", "SKU2", "SKU3", "SKU4"],
                "店铺名称": ["6-ZXU 德国,7-YIP 本土法国", "6-ZXU 德国", "7-YIP 法国", "8-TIS 意大利"],
                "开发员": ["A", "A", "A", "A"],
                "可售": [10, 5, 100, 0],
                "待调仓": [1, 0, 0, 0],
                "调仓中": [1, 0, 0, 0],
                "待入库": [1, 0, 0, 0],
                "采购在途": [2, 1, 0, 0],
                "本地库存": [3, 0, 0, 0],
                "在途": [4, 0, 0, 0],
                "计划入库": [5, 0, 0, 0],
                "91-180天库存数": [1, 0, 0, 0],
                "181-330天库存数": [2, 0, 0, 0],
                "331-365天库存数": [3, 0, 0, 0],
                "366-455天库存数": [4, 0, 0, 0],
                "456天以上库存数": [5, 0, 0, 0],
                "7天销量": [70, 35, 0, 7],
                "14天销量": [140, 70, 0, 14],
                "30天销量": [300, 150, 0, 30],
                "单品重量(g)": [80, 120, 50, 20],
                "上架时间": ["2025-01-01", "2026-07-01", "2025-01-01", "2025-01-01"],
            }
        )

    def available_inventory_monitor_source(self):
        return pd.DataFrame(
            {
                "开发员": ["A", "A", "B"],
                "可售": [10, "20", 100],
                "待调仓": [1, 2, 3],
                "调仓中": [2, 3, 4],
                "待入库": [3, 4, 5],
                "采购在途": [4, 5, 6],
                "本地库存": [5, 6, 7],
                "在途": [6, 7, 8],
                "计划入库": [7, "8", 9],
                "日均销量": [1, "2", 0],
            }
        )

    def test_available_inventory_monitor_requires_expected_columns(self):
        with self.assertRaisesRegex(ValueError, "可售监控列"):
            normalize_available_inventory_monitor(pd.DataFrame({"开发员": ["A"]}))

    def test_available_inventory_monitor_groups_by_developer(self):
        result = normalize_available_inventory_monitor(self.available_inventory_monitor_source()).set_index("开发员")

        self.assertEqual(result.loc["A", "库存总数"], 93)
        self.assertEqual(result.loc["A", "日均单量"], 3)
        self.assertEqual(result.loc["A", "总可售天数"], 31)
        self.assertEqual(result.loc["B", "库存总数"], 142)
        self.assertEqual(result.loc["B", "日均单量"], 0)
        self.assertTrue(pd.isna(result.loc["B", "总可售天数"]))

    def test_available_inventory_monitor_table_uses_developers_as_rows(self):
        result = build_available_inventory_monitor_table(self.available_inventory_monitor_source())

        self.assertEqual(result.columns.tolist(), ["开发员", "库存总数", "日均订单", "总可售天数"])
        indexed = result.set_index("开发员")
        self.assertEqual(indexed.loc["A", "库存总数"], 93)
        self.assertEqual(indexed.loc["A", "日均订单"], 3)
        self.assertEqual(indexed.loc["A", "总可售天数"], 31)

    def department_operational_source(self):
        return pd.DataFrame(
            {
                "MSKU": ["S1", "S2", "S3", "S4", "S5"],
                "店铺名称": ["20-A 德国", "20-B 法国", "6-C 德国,7-D 法国", "7-E 意大利", "20-C 德国"],
                "开发员": ["运营二十部-陈千潼-26", "运营二十部-付凯乐", "运营六部-陈千潼", "运营二十部-杨国梁-26", "运营二十部-付凯乐-26"],
                "可售": [10, 0, 5, 3, 8],
            }
        )

    def department_volume_source(self):
        return pd.DataFrame(
            {
                "msku": ["S1", "S2", "S3", "S4", "S5"],
                "店铺": ["20-A 德国", "20-B 法国", "6-C 德国", "7-E 意大利", "20-C 德国"],
                "开发专员": ["运营二十部-陈千潼-26", "运营二十部-付凯乐", "运营六部-陈千潼", "运营二十部-杨国梁-26", "运营二十部-付凯乐-26"],
                "06-09销量": [999, 999, 999, 999, 999],
                "06-08销量": [7, 1, 2, 4, 3],
                "06-07销量": [7, 1, 2, 4, 3],
                "06-06销量": [7, 1, 2, 4, 3],
                "06-05销量": [7, 1, 2, 4, 3],
                "06-04销量": [7, 1, 2, 4, 3],
                "06-03销量": [7, 1, 2, 4, 3],
                "06-02销量": [7, 1, 2, 4, 3],
                "06-01销量": [1, 1, 1, 1, 1],
            }
        )

    def department_amount_source(self):
        return pd.DataFrame(
            {
                "msku": ["S1", "S2", "S3", "S4", "S5"],
                "店铺": ["20-A 德国", "20-B 法国", "6-C 德国", "7-E 意大利", "20-C 德国"],
                "开发专员": ["运营二十部-陈千潼-26", "运营二十部-付凯乐", "运营六部-陈千潼", "运营二十部-杨国梁-26", "运营二十部-付凯乐-26"],
                "06-09销售额": [9999, 9999, 9999, 9999, 9999],
                "06-08销售额": [70, 14, 7, 100, 21],
                "06-07销售额": [70, 14, 7, 100, 21],
                "06-06销售额": [70, 14, 7, 100, 21],
                "06-05销售额": [70, 14, 7, 100, 21],
                "06-04销售额": [70, 14, 7, 100, 21],
                "06-03销售额": [70, 14, 7, 100, 21],
                "06-02销售额": [70, 14, 7, 100, 21],
                "06-01销售额": [10, 0, 0, 0, 0],
            }
        )

    def test_department_person_name_normalizes_department_and_26_suffix(self):
        self.assertEqual(normalize_department_person_name("运营二十部-陈千潼-26"), "陈千潼")
        self.assertEqual(normalize_department_person_name("运营二十部-付凯乐"), "付凯乐")
        self.assertEqual(normalize_department_person_name("运营二十部－付凯乐－26"), "付凯乐")
        self.assertEqual(normalize_department_person_name("运营六部-陈千潼"), "陈千潼")

    def test_department_performance_total_is_prepended_and_sums_all_rows(self):
        frame = pd.DataFrame(
            [
                {"部门": "联合部门", "在售产品数": 2, "销售额贡献占比": 0.6, "7月12日销量": 10},
                {"部门": "运营二十部", "在售产品数": 3, "销售额贡献占比": 0.4, "7月12日销量": 20},
            ]
        )

        result = with_department_performance_total(frame)

        self.assertEqual(result.iloc[0].to_dict(), {"部门": "合计", "在售产品数": 5, "销售额贡献占比": 1.0, "7月12日销量": 30})
        self.assertEqual(result.iloc[1:].reset_index(drop=True).to_dict(orient="records"), frame.to_dict(orient="records"))

    def test_sales_detail_requires_date_columns(self):
        with self.assertRaisesRegex(ValueError, "日期列"):
            normalize_sales_volume_detail(pd.DataFrame({"msku": ["S1"], "店铺": ["20-A"], "开发专员": ["A"]}))
        with self.assertRaisesRegex(ValueError, "日期列"):
            normalize_sales_amount_detail(pd.DataFrame({"msku": ["S1"], "店铺": ["20-A"], "开发专员": ["A"]}))

    def test_latest_department_detail_date_uses_latest_common_day_and_handles_year_boundary(self):
        volume = pd.DataFrame(columns=["01-02销量", "01-01销量", "12-31销量"])
        amount = pd.DataFrame(columns=["01-02销售额", "12-31销售额", "12-30销售额"])

        result = latest_department_detail_date(volume, amount, reference_date="2026-01-03")

        self.assertEqual(result, pd.Timestamp("2026-01-02"))

    def test_department_performance_tables_default_to_latest_source_date(self):
        tables = build_department_performance_tables(
            self.department_operational_source(),
            self.department_volume_source(),
            self.department_amount_source(),
        )

        self.assertEqual(
            [column for column in tables["开发员业绩排行"].columns if column.endswith("销量")],
            ["6月8日销量", "6月7日销量", "6月6日销量", "6月5日销量", "6月4日销量", "6月3日销量", "6月2日销量"],
        )

    def test_department_performance_ignores_only_completely_duplicate_detail_rows(self):
        volume = self.department_volume_source()
        amount = self.department_amount_source()
        baseline = build_department_performance_tables(
            self.department_operational_source(), volume, amount, today="2026-06-09"
        )
        duplicated = build_department_performance_tables(
            self.department_operational_source(),
            pd.concat([volume, volume.iloc[[0]]], ignore_index=True),
            pd.concat([amount, amount.iloc[[0]]], ignore_index=True),
            today="2026-06-09",
        )

        for key in baseline:
            pd.testing.assert_frame_equal(baseline[key], duplicated[key])

    def test_department_performance_tables_split_stores_and_exclude_today(self):
        tables = build_department_performance_tables(
            self.department_operational_source(),
            self.department_volume_source(),
            self.department_amount_source(),
            today="2026-06-09",
        )

        self.assertEqual(list(tables.keys()), ["开发员业绩排行", "部门业绩"])
        self.assertEqual(
            [column for column in tables["开发员业绩排行"].columns if column.endswith("销量")],
            ["6月8日销量", "6月7日销量", "6月6日销量", "6月5日销量", "6月4日销量", "6月3日销量", "6月2日销量"],
        )
        self.assertNotIn("6月9日销量", tables["开发员业绩排行"].columns)

        developer = tables["开发员业绩排行"].set_index("开发员")
        self.assertEqual(developer.index.tolist(), ["杨国梁", "陈千潼", "付凯乐"])
        self.assertEqual(developer.loc["陈千潼", "在售产品数"], 2)
        self.assertEqual(developer.loc["付凯乐", "在售产品数"], 1)
        self.assertEqual(developer.loc["杨国梁", "在售产品数"], 1)
        self.assertEqual(developer.loc["陈千潼", "近7天日均订单"], 9)
        self.assertEqual(developer.loc["陈千潼", "近7天日均销售额（元）"], 77)
        self.assertEqual(developer.loc["付凯乐", "近7天日均订单"], 4)
        self.assertEqual(developer.loc["付凯乐", "近7天日均销售额（元）"], 35)
        self.assertEqual(developer.loc["杨国梁", "近7天日均销售额（元）"], 100)
        self.assertAlmostEqual(developer.loc["陈千潼", "销售额贡献占比"], 77 / 212)
        self.assertEqual(developer.loc["陈千潼", "预估本月销售额（元）"], 2243)
        self.assertEqual(developer.loc["杨国梁", "6月8日销量"], 4)
        self.assertEqual(developer.loc["杨国梁", "6月8日销售额（元）"], 100)

        department = tables["部门业绩"].set_index("部门")
        self.assertEqual(department.index.tolist(), ["联合部门", "运营二十部"])
        self.assertNotIn("杨国梁", department.index)
        self.assertNotIn("付凯乐", department.index)
        self.assertEqual(department.loc["联合部门", "在售产品数"], 2)
        self.assertEqual(department.loc["运营二十部", "在售产品数"], 2)
        self.assertEqual(department.loc["联合部门", "近7天日均订单"], 6)
        self.assertEqual(department.loc["联合部门", "近7天日均销售额（元）"], 107)
        self.assertEqual(department.loc["运营二十部", "近7天日均订单"], 11)
        self.assertEqual(department.loc["运营二十部", "近7天日均销售额（元）"], 105)
        self.assertAlmostEqual(department.loc["联合部门", "销售额贡献占比"], 107 / 212)

    def replenishment_gross_source(self):
        return pd.DataFrame(
            {
                "ASIN": ["B001", "B001", "B001", "B003"],
                "MSKU": ["SKU1", "SKU2", "SKU2", "SKU4"],
                "国家": ["德国", "德国", "法国", "意大利"],
                "销量--FBA销量": [1, 4, 3, 1],
                "销量--FBM销量": [2, 0, 0, 0],
                "销量--多渠道销量": [3, 0, 0, 0],
                "销售额--FBA销售额": [100, 50, 80, 10],
                "销售额--FBM销售额": [50, 0, 20, 0],
                "COD": [0, 0, 0, 0],
                "毛利润": [30, 10, 30, 1],
                "广告费占比": [0.20, 0.01, 0.02, 0],
                "退款占比": [0.09, 0.01, 0.02, 0],
                "FBA发货费占比": [0.61, 0.20, 0.70, 0],
            }
        )

    def replenishment_rating_source(self):
        return pd.DataFrame(
            {
                "ASIN": ["B001", "B001", "B001", "B003"],
                "国家": ["德国", "法国", "西班牙", "意大利"],
                "Rating总数": [100, 230, 230, 8],
                "评分": [4.0, 4.5, 4.1, 3.9],
            }
        )

    def test_replenishment_targets_normalize_and_dedupe(self):
        result = normalize_replenishment_targets(
            pd.DataFrame({"ASIN": ["B001", "B001", ""], "目标可售天数": ["60", "２１", "70"]})
        )

        self.assertEqual(result.to_dict(orient="records"), [{"ASIN": "B001", "目标可售天数": 21}])

    def test_replenishment_target_can_configure_case_pack_with_default_days(self):
        result = normalize_replenishment_targets(
            pd.DataFrame({"ASIN": ["B001"], "目标可售天数": [pd.NA], "箱规": ["１２"]})
        )

        self.assertEqual(result.loc[0, "ASIN"], "B001")
        self.assertTrue(pd.isna(result.loc[0, "目标可售天数"]))
        self.assertEqual(result.loc[0, "箱规"], 12)

    def test_replenishment_aggregates_skus_and_keeps_excel_pending_inbound_formula(self):
        tables = build_replenishment_management_tables(
            self.replenishment_operational_source(), self.replenishment_gross_source(), self.replenishment_rating_source(),
            store_config=pd.DataFrame({"店铺名": ["6-ZXU"], "店铺类型": ["中企"], "停提款时间": ["2026-01"], "店铺所属部门": ["测试"]}),
            today="2026-07-29", only_needed=False,
        )
        row = tables["detail"].set_index("ASIN").loc["B001"]

        self.assertEqual(row["原SKU"], "SKU1")
        self.assertEqual(row["SKU数量"], 2)
        self.assertEqual(row["最大重量(g)"], 120)
        self.assertEqual(row["库存覆盖天数"], 90)
        self.assertEqual(row["ASIN总库存"], 34)
        self.assertEqual(row["亚马逊可售"], 18)
        self.assertEqual(row["总可售"], 34)
        self.assertEqual(row["跟卖总可售"], 34)
        self.assertAlmostEqual(row["T值"], 0)
        self.assertEqual(row["库龄90天以上"], 15)
        self.assertEqual(row["库龄180-365天"], 5)
        self.assertEqual(row["库龄365天以上"], 9)
        self.assertEqual(row["店铺状态"], "ZXU·停运；YIP·正常")
        self.assertAlmostEqual(row["校准日销量"], 15)
        self.assertEqual(row["目标库存"], 1350)
        self.assertEqual(row["测算建议补货数量"], 1320)
        self.assertEqual(row["建议补货数量"], 1320)
        sku = tables["sku_detail"].set_index("MSKU")
        self.assertEqual(sku.loc["SKU1", "SKU总库存"], 28)
        self.assertEqual(sku.loc["SKU1", "SKU亚马逊可售"], 13)
        self.assertEqual(sku.loc["SKU1", "SKU角色"], "原SKU")

    def test_replenishment_uses_excel_rounding_weight_boundary_and_switch(self):
        source = pd.DataFrame({
            "ASIN": ["B100"], "MSKU": ["S100"], "店铺名称": ["6-ZXU 德国"], "开发员": ["A"],
            "上架时间": ["2025-01-01"], "单品重量(g)": [100], "7天销量": [7], "14天销量": [14], "30天销量": [30],
            "可售": [55], "待调仓": [0], "调仓中": [0], "待入库": [0], "采购在途": [0], "本地库存": [0], "在途": [0], "计划入库": [0],
        })
        tables = build_replenishment_management_tables(source, replenishment_switches=pd.DataFrame({"补货组ID": ["B100"], "是否补货": ["否"], "关闭原因": ["停售"]}), today="2026-07-29", only_needed=False)
        row = tables["detail"].iloc[0]
        self.assertEqual(row["库存覆盖天数"], 90)
        self.assertEqual(row["测算建议补货数量"], 40)
        self.assertEqual(row["建议补货数量"], 0)
        self.assertEqual(row["数据状态"], "已关闭补货")

    def test_replenishment_groups_all_skus_by_asin_and_blocks_missing_inputs(self):
        source = self.replenishment_operational_source()
        source.loc[source["MSKU"].eq("SKU2"), "单品重量(g)"] = pd.NA
        tables = build_replenishment_management_tables(
            source,
            today="2026-07-29", only_needed=False,
        )
        detail = tables["detail"].set_index("补货组ID")
        self.assertNotIn("B001-FOLLOW", detail.index)
        self.assertEqual(detail.loc["B001", "数据状态"], "数据异常")
        self.assertIn("缺少单品重量(g)", detail.loc["B001", "数据异常"])

    def test_replenishment_listing_dates_support_export_formats_without_timezone_shift(self):
        parsed = normalize_replenishment_listing_dates(pd.Series([
            "28/02/2026 05:21:03 MET",
            "04/06/2026 09:01:31 MEST",
            "2026-04-13 04:07:24 CET",
            "2026-04-14 00:05:00 CEST",
            "2026-04-15 23:55:00 GMT",
            45292,
            pd.Timestamp("2026-07-29 23:59:00"),
            "无效日期",
        ]))

        self.assertEqual(parsed.iloc[0], pd.Timestamp("2026-02-28"))
        self.assertEqual(parsed.iloc[1], pd.Timestamp("2026-06-04"))
        self.assertEqual(parsed.iloc[2], pd.Timestamp("2026-04-13"))
        self.assertEqual(parsed.iloc[3], pd.Timestamp("2026-04-14"))
        self.assertEqual(parsed.iloc[4], pd.Timestamp("2026-04-15"))
        self.assertEqual(parsed.iloc[5], pd.Timestamp("2024-01-01"))
        self.assertEqual(parsed.iloc[6], pd.Timestamp("2026-07-29"))
        self.assertTrue(pd.isna(parsed.iloc[7]))

    def test_replenishment_switches_use_asin_and_accept_legacy_group_id(self):
        switches = normalize_replenishment_switches(pd.DataFrame({
            "补货组ID": [" b001 "], "是否补货": ["否"], "关闭原因": ["停售"],
        }))
        self.assertEqual(switches.to_dict(orient="records"), [
            {"ASIN": "B001", "是否补货": False, "关闭原因": "停售"},
        ])
        with self.assertRaisesRegex(ValueError, "关闭原因"):
            normalize_replenishment_switches(pd.DataFrame({
                "ASIN": ["B002"], "是否补货": ["否"], "关闭原因": [""],
            }))

    def test_replenishment_rating_matches_trimmed_case_insensitive_asin(self):
        result = build_replenishment_rating_summary(pd.DataFrame({
            "ASIN": [" b001 ", "B001"], "国家": ["德国", "法国"],
            "Rating总数": [10, 20], "评分": [4.1, 4.7],
        }))
        self.assertEqual(result.to_dict(orient="records"), [
            {"ASIN": "B001", "产品评价数": 20, "产品评分值": 4.7},
        ])

    def test_replenishment_history_and_promotion_are_supporting_data_only(self):
        history = pd.DataFrame([{
            "ASIN": "B001", "DE总销量": 80, "FR总销量": 10, "ES总销量": 5, "IT总销量": 5,
            **{
                key: value
                for month in range(1, 13)
                for key, value in (
                    (f"{month}月总销量", month),
                    (f"{month}月出单天数", 1),
                    (f"{month}月除0日均", float(month)),
                )
            },
        }])
        tables = build_replenishment_management_tables(
            self.replenishment_operational_source(), sales_history_2025=history,
            promotions=pd.DataFrame({
                "sku": ["SKU1"], "start_date": ["2026-07-01"], "end_date": ["2026-08-01"],
                "discount_percent": [10], "promotion_name": ["清仓"],
            }),
            product_tags=pd.DataFrame({
                "ASIN": ["B001", "B001"], "产品标签": ["爆款", "季节品"], "标签颜色": ["#16A34A", ""],
                "是否启用": ["是", "否"], "备注": ["重点", "暂不展示"],
            }),
            today="2026-07-29", only_needed=False,
        )
        self.assertEqual(tables["history"].loc[0, "12月总销量"], 12)
        parent = tables["detail"].set_index("ASIN").loc["B001"]
        self.assertEqual(parent["最近促销开始日期"], "2026-07-01")
        self.assertEqual(parent["最近促销截止日期"], "2026-08-01")
        self.assertEqual(parent["最近促销折扣"], 10)
        self.assertEqual(parent["产品标签"], "爆款")
        self.assertEqual(parent["DE总销量"], 80)
        self.assertNotIn("备注", tables["detail"].columns)
        sku = tables["sku_detail"].set_index("MSKU")
        self.assertEqual(sku.loc["SKU1", "最近促销开始日期"], "2026-07-01")
        self.assertEqual(sku.loc["SKU1", "最近促销截止日期"], "2026-08-01")
        self.assertEqual(sku.loc["SKU1", "最近促销折扣"], 10)
        self.assertEqual(sku.loc["SKU1", "产品标签"], "爆款")
        self.assertNotIn("备注", tables["sku_detail"].columns)

    def test_replenishment_t_value_uses_seven_day_minus_thirty_day_average(self):
        source = self.replenishment_operational_source()
        source.loc[source["ASIN"].eq("B001"), "7天销量"] = [84, 21]
        source.loc[source["ASIN"].eq("B001"), "30天销量"] = [300, 120]
        tables = build_replenishment_management_tables(source, today="2026-07-29", only_needed=False)

        parent = tables["detail"].set_index("ASIN").loc["B001"]
        sku = tables["sku_detail"].set_index("MSKU")
        self.assertAlmostEqual(sku.loc["SKU1", "T值"], 2)
        self.assertAlmostEqual(sku.loc["SKU2", "T值"], -1)
        self.assertAlmostEqual(parent["T值"], 1)

    def test_replenishment_product_tag_validation(self):
        tags = normalize_replenishment_product_tags(pd.DataFrame({
            "ASIN": [" B001 "], "产品标签": [" 爆款 "], "标签颜色": ["#16A34A"], "是否启用": ["是"], "备注": [""],
        }))
        self.assertEqual(tags.loc[0, "ASIN"], "B001")
        self.assertTrue(tags.loc[0, "是否启用"])
        with self.assertRaisesRegex(ValueError, "#RRGGBB"):
            normalize_replenishment_product_tags(pd.DataFrame({
                "ASIN": ["B001"], "产品标签": ["爆款"], "标签颜色": ["green"], "是否启用": ["是"], "备注": [""],
            }))

    def test_replenishment_rule_validation_rejects_overlap_and_history_requires_unique_asin(self):
        with self.assertRaisesRegex(ValueError, "不能重叠"):
            normalize_replenishment_coverage_rules(pd.DataFrame([
                {"运输方式": "空运", "重量下限": 0, "重量上限": 100, "头程时效": 1, "预警天数": 1, "补货频次": 1, "是否启用": "是"},
                {"运输方式": "卡航", "重量下限": 99, "重量上限": None, "头程时效": 1, "预警天数": 1, "补货频次": 1, "是否启用": "是"},
            ]))
        history_row = {
            "ASIN": "B1", "DE总销量": 1, "FR总销量": 0, "ES总销量": 0, "IT总销量": 0,
            **{
                key: 0
                for month in range(1, 13)
                for key in (f"{month}月总销量", f"{month}月出单天数", f"{month}月除0日均")
            },
        }
        with self.assertRaisesRegex(ValueError, "ASIN必须唯一"):
            normalize_sales_history_2025(pd.DataFrame([history_row, history_row]))

    def test_sales_history_workbook_aggregates_daily_before_nonzero_average(self):
        workbook = Workbook()
        workbook.remove(workbook.active)
        for month in range(1, 13):
            sheet = workbook.create_sheet(f"{month}月")
            days = pd.Period(f"2025-{month:02d}").days_in_month
            day_columns = [f"{month:02d}-{day:02d}销量" for day in range(1, days + 1)]
            sheet.append(["asin", "msku", "国家", "小计", *day_columns])
            de_values = [0] * days
            fr_values = [0] * days
            it_values = [0] * days
            if month == 1:
                de_values[0] = 1
                fr_values[0] = 2
            if month == 2:
                it_values[0:2] = [2, 2]
            sheet.append([" b001 ", "SKU-DE", "德国", sum(de_values), *de_values])
            sheet.append(["B001", "SKU-FR", "法国", sum(fr_values), *fr_values])
            sheet.append(["B001", "SKU-IT", "意大利", sum(it_values), *it_values])
            sheet.append(["B001", "SKU-NL", "荷兰", 9, 9, *([0] * (days - 1))])
        buffer = io.BytesIO()
        workbook.save(buffer)

        summary, stats = build_sales_history_2025_summary(buffer.getvalue())
        row = summary.iloc[0]

        self.assertEqual(stats["rows"], 48)
        self.assertEqual(row["DE总销量"], 1)
        self.assertEqual(row["FR总销量"], 2)
        self.assertEqual(row["IT总销量"], 4)
        self.assertEqual(row["1月总销量"], 3)
        self.assertEqual(row["1月出单天数"], 1)
        self.assertEqual(row["1月除0日均"], 3)
        self.assertEqual(row["2月总销量"], 4)
        self.assertEqual(row["2月出单天数"], 2)
        self.assertEqual(row["2月除0日均"], 2)

    def test_product_operational_requires_expected_columns(self):
        with self.assertRaisesRegex(ValueError, "运营原始表缺少产品管理列"):
            normalize_product_operational(pd.DataFrame({"MSKU": ["SKU1"]}))

    def test_product_management_builds_sku_rows_without_asin_summary(self):
        result = build_product_management_table(self.product_operational_source(), self.gross_profit_source(), self.rating_source())

        self.assertEqual(result.columns[:2].tolist(), ["SKU", "ASIN"])
        self.assertEqual(result["SKU"].tolist(), ["SKU1", "SKU2", "SKU3"])
        self.assertEqual(result["ASIN"].tolist(), ["B001", "B001", "B002"])
        self.assertNotIn("行类型", result.columns)
        self.assertIn("Rating", result.columns)
        for country in ["德国", "法国", "西班牙", "意大利"]:
            self.assertNotIn(f"{country}Rating", result.columns)
        self.assertEqual(result.loc[0, "可售数量"], 10)
        self.assertEqual(result.loc[0, "可售天数"], 5)
        self.assertEqual(result.loc[1, "30天销量"], 90)

    def test_product_management_gross_profit_and_rating_metrics(self):
        result = build_product_management_table(self.product_operational_source(), self.gross_profit_source(), self.rating_source())
        sku1 = result[result["SKU"].eq("SKU1")].iloc[0]
        sku2 = result[result["SKU"].eq("SKU2")].iloc[0]

        self.assertEqual(sku1["德国销量"], 111)
        self.assertAlmostEqual(sku1["德国毛利率"], 55 / 110)
        self.assertAlmostEqual(sku1["德国广告费占比"], 15 / 110)
        self.assertAlmostEqual(sku1["销售额"], 440)
        self.assertAlmostEqual(sku1["毛利润"], 88)
        self.assertAlmostEqual(sku1["毛利率"], 88 / 440)
        self.assertEqual(sku1["Rating"], "188(3.8)")
        self.assertEqual(sku2["Rating"], "188(3.8)")
        self.assertEqual(sku2["法国销量"], 222)
        self.assertAlmostEqual(sku2["销售额"], 220)
        self.assertAlmostEqual(sku2["毛利润"], 44)
        self.assertAlmostEqual(sku2["毛利率"], 44 / 220)

    def test_low_margin_product_table_filters_below_threshold(self):
        result = build_low_margin_product_table(self.gross_profit_source())

        self.assertEqual(result.columns.tolist(), ["SKU", "ASIN", "国家", "开发员", "销量", "销售额", "毛利润", "毛利率"])
        self.assertEqual(result["SKU"].tolist(), ["SKU1"])
        row = result.iloc[0]
        self.assertEqual(row["ASIN"], "B001")
        self.assertEqual(row["国家"], "美国")
        self.assertEqual(row["开发员"], "A")
        self.assertEqual(row["销量"], 333)
        self.assertEqual(row["销售额"], 330)
        self.assertEqual(row["毛利润"], 33)
        self.assertAlmostEqual(row["毛利率"], 33 / 330)

    def test_low_margin_product_table_filters_by_developer(self):
        matched = build_low_margin_product_table(self.gross_profit_source(), developers=["A"])
        unmatched = build_low_margin_product_table(self.gross_profit_source(), developers=["B"])

        self.assertEqual(matched["SKU"].tolist(), ["SKU1"])
        self.assertTrue(unmatched.empty)

    def test_low_margin_product_table_sorts_worst_margin_first(self):
        result = build_low_margin_product_table(self.gross_profit_source(), min_sales=0)

        self.assertEqual(result["SKU"].tolist(), ["SKU4", "SKU1"])
        self.assertEqual(result["毛利率"].tolist(), sorted(result["毛利率"].tolist()))

    def test_product_management_sort_uses_sku_table_fields(self):
        result = build_product_management_table(self.product_operational_source(), self.gross_profit_source(), self.rating_source())
        sorted_result = sort_product_management_table(result, "可售数量", ascending=True)

        self.assertEqual(sorted_result["SKU"].tolist(), ["SKU3", "SKU1", "SKU2"])
        self.assertEqual(sorted_result["ASIN"].tolist(), ["B002", "B001", "B001"])

    def test_product_management_sort_normalizes_dirty_numeric_text(self):
        result = build_product_management_table(self.product_operational_source(), self.gross_profit_source(), self.rating_source())
        result["可售数量"] = ["10", "２", "1,000"]
        sorted_result = sort_product_management_table(result, "可售数量", ascending=True)

        self.assertEqual(sorted_result["SKU"].tolist(), ["SKU2", "SKU1", "SKU3"])

    def aging_source(self):
        return pd.DataFrame(
            {
                "MSKU": ["SKU1", "SKU1", "SKU2"],
                "开发员": ["运营二十部-陈千潼", "运营二十部-陈千潼", "运营二十部-李四"],
                "ASIN": ["B001", "B001", "B002"],
                "91-180天库存数": ["10", "1", "0"],
                "181-330天库存数": [20, 0, 0],
                "331-365天库存数": [30, 0, 0],
                "366-455天库存数": [40, 0, 0],
                "456天以上库存数": [50, 0, 0],
                "91-180天占用资金": ["100", "10", "1,000"],
                "181-330天占用资金": [200, "", 0],
                "331-365天占用资金": [300, 0, 0],
                "366-455天占用资金": [400, 0, 0],
                "456天占用资金": [500, 0, 0],
            }
        )

    def test_operational_aging_requires_expected_columns(self):
        with self.assertRaisesRegex(ValueError, "运营原始表缺少库龄列"):
            normalize_operational_aging(pd.DataFrame({"MSKU": ["SKU1"]}))

    def test_operational_aging_normalizes_number_columns(self):
        result = normalize_operational_aging(self.aging_source())

        self.assertEqual(result.loc[0, "91-180天库存数"], 10)
        self.assertEqual(result.loc[1, "181-330天占用资金"], 0)
        self.assertEqual(result.loc[2, "91-180天占用资金"], 1000)

    def test_stopped_store_rows_are_excluded_from_operational_reminders(self):
        source = pd.DataFrame(
            {
                "MSKU": ["KEEP-SKU", "STOP-SKU", "UNCONFIGURED-SKU"],
                "店铺名称": ["1-ZXU 德国", "6-SGE 美国", "3-NEW 英国"],
            }
        )
        store_config = pd.DataFrame(
            {
                "店铺名": ["ZXU", "SGE"],
                "店铺类型": ["中企", "本土"],
                "停提款时间": ["", "2026-01"],
                "店铺所属部门": ["运营部", "运营部"],
            }
        )

        result = exclude_stopped_store_operational_rows(source, store_config)

        self.assertEqual(result["MSKU"].tolist(), ["KEEP-SKU", "UNCONFIGURED-SKU"])

    def test_slow_moving_inventory_calculates_accrual_and_discard_thresholds(self):
        ninety = build_slow_moving_inventory_table(self.aging_source(), "90天以上")
        one_eighty = build_slow_moving_inventory_table(self.aging_source(), "180天以上")
        three_sixty_five = build_slow_moving_inventory_table(self.aging_source(), "365天以上")

        self.assertEqual(ninety["SKU"].tolist(), ["SKU1"])
        row = ninety.iloc[0]
        self.assertEqual(row["91-180天库存数"], 11)
        self.assertEqual(row["90天以上库存数合计"], 151)
        self.assertEqual(row["90天以上占用资金合计"], 1510)
        self.assertAlmostEqual(row["库存计提"], 153.5)
        self.assertAlmostEqual(row["弃置费"], 3171)
        self.assertAlmostEqual(one_eighty.iloc[0]["弃置费"], 2940)
        self.assertAlmostEqual(three_sixty_five.iloc[0]["弃置费"], 1890)

    def test_slow_moving_inventory_rejects_unknown_discard_threshold(self):
        with self.assertRaisesRegex(ValueError, "未知弃置费阈值"):
            build_slow_moving_inventory_table(self.aging_source(), "未知")


if __name__ == "__main__":
    unittest.main()
