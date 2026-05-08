from __future__ import annotations

import pandas as pd


def apply_home_filters(
    data: pd.DataFrame,
    months: list[str],
    developers: list[str],
    departments: list[str],
    store_types: list[str],
) -> pd.DataFrame:
    filtered = data.copy()
    if "月份" in filtered.columns:
        filtered = filtered[filtered["月份"].isin(months)] if months else filtered.iloc[0:0]
    if "销售专员" in filtered.columns:
        filtered = filtered[filtered["销售专员"].isin(developers)] if developers else filtered.iloc[0:0]
    if "部门" in filtered.columns:
        filtered = filtered[filtered["部门"].isin(departments)] if departments else filtered.iloc[0:0]
    if "店铺类型" in filtered.columns:
        filtered = filtered[filtered["店铺类型"].isin(store_types)] if store_types else filtered.iloc[0:0]
    return filtered
