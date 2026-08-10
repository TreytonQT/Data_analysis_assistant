from __future__ import annotations

import io
import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.batch_monitor import batch_monitor_revision
from backend.db import DB_PATH, LOCAL_TIMEZONE, connect

from dashboard.data_processing import (
    SALES_HISTORY_GENERIC_COLUMNS,
    SALES_HISTORY_GENERIC_MONTH_COLUMNS,
    SALES_HISTORY_2025_MONTH_COLUMNS,
    SALES_HISTORY_2025_SITE_COLUMNS,
    build_alerts,
    build_department_performance_tables,
    build_low_margin_product_table,
    build_person_commission_summary,
    build_product_management_table,
    build_replenishment_management_tables,
    build_sales_history_monthly_summary,
    build_sales_dashboard_tables,
    build_slow_moving_inventory_table,
    compute_metric_table,
    count_chen_26_onsale_skus,
    duplicate_row_issues,
    exclude_stopped_store_operational_rows,
    load_business_config,
    load_commission_config,
    load_department_fee_config,
    load_metric_config,
    latest_department_detail_date,
    merge_business_config,
    normalize_config_number,
    normalize_operational_sales,
    normalize_rate,
    normalize_replenishment_targets,
    normalize_replenishment_coverage_rules,
    normalize_replenishment_product_tags,
    normalize_replenishment_switches,
    normalize_store_config,
    normalize_sales_amount_detail,
    normalize_sales_volume_detail,
    product_management_display_table,
    read_local_table,
    split_counted_and_stopped_data,
    with_department_performance_total,
)
from dashboard.parquet_cache import (
    clear_parquet_memory_cache,
    load_or_build_parquet,
    revision_digest,
)
from dashboard.report_store import (
    DATA_DIR,
    get_latest_source_path,
    get_sales_history_paths,
    load_reports_from_records,
    load_sales_history_records,
    load_upload_records,
    sales_history_index_path,
)
from app_paths import CONFIG_DIR

SUMMARY_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
PRODUCT_LAUNCH_PRICE_COLUMNS = {
    "de_price": "德国开售价格",
    "fr_price": "法国开售价格",
    "es_price": "西班牙开售价格",
    "it_price": "意大利开售价格",
}
PRODUCT_LAUNCH_COLUMNS = [
    "开售时间",
    "开售天数",
    *PRODUCT_LAUNCH_PRICE_COLUMNS.values(),
]


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    clean = frame.where(pd.notna(frame), None)
    return json.loads(clean.to_json(orient="records", date_format="iso", force_ascii=False))


def _format_metadata(name: str, configured: str | None = None) -> dict[str, Any]:
    configured = (configured or "").strip()
    percent = configured in {"百分比", "percent", "percentage"} or any(
        token in name for token in ("毛利率", "完成率", "占比", "费用率", "提点", "广告费占比", "退款占比")
    )
    amount = not percent and any(
        token in name
        for token in ("销售额", "营业额", "毛利润", "广告费", "成本", "货值", "提成", "计提", "弃置费", "占用资金", "金额")
    )
    integer = configured in {"整数", "integer"} or any(
        token in name for token in ("数量", "库存数", "订单", "销量", "产品数", "SKU数", "ASIN数", "在售个数")
    )
    if percent:
        return {"type": "percent", "format": "percent", "unit": "%", "precision": 2}
    if amount:
        return {"type": "number", "format": "amount", "unit": "万", "precision": 2}
    if integer:
        return {"type": "number", "format": "integer", "unit": "", "precision": 0}
    if configured in {"金额", "amount", "currency"}:
        return {"type": "number", "format": "amount", "unit": "万", "precision": 2}
    if configured in {"数值", "number"}:
        return {"type": "number", "format": "number", "unit": "", "precision": 2}
    return {"type": "string", "format": "text", "unit": "", "precision": 0}


def column_definition(name: str, configured: str | None = None) -> dict[str, Any]:
    return {"key": name, "label": name, **_format_metadata(name, configured), "sortable": True}


def column_definitions(frame: pd.DataFrame, formats: dict[str, str] | None = None) -> list[dict[str, Any]]:
    formats = formats or {}
    definitions = []
    for name in frame.columns:
        definition = column_definition(str(name), formats.get(str(name)))
        if pd.api.types.is_numeric_dtype(frame[name]) and definition["format"] == "text":
            definition.update({"type": "number", "format": "number", "precision": 2})
        definitions.append(definition)
    return definitions


