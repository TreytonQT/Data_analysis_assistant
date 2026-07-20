import unittest

import pandas as pd

from dashboard.promotions import (
    PROMOTION_AGED_INVENTORY_COLUMNS,
    PROMOTION_CANDIDATE_COLUMNS,
    PROMOTION_SKU_METRIC_COLUMNS,
    RULE_AGED_90D,
    RULE_SALES_11_20,
    RULE_SALES_21_30,
    RULE_SALES_LE_10,
    build_promotion_candidates,
    build_promotion_sku_metrics,
    promotion_candidates_for_discount,
)


def operational_row(
    sku: str,
    *,
    available: object = 20,
    sales_7d: object = 0,
    sales_30d: object = 0,
    sales_90d: object = 0,
    aged: object = 0,
    asin: str = "ASIN-1",
    developer: str = "开发员A",
) -> dict:
    row = {
        "MSKU": sku,
        "ASIN": asin,
        "开发员": developer,
        "可售": available,
        "7天销量": sales_7d,
        "30天销量": sales_30d,
        "90天销量": sales_90d,
    }
    row.update({column: 0 for column in PROMOTION_AGED_INVENTORY_COLUMNS})
    row[PROMOTION_AGED_INVENTORY_COLUMNS[0]] = aged
    return row


class PromotionDataTests(unittest.TestCase):
    def test_sales_boundaries_use_mutually_exclusive_priority_rules(self):
        source = pd.DataFrame(
            [
                operational_row("sales-10", sales_90d=10, aged=8),
                operational_row("sales-over-10", sales_90d=10.01),
                operational_row("sales-20", sales_90d=20),
                operational_row("sales-over-20", sales_90d=20.01),
                operational_row("sales-30", sales_90d=30, aged=8),
                operational_row("sales-over-30", sales_90d=30.01),
            ]
        )

        result = build_promotion_candidates(source).set_index("sku")

        self.assertEqual(result.loc["sales-10", "rule_key"], RULE_SALES_LE_10)
        self.assertEqual(result.loc["sales-10", "discount_percent"], 10)
        self.assertEqual(result.loc["sales-over-10", "rule_key"], RULE_SALES_11_20)
        self.assertEqual(result.loc["sales-20", "rule_key"], RULE_SALES_11_20)
        self.assertEqual(result.loc["sales-over-20", "rule_key"], RULE_SALES_21_30)
        self.assertEqual(result.loc["sales-30", "rule_key"], RULE_SALES_21_30)
        self.assertNotIn("sales-over-30", result.index)

    def test_aged_inventory_is_only_a_fallback_and_has_no_available_minimum(self):
        source = pd.DataFrame(
            [
                operational_row("low-stock-aged", available=19, sales_90d=5, aged=1),
                operational_row("high-sales-aged", available=20, sales_90d=31, aged=2),
                operational_row("sales-rule-wins", available=20, sales_90d=7, aged=3),
                operational_row("not-candidate", available=19, sales_90d=7, aged=0),
            ]
        )

        result = build_promotion_candidates(source).set_index("sku")

        self.assertEqual(result.loc["low-stock-aged", "rule_key"], RULE_AGED_90D)
        self.assertEqual(result.loc["high-sales-aged", "rule_key"], RULE_AGED_90D)
        self.assertEqual(result.loc["sales-rule-wins", "rule_key"], RULE_SALES_LE_10)
        self.assertNotIn("not-candidate", result.index)

    def test_aged_inventory_sums_all_five_over_90_day_buckets(self):
        row = operational_row("all-aged-buckets", available=0, sales_90d=100)
        for index, column in enumerate(PROMOTION_AGED_INVENTORY_COLUMNS, start=1):
            row[column] = index

        metrics = build_promotion_sku_metrics(pd.DataFrame([row])).iloc[0]
        candidate = build_promotion_candidates(pd.DataFrame([row])).iloc[0]

        self.assertEqual(metrics["aged_inventory_90d"], 15)
        self.assertEqual(candidate["rule_key"], RULE_AGED_90D)

    def test_rows_are_aggregated_by_normalized_msku_before_rules(self):
        source = pd.DataFrame(
            [
                operational_row(
                    "  SKU-A ",
                    available="10",
                    sales_7d="7",
                    sales_30d="30",
                    sales_90d="5",
                    aged="1",
                    asin="ASIN-B",
                    developer="B",
                ),
                operational_row(
                    "ＳＫＵ-A",
                    available="１０",
                    sales_7d="14",
                    sales_30d="60",
                    sales_90d="6",
                    aged="2",
                    asin="ASIN-A",
                    developer="A",
                ),
            ]
        )

        metrics = build_promotion_sku_metrics(source)
        candidates = build_promotion_candidates(source)

        self.assertEqual(metrics["sku"].tolist(), ["SKU-A"])
        row = metrics.iloc[0]
        self.assertEqual(row["asin"], "ASIN-A；ASIN-B")
        self.assertEqual(row["developer"], "A；B")
        self.assertEqual(row["available_inventory"], 20)
        self.assertEqual(row["sales_90d"], 11)
        self.assertEqual(row["aged_inventory_90d"], 3)
        self.assertEqual(row["average_7d"], 3)
        self.assertEqual(row["average_30d"], 3)
        self.assertEqual(row["daily_lift"], 0)
        self.assertEqual(candidates.iloc[0]["rule_key"], RULE_SALES_11_20)

    def test_daily_lift_preserves_negative_values(self):
        source = pd.DataFrame(
            [operational_row("negative-lift", sales_7d=7, sales_30d=60, sales_90d=8)]
        )

        row = build_promotion_candidates(source).iloc[0]

        self.assertEqual(row["average_7d"], 1)
        self.assertEqual(row["average_30d"], 2)
        self.assertEqual(row["daily_lift"], -1)

    def test_empty_source_and_discount_filter_have_stable_contracts(self):
        columns = list(operational_row("empty").keys())
        empty = pd.DataFrame(columns=columns)

        self.assertEqual(tuple(build_promotion_sku_metrics(empty).columns), PROMOTION_SKU_METRIC_COLUMNS)
        self.assertEqual(tuple(build_promotion_candidates(empty).columns), PROMOTION_CANDIDATE_COLUMNS)

        source = pd.DataFrame(
            [
                operational_row("ten", sales_90d=1),
                operational_row("eight", sales_90d=11),
                operational_row("five", sales_90d=21),
            ]
        )
        self.assertEqual(promotion_candidates_for_discount(source, 8)["sku"].tolist(), ["eight"])
        with self.assertRaisesRegex(ValueError, "12"):
            promotion_candidates_for_discount(source, 12)

    def test_missing_source_columns_are_reported(self):
        with self.assertRaisesRegex(ValueError, "90天销量"):
            build_promotion_candidates(pd.DataFrame([{"MSKU": "SKU-A"}]))


if __name__ == "__main__":
    unittest.main()
