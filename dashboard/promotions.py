from __future__ import annotations

import unicodedata
from collections.abc import Iterable

import pandas as pd

from dashboard.data_processing import normalize_config_number


PROMOTION_DISCOUNTS = (10, 8, 5)

RULE_SALES_LE_10 = "sales_le_10"
RULE_SALES_11_20 = "sales_11_20"
RULE_SALES_21_30 = "sales_21_30"
RULE_AGED_90D = "aged_90d"

RULE_DISCOUNT_PERCENT = {
    RULE_SALES_LE_10: 10,
    RULE_SALES_11_20: 8,
    RULE_SALES_21_30: 5,
    RULE_AGED_90D: 5,
}

PROMOTION_AGED_INVENTORY_COLUMNS = (
    "91-180天库存数",
    "181-330天库存数",
    "331-365天库存数",
    "366-455天库存数",
    "456天以上库存数",
)

PROMOTION_SOURCE_COLUMNS = (
    "MSKU",
    "ASIN",
    "开发员",
    "可售",
    "7天销量",
    "30天销量",
    "90天销量",
    *PROMOTION_AGED_INVENTORY_COLUMNS,
)

PROMOTION_SKU_METRIC_COLUMNS = (
    "sku",
    "asin",
    "developer",
    "available_inventory",
    "sales_90d",
    "aged_inventory_90d",
    "average_7d",
    "average_30d",
    "daily_lift",
)

PROMOTION_CANDIDATE_COLUMNS = (
    *PROMOTION_SKU_METRIC_COLUMNS,
    "discount_percent",
    "rule_key",
)

_SOURCE_TO_NORMALIZED = {
    "MSKU": "sku",
    "ASIN": "asin",
    "开发员": "developer",
    "可售": "available_inventory",
    "7天销量": "sales_7d",
    "30天销量": "sales_30d",
    "90天销量": "sales_90d",
}


def normalize_promotion_sku(value: object) -> str:
    """Return the stable MSKU key used by promotion records and candidates."""
    if value is None or pd.isna(value):
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def _normalize_identifier(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def _join_identifiers(values: Iterable[object]) -> str:
    normalized = {_normalize_identifier(value) for value in values}
    return "；".join(sorted(value for value in normalized if value))


def _empty_metrics() -> pd.DataFrame:
    return pd.DataFrame(columns=PROMOTION_SKU_METRIC_COLUMNS)


def _empty_candidates() -> pd.DataFrame:
    return pd.DataFrame(columns=PROMOTION_CANDIDATE_COLUMNS)


def build_promotion_sku_metrics(raw: pd.DataFrame) -> pd.DataFrame:
    """Aggregate raw operational data once per normalized MSKU.

    The input must be the unexpanded operational source. In particular, callers
    should not pass the store-expanded result of ``normalize_operational_sales``.
    """
    missing = [column for column in PROMOTION_SOURCE_COLUMNS if column not in raw.columns]
    if missing:
        raise ValueError(f"运营原始表缺少促销计算列：{', '.join(missing)}")

    if raw.empty:
        return _empty_metrics()

    data = raw.loc[:, PROMOTION_SOURCE_COLUMNS].copy()
    data = data.rename(columns=_SOURCE_TO_NORMALIZED)
    data["sku"] = data["sku"].map(normalize_promotion_sku)
    data["asin"] = data["asin"].map(_normalize_identifier)
    data["developer"] = data["developer"].map(_normalize_identifier)
    data = data[data["sku"].ne("")].copy()
    if data.empty:
        return _empty_metrics()

    numeric_columns = [
        "available_inventory",
        "sales_7d",
        "sales_30d",
        "sales_90d",
        *PROMOTION_AGED_INVENTORY_COLUMNS,
    ]
    for column in numeric_columns:
        data[column] = normalize_config_number(data[column]).fillna(0)

    grouped = (
        data.groupby("sku", as_index=False, sort=True)
        .agg(
            asin=("asin", _join_identifiers),
            developer=("developer", _join_identifiers),
            available_inventory=("available_inventory", "sum"),
            sales_7d=("sales_7d", "sum"),
            sales_30d=("sales_30d", "sum"),
            sales_90d=("sales_90d", "sum"),
            **{
                column: (column, "sum")
                for column in PROMOTION_AGED_INVENTORY_COLUMNS
            },
        )
        .reset_index(drop=True)
    )
    grouped["aged_inventory_90d"] = grouped[list(PROMOTION_AGED_INVENTORY_COLUMNS)].sum(axis=1)
    grouped["average_7d"] = grouped["sales_7d"] / 7
    grouped["average_30d"] = grouped["sales_30d"] / 30
    grouped["daily_lift"] = grouped["average_7d"] - grouped["average_30d"]
    return grouped.loc[:, PROMOTION_SKU_METRIC_COLUMNS].reset_index(drop=True)


def build_promotion_candidates(raw: pd.DataFrame) -> pd.DataFrame:
    """Return mutually exclusive promotion candidates in rule priority order."""
    metrics = build_promotion_sku_metrics(raw)
    if metrics.empty:
        return _empty_candidates()

    available = metrics["available_inventory"] >= 20
    sales_90d = metrics["sales_90d"]
    rule_masks = (
        (RULE_SALES_LE_10, available & sales_90d.le(10)),
        (RULE_SALES_11_20, available & sales_90d.gt(10) & sales_90d.le(20)),
        (RULE_SALES_21_30, available & sales_90d.gt(20) & sales_90d.le(30)),
    )

    candidates = metrics.copy()
    candidates["rule_key"] = pd.NA
    unmatched = pd.Series(True, index=candidates.index)
    for rule_key, mask in rule_masks:
        selected = unmatched & mask
        candidates.loc[selected, "rule_key"] = rule_key
        unmatched &= ~selected

    aged_fallback = unmatched & candidates["aged_inventory_90d"].gt(0)
    candidates.loc[aged_fallback, "rule_key"] = RULE_AGED_90D
    candidates = candidates[candidates["rule_key"].notna()].copy()
    if candidates.empty:
        return _empty_candidates()

    candidates["discount_percent"] = candidates["rule_key"].map(RULE_DISCOUNT_PERCENT).astype(int)
    discount_order = {discount: index for index, discount in enumerate(PROMOTION_DISCOUNTS)}
    candidates["_discount_order"] = candidates["discount_percent"].map(discount_order)
    candidates = candidates.sort_values(["_discount_order", "sku"], kind="stable")
    return candidates.loc[:, PROMOTION_CANDIDATE_COLUMNS].reset_index(drop=True)


def promotion_candidates_for_discount(raw: pd.DataFrame, discount_percent: int) -> pd.DataFrame:
    """Build and filter candidates for one of the supported discount tables."""
    if discount_percent not in PROMOTION_DISCOUNTS:
        allowed = ", ".join(str(value) for value in PROMOTION_DISCOUNTS)
        raise ValueError(f"不支持的促销折扣：{discount_percent}；只允许 {allowed}")
    candidates = build_promotion_candidates(raw)
    return candidates[candidates["discount_percent"].eq(discount_percent)].reset_index(drop=True)