def chart_definition(chart: dict[str, Any] | None, columns: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not chart or not chart.get("x"):
        return None
    lookup = {column["key"]: column for column in columns}
    raw_series = chart.get("series") or ([chart["y"]] if chart.get("y") else [])
    series = []
    for item in raw_series:
        item = {"key": item} if isinstance(item, str) else dict(item)
        key = item.get("key")
        if not key or key not in lookup:
            continue
        metadata = lookup[key]
        series.append(
            {
                "key": key,
                "label": item.get("label") or metadata["label"],
                "type": item.get("type", metadata["type"]),
                "format": item.get("format") or metadata["format"],
                "unit": item.get("unit", metadata["unit"]),
                "precision": item.get("precision", metadata["precision"]),
            }
        )
    if not series:
        return None
    return {"kind": chart.get("kind", "bar"), "x": chart["x"], "series": series}


def section(
    key: str,
    title: str,
    frame: pd.DataFrame,
    chart: dict[str, Any] | None = None,
    formats: dict[str, str] | None = None,
    summary_mode: str | None = None,
    row_serializer: Callable[[pd.DataFrame], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    frame = frame.reset_index(drop=True)
    columns = column_definitions(frame, formats)
    result = {"key": key, "title": title, "frame": frame, "columns": columns, "chart": chart_definition(chart, columns)}
    if summary_mode:
        result["summary_mode"] = summary_mode
    if row_serializer:
        result["row_serializer"] = row_serializer
    return result


def metric(name: str, value: Any, format_name: str = "number") -> dict[str, Any]:
    if pd.isna(value):
        value = None
    elif hasattr(value, "item"):
        value = value.item()
    metadata = _format_metadata(name, format_name)
    return {"name": name, "value": value, **metadata}


def performance_with_total(frame: pd.DataFrame) -> pd.DataFrame:
    return with_department_performance_total(frame)


def selected_values(csv_value: str | None, available: list[str]) -> list[str]:
    if not csv_value:
        return available
    requested = {item.strip() for item in csv_value.split(",") if item.strip()}
    return [item for item in available if item in requested]


def explicit_selected_values(csv_value: str | None, available: list[str]) -> list[str]:
    """Return only values explicitly requested by the UI.

    An omitted multi-select means "all data" for calculation, but should remain
    visually empty so selecting one condition does not require clearing an
    automatically populated list first.
    """

    return selected_values(csv_value, available) if csv_value else []


def source_path(key: str, title: str) -> Path:
    path = get_latest_source_path(key)
    if not path:
        raise HTTPException(404, f"请先到上传中心上传{title}")
    return path


def load_source_frame(key: str, title: str) -> pd.DataFrame:
    if key == "sales_history_rolling":
        paths = get_sales_history_paths()
        if not paths:
            raise HTTPException(404, f"请先到上传中心上传{title}")
        records_frame = load_sales_history_records()
        month_by_path = {
            str(row["保存文件名"]): str(row["月份"])
            for _, row in records_frame.iterrows()
        }
        return load_or_build_parquet(
            "source-sales_history_rolling-raw",
            [sales_history_index_path(), *paths],
            lambda: build_sales_history_monthly_summary(
                [(month_by_path[path.name], path) for path in paths]
            )[0],
        )
    path = source_path(key, title)
    loader = lambda: read_local_table(path)
    return load_or_build_parquet(f"source-{key}-raw", [path], loader)


def warm_source_cache(source_key: str) -> None:
    titles = {
        "operational_sales": "运营原始表",
        "gross_profit": "毛利原始表",
        "rating": "Rating",
        "sales_volume_detail": "销量明细",
        "sales_amount_detail": "销售额明细",
        "sales_history_rolling": "往月销量原始表",
    }
    title = titles.get(source_key)
    if title:
        load_source_frame(source_key, title)


def _report_paths(records_frame: pd.DataFrame) -> list[Path]:
    paths: list[Path] = []
    reports_dir = (DATA_DIR / "reports").resolve()
    for saved_name in records_frame.get("保存文件名", pd.Series(dtype=str)).fillna("").astype(str):
        if not saved_name or Path(saved_name).name != saved_name:
            raise ValueError("业绩索引包含非法保存文件名")
        path = (reports_dir / saved_name).resolve()
        if path.parent != reports_dir:
            raise ValueError("业绩索引文件超出报表目录")
        if path.exists():
            paths.append(path)
    return paths


def load_performance_reports() -> pd.DataFrame:
    upload_records = load_upload_records()
    if upload_records.empty:
        raise HTTPException(404, "请先到上传中心上传业绩报表")
    paths = _report_paths(upload_records)
    if not paths:
        raise HTTPException(404, "没有可读取的历史业绩报表")
    return load_or_build_parquet(
        "performance-reports-normalized",
        paths,
        lambda: load_reports_from_records(upload_records),
    )


def load_home_data() -> pd.DataFrame:
    reports = load_performance_reports()
    store_config, target_config = load_business_config()
    return merge_business_config(reports, store_config, target_config)


def developer_options(frame: pd.DataFrame) -> list[str]:
    if "开发员" not in frame.columns:
        return []
    values = frame["开发员"].fillna("").astype(str).str.strip()
    return sorted(values[values.ne("")].drop_duplicates().tolist())


def metrics_for_group(config: pd.DataFrame, group_name: str, fallback: bool = True) -> pd.DataFrame:
    selected = config[config["显示分组"].isin([group_name, "全部"])].copy()
    if selected.empty and fallback:
        selected = config[config["显示分组"].isin(["总览", "全部"])].copy()
    return selected.drop_duplicates(subset=["指标名称"], keep="first")


def metric_format_lookup(config: pd.DataFrame) -> dict[str, str]:
    return dict(zip(config["指标名称"].astype(str), config["格式"].astype(str)))


def table_row_metrics(frame: pd.DataFrame, formats: dict[str, str]) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    ignored = {"月份", "销售专员", "店铺", "店铺编码", "店铺类型", "停提款时间", "是否停提款数据", "部门"}
    return [metric(column, frame.iloc[0][column], formats.get(column, "number")) for column in frame.columns if column not in ignored]


def _non_empty_options(frame: pd.DataFrame, column: str) -> list[str]:
    if column not in frame.columns:
        return []
    values = frame[column].dropna().astype(str).str.strip()
    return sorted(values[values.ne("")].drop_duplicates().tolist())


def _base_payload(title: str, filters: dict[str, list[str]], selected: dict[str, Any]) -> dict[str, Any]:
    return {"title": title, "filters": filters, "selected": selected, "metrics": [], "sections": [], "message": None}


def _build_overview(developers: str | None, months: str | None, departments: str | None, store_types: str | None) -> dict[str, Any]:
    data = load_home_data()
    available = {
        "developers": _non_empty_options(data, "销售专员"),
        "months": _non_empty_options(data, "月份"),
        "departments": _non_empty_options(data, "部门"),
        "store_types": _non_empty_options(data, "店铺类型"),
    }
    chosen = {
        "developers": selected_values(developers, available["developers"]),
        "months": selected_values(months, available["months"]),
        "departments": selected_values(departments, available["departments"]),
        "store_types": selected_values(store_types, available["store_types"]),
    }
    selected = {
        "developers": explicit_selected_values(developers, available["developers"]),
        "months": explicit_selected_values(months, available["months"]),
        "departments": explicit_selected_values(departments, available["departments"]),
        "store_types": explicit_selected_values(store_types, available["store_types"]),
    }
    payload = _base_payload("经营首页", available, selected)
    filtered = data[
        data["销售专员"].astype(str).isin(chosen["developers"])
        & data["月份"].astype(str).isin(chosen["months"])
        & data["部门"].astype(str).isin(chosen["departments"])
        & data["店铺类型"].astype(str).isin(chosen["store_types"])
    ].copy()
    if filtered.empty:
        payload.update({"has_data": False, "message": "当前筛选条件下没有数据"})
        return payload

    config = load_metric_config()
    formats = metric_format_lookup(config)
    overview_table = compute_metric_table(filtered, metrics_for_group(config, "总览", False), [])
    trend = compute_metric_table(filtered, metrics_for_group(config, "趋势"), ["月份"]).sort_values("月份")
    developer = compute_metric_table(filtered, metrics_for_group(config, "开发员分析"), ["销售专员"])
    if "销售额" in developer.columns:
        developer = developer.sort_values("销售额", ascending=False)
    stores = compute_metric_table(filtered, metrics_for_group(config, "店铺分析"), ["部门", "店铺编码", "店铺类型"])
    if "销售额" in stores.columns:
        stores = stores.sort_values("销售额", ascending=False)
    developer_stores = compute_metric_table(
        filtered,
        metrics_for_group(config, "开发员店铺分析"),
        ["销售专员", "店铺编码", "店铺类型"],
    )
    if "销售额" in developer_stores.columns:
        developer_stores = developer_stores.sort_values("销售额", ascending=False)
        total = pd.to_numeric(developer_stores["销售额"], errors="coerce").sum()
        developer_stores["销售额占比"] = developer_stores["销售额"] / total if total else pd.NA
    counted, _ = split_counted_and_stopped_data(filtered)
    try:
        commission = build_person_commission_summary(
            counted, config, load_commission_config(), load_department_fee_config()
        )
    except (ValueError, KeyError):
        commission = pd.DataFrame()
    payload.update(
        {
            "has_data": True,
            "metrics": table_row_metrics(overview_table, formats),
            "sections": [
                section("trend", "月度趋势", trend, {"x": "月份", "series": ["销售额"], "kind": "line"}, formats),
                section("commission", "所选月份提成金额", commission, formats=formats),
                section("developers", "开发员分析", developer, {"x": "销售专员", "series": ["销售额"]}, formats),
                section("stores", "店铺分析", stores, {"x": "店铺编码", "series": ["销售额"]}, formats),
                section(
                    "developer-stores",
                    "开发员 + 店铺分析",
                    developer_stores,
                    {"x": "店铺编码", "series": ["销售额"]},
                    formats,
                ),
                section("alerts", "异常预警", build_alerts(developer_stores), formats=formats),
            ],
        }
    )
    return payload


def _build_sales(developers: str | None) -> dict[str, Any]:
    raw = load_source_frame("operational_sales", "运营原始表")
    operational = normalize_operational_sales(raw)
    options = developer_options(operational)
    chosen = selected_values(developers, options)
    if options:
        operational = operational[operational["开发员"].isin(chosen)].copy()
    store_config, _ = load_business_config()
    tables = build_sales_dashboard_tables(operational, store_config)
    stores, source = tables["stores"], tables["source"]
    metrics = [] if stores.empty else [
        metric("在售个数", stores["在售个数"].sum(), "integer"),
        metric("-26在售", count_chen_26_onsale_skus(source), "integer"),
        metric("昨日订单", stores["昨日订单"].sum(), "integer"),
        metric("-26订单", stores["-26订单"].sum(), "integer"),
        metric("7天日均", stores["7天日均"].sum()),
        metric("30天日均", stores["30天日均"].sum()),
        metric("总库存", stores["总库存"].sum(), "integer"),
    ]
    return {
        **_base_payload(
            "销量看板",
            {"developers": options},
            {"developers": explicit_selected_values(developers, options)},
        ),
        "has_data": not stores.empty,
        "metrics": metrics,
        "sections": [
            section(
                "stores",
                "店铺明细",
                stores,
                {"x": "店铺编码", "series": ["昨日订单", "30天日均"]},
                summary_mode="sales_stores",
            ),
            section("levels", "产品等级", tables["levels"]),
            section("date-compare", "日期对比", tables["date_compare"]),
        ],
    }


def _build_slow_moving(developers: str | None, threshold: str) -> dict[str, Any]:
    thresholds = ["90天以上", "180天以上", "365天以上"]
    if threshold not in thresholds:
        raise HTTPException(422, "非法库龄范围")
    operational = load_source_frame("operational_sales", "运营原始表")
    store_config, _ = load_business_config()
    operational = exclude_stopped_store_operational_rows(operational, store_config)
    options = developer_options(operational)
    chosen = selected_values(developers, options)
    if options:
        operational = operational[operational["开发员"].astype(str).isin(chosen)].copy()
    detail = build_slow_moving_inventory_table(operational, threshold)
    metrics = [] if detail.empty else [
        metric("滞销SKU数", len(detail), "integer"),
        metric("90天以上库存数", detail["90天以上库存数合计"].sum(), "integer"),
        metric("90天以上占用资金", detail["90天以上占用资金合计"].sum(), "amount"),
        metric("库存计提", detail["库存计提"].sum(), "amount"),
        metric("弃置费", detail["弃置费"].sum(), "amount"),
    ]
    return {
        **_base_payload(
            "滞销提醒",
            {"developers": options, "thresholds": thresholds},
            {"developers": chosen, "threshold": threshold},
        ),
        "has_data": not detail.empty,
        "message": "当前筛选条件下没有对应库龄库存" if detail.empty else None,
        "metrics": metrics,
        "sections": [section("detail", "滞销 SKU 明细", detail)],
    }


def _product_launch_rows() -> pd.DataFrame:
    """Read batch prices with historical price-only values as a fallback."""

    columns = ["SKU", *PRODUCT_LAUNCH_PRICE_COLUMNS.values(), "开售时间"]
    with connect() as conn:
        rows = conn.execute(
            """WITH product_skus AS (
                SELECT sku FROM batch_monitor_skus
                UNION
                SELECT sku FROM sku_first_shipments
                UNION
                SELECT sku FROM sku_launch_prices
            )
            SELECT
                keys.sku AS SKU,
                COALESCE(prices.de_price, legacy.de_price) AS de_price,
                COALESCE(prices.fr_price, legacy.fr_price) AS fr_price,
                COALESCE(prices.es_price, legacy.es_price) AS es_price,
                COALESCE(prices.it_price, legacy.it_price) AS it_price,
                shipments.arrival_date AS 开售时间
            FROM product_skus keys
            LEFT JOIN batch_monitor_skus prices ON prices.sku = keys.sku
            LEFT JOIN sku_launch_prices legacy ON legacy.sku = keys.sku
            LEFT JOIN sku_first_shipments shipments ON shipments.sku = keys.sku
            ORDER BY keys.sku"""
        ).fetchall()
    if not rows:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame([dict(row) for row in rows])
    return frame.rename(columns=PRODUCT_LAUNCH_PRICE_COLUMNS)[columns]


def _normalized_sku_set(frame: pd.DataFrame, column: str) -> set[str]:
    if column not in frame.columns:
        return set()
    return {
        value
        for value in frame[column].fillna("").astype(str).str.strip().str.upper()
        if value
    }


def merge_product_launch_data(
    detail: pd.DataFrame,
    launch_rows: pd.DataFrame,
    *,
    today: date | datetime | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Attach batch-monitor launch data without changing product row cardinality."""

    result = detail.copy()
    result["_launch_row_order"] = range(len(result))
    result["_launch_sku"] = (
        result["SKU"].fillna("").astype(str).str.strip().str.upper()
        if "SKU" in result.columns
        else ""
    )

    launch = launch_rows.copy()
    for column in ["SKU", *PRODUCT_LAUNCH_COLUMNS]:
        if column not in launch.columns:
            launch[column] = pd.NA
    launch["_launch_sku"] = launch["SKU"].fillna("").astype(str).str.strip().str.upper()
    launch = launch[launch["_launch_sku"].ne("")].drop_duplicates("_launch_sku", keep="first")

    arrival = pd.to_datetime(launch["开售时间"], errors="coerce")
    calculation_day = (
        pd.Timestamp(today).normalize()
        if today is not None
        else pd.Timestamp(datetime.now(LOCAL_TIMEZONE).date())
    )
    launch["开售时间"] = arrival.dt.strftime("%Y-%m-%d").where(arrival.notna(), pd.NA)
    launch["开售天数"] = (calculation_day - arrival.dt.normalize()).dt.days.astype("Int64")
    for column in PRODUCT_LAUNCH_PRICE_COLUMNS.values():
        launch[column] = pd.to_numeric(launch[column], errors="coerce")

    result = result.merge(
        launch[["_launch_sku", *PRODUCT_LAUNCH_COLUMNS]],
        on="_launch_sku",
        how="left",
        sort=False,
        validate="many_to_one",
    )
    result = result.sort_values("_launch_row_order", kind="stable")
    result = result.drop(columns=["_launch_row_order", "_launch_sku"])

    preferred = ["SKU", "ASIN", "Rating", "开售时间", "开售天数"]
    ordered = [column for column in preferred if column in result.columns]
    used = set(ordered)
    price_by_sales = {
        f"{country}销量": f"{country}开售价格"
        for country in ("德国", "法国", "西班牙", "意大利")
    }
    for column in result.columns:
        price_column = price_by_sales.get(str(column))
        if price_column and price_column in result.columns and price_column not in used:
            ordered.append(price_column)
            used.add(price_column)
        if column not in used:
            ordered.append(column)
            used.add(column)
    return result[ordered].reset_index(drop=True)


def _batch_monitor_updated_timestamp() -> float:
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT updated_at FROM batch_monitor_meta WHERE key = 'revision'"
            ).fetchone()
        return pd.Timestamp(row["updated_at"]).timestamp() if row else 0.0
    except Exception:
        return 0.0


def _build_products(developers: str | None) -> dict[str, Any]:
    operational = load_source_frame("operational_sales", "运营原始表")
    gross = load_source_frame("gross_profit", "毛利原始表")
    rating = load_source_frame("rating", "Rating")
    options = developer_options(operational)
    chosen = selected_values(developers, options)
    if options:
        operational = operational[operational["开发员"].fillna("").astype(str).str.strip().isin(chosen)].copy()
    operational_skus = _normalized_sku_set(operational, "MSKU")
    detail = merge_product_launch_data(
        product_management_display_table(build_product_management_table(operational, gross, rating)),
        _product_launch_rows(),
    )
    low = build_low_margin_product_table(
        gross,
        developers=chosen or None,
        allowed_skus=operational_skus,
    )
    metrics = [] if detail.empty else [
        metric("ASIN数", detail["ASIN"].nunique(), "integer"),
        metric("SKU数", len(detail), "integer"),
        metric("可售数量", pd.to_numeric(detail["可售数量"], errors="coerce").sum(), "integer"),
        metric("日均销量", pd.to_numeric(detail["日均销量"], errors="coerce").sum()),
        metric("30天销量", pd.to_numeric(detail["30天销量"], errors="coerce").sum(), "integer"),
    ]
    return {
        **_base_payload("产品管理", {"developers": options}, {"developers": chosen}),
        "has_data": not detail.empty,
        "metrics": metrics,
        "sections": [
            section("low-margin", "低毛利率 SKU", low),
            section(
                "detail",
                "产品管理明细",
                detail,
                formats={
                    "开售天数": "整数",
                    **{
                        column: "数值"
                        for column in PRODUCT_LAUNCH_PRICE_COLUMNS.values()
                    },
                },
            ),
        ],
        "_updated_at": _batch_monitor_updated_timestamp(),
    }


def latest_detail_date(volume: pd.DataFrame, amount: pd.DataFrame) -> pd.Timestamp | None:
    return latest_department_detail_date(volume, amount)


def _build_department(month: str | None) -> dict[str, Any]:
    home = load_home_data()
    months = _non_empty_options(home, "月份")
    chosen_month = month if month in months else (months[-1] if months else None)
    commission = pd.DataFrame()
    if chosen_month:
        month_data = home[home["月份"].astype(str).eq(chosen_month)].copy()
        counted, _ = split_counted_and_stopped_data(month_data)
        commission = build_person_commission_summary(
            counted, load_metric_config(), load_commission_config(), load_department_fee_config()
        )
    operational = load_source_frame("operational_sales", "运营原始表")
    volume = load_source_frame("sales_volume_detail", "销量明细")
    amount = load_source_frame("sales_amount_detail", "销售额明细")
    volume_duplicate_count = sum(
        item["duplicate_count"] for item in duplicate_row_issues(normalize_sales_volume_detail(volume))
    )
    amount_duplicate_count = sum(
        item["duplicate_count"] for item in duplicate_row_issues(normalize_sales_amount_detail(amount))
    )
    performance = build_department_performance_tables(operational, volume, amount)
    sections = [section("commission", f"{chosen_month or ''} 人员提成汇总", commission)]
    sections.extend(
        section(
            f"performance-{index}",
            title,
            performance_with_total(frame),
            formats={"库存总数": "整数", "占用资金": "金额"},
        )
        for index, (title, frame) in enumerate(performance.items())
    )
    payload = {
        **_base_payload("部门监控", {"months": months}, {"month": chosen_month}),
        "has_data": any(not frame.empty for frame in performance.values()) or not commission.empty,
        "sections": sections,
    }
    warnings = []
    if volume_duplicate_count:
        warnings.append(
            f"现有销量明细含 {volume_duplicate_count} 条完全重复记录，计算时已自动去重，原始上传文件仍保留"
        )
    if amount_duplicate_count:
        warnings.append(
            f"现有销售额明细含 {amount_duplicate_count} 条完全重复记录，计算时已自动去重，原始上传文件仍保留"
        )
    if warnings:
        payload["warnings"] = warnings
    return payload


def _read_optional_replenishment_config(name: str, normalizer) -> pd.DataFrame:
    path = CONFIG_DIR / f"{name}.csv"
    return normalizer(read_local_table(path)) if path.exists() else normalizer(pd.DataFrame())


def _last_promotion_rows() -> pd.DataFrame:
    try:
        with connect() as conn:
            rows = [dict(row) for row in conn.execute(
                "SELECT sku, promotion_name, discount_percent, start_date, end_date, updated_at FROM sku_last_promotions"
            ).fetchall()]
        return pd.DataFrame(rows)
    except Exception:
        # Promotions are supporting evidence only; a missing snapshot must not
        # prevent replenishment quantity calculation.
        return pd.DataFrame(columns=["sku", "promotion_name", "discount_percent", "start_date", "end_date", "updated_at"])


def _replenishment_base_paths() -> list[Path]:
    paths: list[Path] = []
    for key in ("operational_sales", "gross_profit", "rating"):
        path = get_latest_source_path(key)
        if path:
            paths.append(path)
    for name in ("replenishment_coverage_rules", "replenishment_product_tags", "store_config"):
        path = CONFIG_DIR / f"{name}.csv"
        if path.exists():
            paths.append(path)
    history_index = sales_history_index_path()
    if history_index.exists():
        paths.append(history_index)
    paths.extend(get_sales_history_paths())
    if DB_PATH.exists():
        paths.append(DB_PATH)
    return sorted(set(paths), key=str)


@lru_cache(maxsize=4)
def _cached_replenishment_base_tables(revision: str) -> dict[str, pd.DataFrame]:
    del revision
    operational = load_source_frame("operational_sales", "运营原始表")
    gross = load_source_frame("gross_profit", "毛利原始表") if get_latest_source_path("gross_profit") else pd.DataFrame()
    rating = load_source_frame("rating", "Rating") if get_latest_source_path("rating") else pd.DataFrame()
    history_paths = get_sales_history_paths()
    history = load_source_frame("sales_history_rolling", "往月销量原始表") if history_paths else pd.DataFrame()
    tables = build_replenishment_management_tables(
        operational,
        gross,
        rating,
        coverage_rules=_read_optional_replenishment_config("replenishment_coverage_rules", normalize_replenishment_coverage_rules),
        product_tags=_read_optional_replenishment_config("replenishment_product_tags", normalize_replenishment_product_tags),
        store_config=_read_optional_replenishment_config("store_config", normalize_store_config),
        sales_history_rolling=history if history_paths else None,
        promotions=_last_promotion_rows(),
        only_needed=False,
    )
    tables["history_source"] = "rolling" if history_paths else None
    return tables


def _apply_replenishment_switches(
    detail: pd.DataFrame,
    switches: pd.DataFrame,
) -> pd.DataFrame:
    result = detail.copy()
    if result.empty or switches.empty:
        return result
    switch_lookup = switches.set_index("ASIN")
    group_ids = result["补货组ID"].fillna("").astype(str).str.strip().str.upper()
    configured = group_ids.isin(switch_lookup.index)
    if not configured.any():
        return result
    enabled_lookup = switch_lookup["是否补货"].to_dict()
    reason_lookup = switch_lookup["关闭原因"].to_dict()
    result.loc[configured, "是否补货"] = group_ids[configured].map(enabled_lookup).astype(bool)
    result.loc[configured, "关闭原因"] = group_ids[configured].map(reason_lookup).fillna("")
    disabled = configured & ~result["是否补货"].fillna(False).astype(bool)
    disabled_valid = disabled & ~result["数据状态"].eq("数据异常")
    result.loc[disabled_valid, "建议补货数量"] = 0
    result.loc[disabled_valid, "数据状态"] = "已关闭补货"
    return result


def _replenishment_tables() -> dict[str, pd.DataFrame]:
    paths = _replenishment_base_paths()
    revision = revision_digest("replenishment-base", paths) if paths else "empty"
    base = _cached_replenishment_base_tables(revision)
    switches = _read_optional_replenishment_config(
        "replenishment_switches",
        normalize_replenishment_switches,
    )
    return {
        **base,
        "detail": _apply_replenishment_switches(base["detail"], switches),
    }


def _split_compact(value: Any) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in str(value).split("；") if part.strip()]


def _replenishment_number(value: Any) -> int | float | None:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _history_metadata(source: str | None) -> dict[str, str | None]:
    if source == "rolling":
        return {"source": "rolling", "title": "近12个月销量画像"}
    if source == "legacy_2025":
        return {"source": "legacy_2025", "title": "25年销量画像"}
    return {"source": None, "title": "销量画像"}


def _replenishment_history(
    row: dict[str, Any],
    *,
    include_months: bool = False,
    source: str | None = None,
) -> dict[str, Any]:
    raw_values = [row.get(column) for column in SALES_HISTORY_GENERIC_MONTH_COLUMNS]
    available = any(value is not None and not pd.isna(value) for value in raw_values)
    site_sales = {
        code: (_replenishment_number(row.get(f"{code}总销量")) or 0)
        for code in ("DE", "FR", "ES", "IT")
    }
    if available:
        months = [
            {
                "month": str(row.get(f"历史月份{index}") or ""),
                "total_sales": _replenishment_number(row.get(f"历史{index}月总销量")) or 0,
                "included_days": int(_replenishment_number(row.get(f"历史{index}月计入天数")) or 0),
                "adjusted_daily_average": _replenishment_number(row.get(f"历史{index}月日均销量")) or 0,
            }
            for index in range(1, 13)
            if str(row.get(f"历史月份{index}") or "").strip()
        ]
    else:
        legacy_values = [row.get(column) for column in (*SALES_HISTORY_2025_SITE_COLUMNS, *SALES_HISTORY_2025_MONTH_COLUMNS)]
        available = any(value is not None and not pd.isna(value) for value in legacy_values)
        months = [
            {
                "month": index,
                "total_sales": _replenishment_number(row.get(f"{index}月总销量")) or 0,
                "included_days": int(_replenishment_number(row.get(f"{index}月出单天数")) or 0),
                "adjusted_daily_average": _replenishment_number(row.get(f"{index}月除0日均")) or 0,
            }
            for index in range(1, 13)
        ]
    peak_months = sorted(
        (item for item in months if float(item["total_sales"]) > 0),
        key=lambda item: (
            -float(item["total_sales"]),
            -float(item["adjusted_daily_average"]),
            str(item["month"]),
        ),
    )[:6]
    metadata = _history_metadata(source)
    result: dict[str, Any] = {
        "available": available,
        "site_sales": site_sales,
        "peak_months": peak_months,
        **metadata,
        "period_start": months[0]["month"] if months else None,
        "period_end": months[-1]["month"] if months else None,
    }
    if include_months:
        result["months"] = months
    return result


def _replenishment_group_rows(frame: pd.DataFrame, history_source: str | None = None) -> list[dict[str, Any]]:
    country_columns = {
        "DE": "德国",
        "FR": "法国",
        "ES": "西班牙",
        "IT": "意大利",
    }
    result: list[dict[str, Any]] = []
    for row in records(frame):
        tag_labels = _split_compact(row.get("产品标签"))
        raw_colors = str(row.get("产品标签颜色") or "").split("；")
        tags = [
            {"label": label, "color": raw_colors[index].strip() if index < len(raw_colors) else ""}
            for index, label in enumerate(tag_labels)
        ]
        countries = {
            code: {
                "units": row.get(f"{country}单量"),
                "margin": row.get(f"{country}毛利率"),
                "reasons": _split_compact(row.get(f"{country}原因")),
            }
            for code, country in country_columns.items()
        }
        review_count = _replenishment_number(row.get("产品评价数"))
        rating_score = _replenishment_number(row.get("产品评分值"))
        rating = (
            {"review_count": review_count, "score": rating_score}
            if review_count is not None or rating_score is not None
            else None
        )
        promotion = None
        if any(row.get(column) is not None for column in ("最近促销开始日期", "最近促销截止日期", "最近促销折扣")):
            promotion = {
                "start_date": row.get("最近促销开始日期"),
                "end_date": row.get("最近促销截止日期"),
                "discount_percent": row.get("最近促销折扣"),
            }
        result.append(
            {
                "group_id": str(row.get("补货组ID") or ""),
                "identity": {
                    "asin": str(row.get("ASIN") or ""),
                    "original_sku": str(row.get("原SKU") or ""),
                    "follower_skus": _split_compact(row.get("跟卖SKU")),
                    "sku_count": int(row.get("SKU数量") or 0),
                    "stores": _split_compact(row.get("店铺编码")),
                    "store_statuses": _split_compact(row.get("店铺状态")),
                    "developers": _split_compact(row.get("开发员")),
                    "tags": tags,
                    "rating": rating,
                },
                "countries": countries,
                "inventory": {
                    "amazon_available": row.get("亚马逊可售"),
                    "group_total": row.get("总可售"),
                    "asin_reference_total": row.get("跟卖总可售"),
                    "aged_over_90": row.get("库龄90天以上"),
                    "aged_180_to_365": row.get("库龄180-365天"),
                    "aged_over_365": row.get("库龄365天以上"),
                    "is_split_reference": row.get("总可售") != row.get("跟卖总可售"),
                },
                "trend": {
                    "t_value": row.get("T值"),
                    "calibrated_daily_sales": row.get("校准日销量"),
                    "max_weight_g": row.get("最大重量(g)"),
                    "coverage_days": row.get("库存覆盖天数"),
                },
                "promotion": promotion,
                "history": _replenishment_history(row, source=history_source),
                "recommendation": {
                    "target_inventory": row.get("目标库存"),
                    "measured_quantity": row.get("测算建议补货数量"),
                    "official_quantity": row.get("建议补货数量"),
                    "enabled": bool(row.get("是否补货")),
                    "close_reason": row.get("关闭原因"),
                    "status": row.get("数据状态"),
                    "errors": _split_compact(row.get("数据异常")),
                },
            }
        )
    return result


def _filter_replenishment_detail(
    detail: pd.DataFrame,
    developers: str | None,
    min_qty: int,
    developer_choices: list[str],
) -> pd.DataFrame:
    result = detail[detail["是否补货"].fillna(False).astype(bool)].copy()
    if developers:
        chosen = selected_values(developers, developer_choices)
        result = result[
            result["开发员"].fillna("").astype(str).map(
                lambda value: any(
                    item in [part.strip() for part in value.split("；")]
                    for item in chosen
                )
            )
        ].copy()
    if min_qty > 0:
        quantities = pd.to_numeric(result["建议补货数量"], errors="coerce")
        result = result[quantities.ge(min_qty)].copy()
    return result.reset_index(drop=True)


def _build_replenishment(developers: str | None, min_qty: int = 30) -> dict[str, Any]:
    operational = load_source_frame("operational_sales", "运营原始表")
    options = developer_options(operational)
    chosen = selected_values(developers, options)
    tables = _replenishment_tables()
    detail = _filter_replenishment_detail(tables["detail"], developers, min_qty, options)
    positive = detail[pd.to_numeric(detail["建议补货数量"], errors="coerce").fillna(0).gt(0)]
    metrics = [
        metric("需补货ASIN数", int(positive["补货组ID"].nunique()), "integer"),
        metric("建议补货总量", pd.to_numeric(positive["建议补货数量"], errors="coerce").fillna(0).sum(), "integer"),
        metric("数据异常ASIN数", int(detail["数据状态"].eq("数据异常").sum()), "integer"),
    ]
    return {
        **_base_payload("补货管理", {"developers": options}, {"developers": chosen}),
        "has_data": not detail.empty,
        "message": "当前筛选条件下没有补货组" if detail.empty else None,
        "metrics": metrics,
        "sections": [
            section(
                "detail",
                "ASIN补货汇总",
                detail,
                row_serializer=lambda frame: _replenishment_group_rows(frame, tables.get("history_source")),
            )
        ],
    }


def _revision_paths() -> list[Path]:
    paths = [path for path in CONFIG_DIR.glob("*.csv") if path.is_file()]
    index_path = DATA_DIR / "upload_records.csv"
    if index_path.exists():
        paths.append(index_path)
    upload_records = load_upload_records()
    paths.extend(_report_paths(upload_records))
    for key in ("operational_sales", "gross_profit", "rating", "sales_volume_detail", "sales_amount_detail"):
        path = get_latest_source_path(key)
        if path:
            paths.append(path)
        source_index = DATA_DIR / "sources" / f"{key}_source.csv"
        if source_index.exists():
            paths.append(source_index)
    history_index = sales_history_index_path()
    if history_index.exists():
        paths.append(history_index)
    paths.extend(get_sales_history_paths())
    return sorted(set(paths), key=str)


def dashboard_revision() -> str:
    paths = _revision_paths()
    return revision_digest("dashboard-derived", paths) if paths else "empty"


def _page_revision(page_name: str) -> str:
    base_revision = dashboard_revision()
    if page_name == "products":
        return f"{base_revision}:{batch_monitor_revision()}"
    return base_revision


@lru_cache(maxsize=48)
def _cached_bundle(
    page_name: str,
    developers: str | None,
    months: str | None,
    departments: str | None,
    store_types: str | None,
    threshold: str,
    month: str | None,
    min_qty: int,
    revision: str,
) -> dict[str, Any]:
    del revision
    if page_name == "overview":
        return _build_overview(developers, months, departments, store_types)
    if page_name == "sales":
        return _build_sales(developers)
    if page_name == "slow-moving":
        return _build_slow_moving(developers, threshold)
    if page_name == "products":
        return _build_products(developers)
    if page_name == "department":
        return _build_department(month)
    if page_name == "replenishment":
        return _build_replenishment(developers, min_qty)
    raise HTTPException(404, "未知看板页面")


def clear_dashboard_caches() -> None:
    _cached_bundle.cache_clear()
    _cached_replenishment_base_tables.cache_clear()
    clear_parquet_memory_cache()


def clear_replenishment_view_cache() -> None:
    """Invalidate switch-filtered responses without discarding expensive base calculations."""

    _cached_bundle.cache_clear()


def _bundle(
    page_name: str,
    developers: str | None = None,
    months: str | None = None,
    departments: str | None = None,
    store_types: str | None = None,
    threshold: str = "90天以上",
    month: str | None = None,
    min_qty: int = 30,
) -> dict[str, Any]:
    return _cached_bundle(
        page_name,
        developers,
        months,
        departments,
        store_types,
        threshold,
        month,
        min_qty,
        _page_revision(page_name),
    )


def _sort_key(series: pd.Series, definition: dict[str, Any] | None = None) -> pd.Series:
    definition = definition or {}
    format_name = str(definition.get("format") or "").strip().lower()
    type_name = str(definition.get("type") or "").strip().lower()
    numeric_formats = {"amount", "integer", "number", "currency", "金额", "整数", "数值"}
    if format_name in {"percent", "percentage", "百分比"} or type_name == "percent":
        return normalize_rate(series)
    if format_name in numeric_formats or type_name == "number" or pd.api.types.is_numeric_dtype(series):
        return normalize_config_number(series)

    numeric = normalize_config_number(series)
    populated = series.notna() & series.astype(str).str.strip().ne("")
    if populated.any() and numeric.notna().sum() / populated.sum() >= 0.8:
        return numeric
    return series.fillna("").astype(str).str.casefold()


def _resolve_sort_column(
    frame: pd.DataFrame,
    columns: list[dict[str, Any]] | None,
    sort_by: str,
) -> tuple[Any, dict[str, Any]]:
    requested = sort_by.strip()
    definitions = columns or column_definitions(frame)
    actual_by_key = {str(column): column for column in frame.columns}
    by_key: dict[str, tuple[Any, dict[str, Any]]] = {}
    by_label: dict[str, list[tuple[Any, dict[str, Any]]]] = {}
    for definition in definitions:
        key = str(definition.get("key") or "")
        actual = actual_by_key.get(key)
        if actual is None:
            continue
        by_key[key] = (actual, definition)
        label = str(definition.get("label") or key)
        by_label.setdefault(label, []).append((actual, definition))

    resolved = by_key.get(requested)
    if resolved is None:
        label_matches = by_label.get(requested, [])
        if len(label_matches) > 1:
            raise HTTPException(422, f"排序列标签不唯一，请使用列 key：{sort_by}")
        resolved = label_matches[0] if label_matches else None
    if resolved is None:
        raise HTTPException(422, f"不可按未知列排序：{sort_by}")
    if resolved[1].get("sortable") is False:
        raise HTTPException(422, f"该列不支持排序：{sort_by}")
    return resolved


def _query_frame(
    frame: pd.DataFrame,
    search: str | None = None,
    sort_by: str | None = None,
    sort_order: str = "asc",
    columns: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    result = frame
    if search and search.strip() and not result.empty:
        needle = search.strip()
        mask = pd.Series(False, index=result.index)
        for column in result.columns:
            searchable = result[column].astype("string").fillna("")
            mask |= searchable.str.contains(needle, case=False, regex=False)
        result = result[mask]
    if sort_by:
        if sort_order not in {"asc", "desc"}:
            raise HTTPException(422, "sort_order 只能是 asc 或 desc")
        sort_column, definition = _resolve_sort_column(result, columns, sort_by)
        result = result.sort_values(
            sort_column,
            ascending=sort_order == "asc",
            na_position="last",
            kind="stable",
            key=lambda values: _sort_key(values, definition),
        )
    return result.reset_index(drop=True)


def _sales_store_summary(frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame.empty:
        return None

    def total(column: str) -> float:
        if column not in frame.columns:
            return 0.0
        return float(normalize_config_number(frame[column]).fillna(0).sum())

    onsale = total("在售个数")
    summary: dict[str, Any] = {str(column): None for column in frame.columns}
    summary.update(
        {
            "店铺编码": "合计",
            "店铺类型": "—",
            "店铺状态": "—",
            "在售个数": onsale,
            "产品数占比": float(normalize_rate(frame["产品数占比"]).fillna(0).sum())
            if "产品数占比" in frame.columns
            else 0.0,
            "昨日D值": total("昨日订单") / onsale if onsale else 0.0,
            "7天D值": total("7天日均") / onsale if onsale else 0.0,
        }
    )
    for column in ("昨日订单", "-26订单", "7天日均", "30天日均", "总库存", "占用资金"):
        if column in frame.columns:
            summary[column] = total(column)
    return summary


def _section_summary(frame: pd.DataFrame, mode: str | None) -> dict[str, Any] | None:
    if mode == "sales_stores":
        return _sales_store_summary(frame)
    return None


def _serialized_section(
    model: dict[str, Any],
    page: int = 1,
    page_size: int = SUMMARY_PAGE_SIZE,
    search: str | None = None,
    sort_by: str | None = None,
    sort_order: str = "asc",
) -> dict[str, Any]:
    filtered = _query_frame(model["frame"], search, sort_by, sort_order, model.get("columns"))
    total = len(filtered)
    start = (page - 1) * page_size
    visible = filtered.iloc[start : start + page_size]
    result = {
        "key": model["key"],
        "title": model["title"],
        "columns": model["columns"],
        "rows": records(visible),
        "chart": model["chart"],
        "page": page,
        "page_size": page_size,
        "total": total,
        "paginated": total > page_size,
        "summary": _section_summary(filtered, model.get("summary_mode")),
    }
    row_serializer = model.get("row_serializer")
    if row_serializer:
        result["group_rows"] = row_serializer(visible)
    return result


def _serialize_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value
        for key, value in bundle.items()
        if key not in {"sections", "_updated_at"}
    }
    result["sections"] = [_serialized_section(item) for item in bundle.get("sections", [])]
    replenishment_section = next(
        (item for item in result["sections"] if item.get("key") == "detail" and "group_rows" in item),
        None,
    )
    if replenishment_section:
        result["group_rows"] = replenishment_section["group_rows"]
    result["updated_at"] = max(
        max((path.stat().st_mtime for path in _revision_paths()), default=0),
        float(bundle.get("_updated_at") or 0),
    )
    return result


def _dashboard_response(page_name: str, **filters: Any) -> dict[str, Any]:
    try:
        return _serialize_bundle(_bundle(page_name, **filters))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"看板计算失败：{exc}") from exc


@router.get("/overview")
def overview(
    developers: str | None = None,
    months: str | None = None,
    departments: str | None = None,
    store_types: str | None = None,
):
    return _dashboard_response(
        "overview",
        developers=developers,
        months=months,
        departments=departments,
        store_types=store_types,
    )


@router.get("/sales")
def sales(developers: str | None = None):
    return _dashboard_response("sales", developers=developers)


@router.get("/slow-moving")
def slow_moving(developers: str | None = None, threshold: str = "90天以上"):
    return _dashboard_response("slow-moving", developers=developers, threshold=threshold)


@router.get("/products")
def products(developers: str | None = None):
    return _dashboard_response("products", developers=developers)


@router.get("/department")
def department(month: str | None = None):
    return _dashboard_response("department", month=month)


@router.get("/replenishment")
def replenishment(
    developers: str | None = None,
    min_qty: int = Query(30, ge=0),
):
    return _dashboard_response("replenishment", developers=developers, min_qty=min_qty)


class ReplenishmentSwitchInput(BaseModel):
    is_replenishment: bool
    close_reason: str = ""


@router.put("/replenishment/asins/{asin}/switch")
def update_replenishment_switch(asin: str, payload: ReplenishmentSwitchInput):
    normalized_asin = str(asin or "").strip().upper()
    operational = load_source_frame("operational_sales", "运营原始表")
    available_asins = set(operational["ASIN"].fillna("").astype(str).str.strip().str.upper())
    if not normalized_asin or normalized_asin not in available_asins:
        raise HTTPException(404, "ASIN不存在于当前运营原始表")
    try:
        from backend.config_api import upsert_replenishment_switch

        return upsert_replenishment_switch(
            normalized_asin,
            payload.is_replenishment,
            payload.close_reason,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/replenishment/groups/{group_id}/details")
def replenishment_group_details(group_id: str):
    try:
        tables = _replenishment_tables()
        summary = tables["detail"]
        match = summary[summary["补货组ID"].astype(str).eq(group_id)]
        if match.empty:
            raise HTTPException(404, "补货组不存在")
        sku_detail = tables["sku_detail"]
        sku_detail = sku_detail[sku_detail["补货组ID"].astype(str).eq(group_id)].reset_index(drop=True)
        asin = str(match.iloc[0]["ASIN"]).split("；")[0]
        history = tables["history"]
        history_row = records(history[history["ASIN"].astype(str).eq(asin)].head(1)) if not history.empty else []
        return {
            "group": records(match.head(1))[0],
            "sku_columns": column_definitions(sku_detail),
            "sku_rows": records(sku_detail),
            "sales_history": (
                _replenishment_history(
                    history_row[0],
                    include_months=True,
                    source=tables.get("history_source"),
                )
                if history_row
                else {**_history_metadata(tables.get("history_source")), "available": False, "site_sales": {}, "peak_months": [], "months": [], "period_start": None, "period_end": None}
            ),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"补货组明细读取失败：{exc}") from exc


@router.get("/replenishment/export.xlsx")
def export_replenishment(
    developers: str | None = None,
    min_qty: int = Query(30, ge=0),
):
    try:
        tables = _replenishment_tables()
        operational = load_source_frame("operational_sales", "运营原始表")
        options = developer_options(operational)
        detail = _filter_replenishment_detail(tables["detail"], developers, min_qty, options)
        sku_detail = tables["sku_detail"].copy()
        sku_detail = sku_detail[sku_detail["补货组ID"].isin(set(detail["补货组ID"]))].copy()
        export_detail = detail.drop(columns=SALES_HISTORY_GENERIC_MONTH_COLUMNS, errors="ignore").copy()
        history_source = tables.get("history_source")
        peak_sets = [_replenishment_history(row, source=history_source)["peak_months"] for row in records(detail)]
        for index in range(6):
            export_detail[f"峰值{index + 1}月份"] = [
                peaks[index]["month"] if index < len(peaks) else None
                for peaks in peak_sets
            ]
            export_detail[f"峰值{index + 1}日均销量"] = [
                peaks[index]["adjusted_daily_average"] if index < len(peaks) else None
                for peaks in peak_sets
            ]
            export_detail[f"峰值{index + 1}月销量"] = [
                peaks[index]["total_sales"] if index < len(peaks) else None
                for peaks in peak_sets
            ]
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            export_detail.to_excel(writer, index=False, sheet_name="ASIN补货汇总")
            sku_detail.to_excel(writer, index=False, sheet_name="SKU计算明细")
        buffer.seek(0)
        filename = quote("补货管理导出.xlsx")
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
        )
    except Exception as exc:
        raise HTTPException(422, f"补货导出失败：{exc}") from exc


def _section_model(bundle: dict[str, Any], section_key: str) -> dict[str, Any]:
    for item in bundle.get("sections", []):
        if item["key"] == section_key:
            return item
    raise HTTPException(404, "未知看板区块")


@router.get("/{page_name}/sections/{section_key}")
def dashboard_section(
    page_name: str,
    section_key: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(SUMMARY_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    search: str | None = Query(None, max_length=200),
    sort_by: str | None = Query(None, max_length=100),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    developers: str | None = None,
    months: str | None = None,
    departments: str | None = None,
    store_types: str | None = None,
    threshold: str = "90天以上",
    month: str | None = None,
    min_qty: int = Query(30, ge=0),
):
    try:
        bundle = _bundle(
            page_name,
            developers=developers,
            months=months,
            departments=departments,
            store_types=store_types,
            threshold=threshold,
            month=month,
            min_qty=min_qty,
        )
        return _serialized_section(_section_model(bundle, section_key), page, page_size, search, sort_by, sort_order)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"看板区块读取失败：{exc}") from exc


def _csv_chunks(frame: pd.DataFrame, chunk_size: int = 500) -> Iterator[bytes]:
    yield b"\xef\xbb\xbf"
    header = io.StringIO()
    frame.iloc[:0].to_csv(header, index=False, lineterminator="\n")
    yield header.getvalue().encode("utf-8")
    for start in range(0, len(frame), chunk_size):
        buffer = io.StringIO()
        frame.iloc[start : start + chunk_size].to_csv(buffer, index=False, header=False, lineterminator="\n")
        yield buffer.getvalue().encode("utf-8")


@router.get("/{page_name}/sections/{section_key}/export.csv")
def export_dashboard_section(
    page_name: str,
    section_key: str,
    search: str | None = Query(None, max_length=200),
    sort_by: str | None = Query(None, max_length=100),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    developers: str | None = None,
    months: str | None = None,
    departments: str | None = None,
    store_types: str | None = None,
    threshold: str = "90天以上",
    month: str | None = None,
    min_qty: int = Query(30, ge=0),
):
    try:
        bundle = _bundle(
            page_name,
            developers=developers,
            months=months,
            departments=departments,
            store_types=store_types,
            threshold=threshold,
            month=month,
            min_qty=min_qty,
        )
        model = _section_model(bundle, section_key)
        frame = _query_frame(model["frame"], search, sort_by, sort_order, model.get("columns"))
        filename = quote(f"{model['title']}.csv")
        return StreamingResponse(
            _csv_chunks(frame),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"看板导出失败：{exc}") from exc


@router.get("/cache-stats", include_in_schema=False)
def cache_stats():
    info = _cached_bundle.cache_info()
    return {"hits": info.hits, "misses": info.misses, "size": info.currsize, "max_size": info.maxsize}
