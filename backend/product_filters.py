"""Shared product-monitor filter boundaries."""
from __future__ import annotations

import pandas as pd

MARGIN_BANDS = {
    "negative": (None, 0), "0-5": (0, .05), "5-12": (.05, .12),
    "12-20": (.12, .20), "20-plus": (.20, None),
}


def filter_margin(frame: pd.DataFrame, bands: str, min_sales: float) -> pd.DataFrame:
    selected = bands.split(",") if bands else list(MARGIN_BANDS)[:4]
    if "all" in selected:
        mask = pd.Series(True, index=frame.index)
    else:
        if any(value not in MARGIN_BANDS and value != "missing" for value in selected):
            raise ValueError("未知毛利档位")
        margin = pd.to_numeric(frame["毛利率"], errors="coerce")
        mask = pd.Series(False, index=frame.index)
        for value in selected:
            if value == "missing":
                mask |= margin.isna()
                continue
            lower, upper = MARGIN_BANDS[value]
            match = margin.notna()
            if lower is not None:
                match &= margin.ge(lower)
            if upper is not None:
                match &= margin.lt(upper)
            mask |= match
    return frame.loc[mask & pd.to_numeric(frame["销量"], errors="coerce").ge(min_sales)].copy()


def filter_new_sales(frame: pd.DataFrame, minimum: int | None, maximum: int | None) -> pd.DataFrame:
    if minimum is not None and minimum < 0 or maximum is not None and maximum < 0:
        raise ValueError("销量范围不能为负数")
    if minimum is not None and maximum is not None and minimum >= maximum:
        raise ValueError("销量上限必须大于下限")
    result = frame.copy()
    sales = pd.to_numeric(result["90天销量"], errors="coerce")
    if minimum is not None:
        result = result.loc[sales.ge(minimum)]
    if maximum is not None:
        result = result.loc[sales.loc[result.index].lt(maximum)]
    return result
