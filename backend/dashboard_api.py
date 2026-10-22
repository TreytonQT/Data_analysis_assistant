from __future__ import annotations

import io
import hashlib
import json
import math
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from threading import Lock, Timer
from concurrent.futures import ThreadPoolExecutor
import logging
from typing import Any, Callable, Iterator
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.batch_monitor import batch_monitor_revision
from backend.db import LOCAL_TIMEZONE, connect

from dashboard.data_processing import (
    SALES_HISTORY_GENERIC_COLUMNS,
    SALES_HISTORY_GENERIC_MONTH_COLUMNS,
    SALES_HISTORY_2025_MONTH_COLUMNS,
    SALES_HISTORY_2025_SITE_COLUMNS,
    build_alerts,

    build_department_performance_tables,
    build_department_assessment_report,
    build_low_margin_product_table,
    build_person_commission_summary,
    build_department_commission_monitor,
    build_product_management_table,
    build_new_product_monitor_table,
    build_product_gross_columns,
    build_product_rating_columns,
    normalize_gross_profit_source,
    normalize_rating_source,
    PRODUCT_COUNTRIES,
    build_replenishment_management_tables,
    build_replenishment_site_sales_summary,
    build_sales_history_monthly_summary,
    build_sales_dashboard_tables,
    build_slow_moving_inventory_table,
    compute_metric_table,
    count_26_onsale_skus,
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
    normalize_sku_image_map,
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
from dashboard.derived_table_cache import load_or_build_frame_bundle
from dashboard.promotions import normalize_promotion_sku
from backend.listing_prices import cached_listing_bundle, latest_listing_wide, listing_history, listing_index_path, listing_root, observation_rows
from dashboard.report_store import (
    DATA_DIR,
    department_sales_amount_history_path,
    get_latest_source_path,
    get_sales_history_paths,
    latest_source_index_path,
    load_latest_source_record,
    load_reports_from_records,
    load_sales_history_records,
    load_upload_records,
    sales_history_index_path,
    load_department_sales_amount_history,
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
    integer = configured in {"整数", "integer"} or (
        configured not in {"数值", "number"}
        and any(token in name for token in ("数量", "库存数", "订单", "销量", "产品数", "SKU数", "ASIN数", "在售个数", "折扣"))
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
    rows_serializer: Callable[[pd.DataFrame], list[dict[str, Any]]] | None = None,
    export_frame_serializer: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> dict[str, Any]:
    frame = frame.reset_index(drop=True)
    columns = column_definitions(frame, formats)
    result = {"key": key, "title": title, "frame": frame, "columns": columns, "chart": chart_definition(chart, columns)}
    if summary_mode:
        result["summary_mode"] = summary_mode
    if row_serializer:
        result["row_serializer"] = row_serializer
    if rows_serializer:
        result["rows_serializer"] = rows_serializer
    if export_frame_serializer:
        result["export_frame_serializer"] = export_frame_serializer
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


def performance_section(key: str, title: str, frame: pd.DataFrame) -> dict[str, Any]:
    total_frame = performance_with_total(frame)
    component_fields = ["预估中企原始销售额（元）", "预估本土原始销售额（元）"]
    if not all(field in total_frame.columns for field in component_fields):
        return section(key, title, total_frame, formats={"库存总数": "整数", "占用资金": "金额"})
    components = {
        row["开发员"]: {"enterprise": row[component_fields[0]], "local": row[component_fields[1]]}
        for row in records(total_frame)
    }

    def serialize_rows(visible: pd.DataFrame) -> list[dict[str, Any]]:
        return [{**row, "forecast_sales": components[row["开发员"]]} for row in records(visible)]

    return section(
        key, title, total_frame.drop(columns=component_fields),
        formats={"库存总数": "整数", "占用资金": "金额"},
        rows_serializer=serialize_rows,
    )


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
            "source-sales_history_rolling-raw-v2",
            [sales_history_index_path(), *paths],
            lambda: build_sales_history_monthly_summary(
                [(month_by_path[path.name], path) for path in paths]
            )[0],
        )
    path = source_path(key, title)
    loader = lambda: read_local_table(path)
    return load_or_build_parquet(f"source-{key}-raw", [path], loader)


def _optional_sku_image_map() -> pd.DataFrame:
    """Load the optional SKU image map without making dashboard pages depend on it."""

    path = get_latest_source_path("sku_image_map")
    if not path:
        return pd.DataFrame(columns=["库存SKU", "虚拟SKU", "库存图片链接"])
    try:
        return normalize_sku_image_map(load_source_frame("sku_image_map", "SKU图片映射表"))
    except (OSError, TypeError, ValueError):
        # The mapping is an optional presentation enhancement. A stale or
        # malformed legacy file must not make the business matrices fail.
        return pd.DataFrame(columns=["库存SKU", "虚拟SKU", "库存图片链接"])


def _sku_image_lookup(operational: pd.DataFrame, image_map: pd.DataFrame) -> dict[str, dict[str, str]]:
    """Build a virtual-SKU lookup only for exact operational SKU pairs."""

    required = {"本地SKU", "MSKU"}
    if image_map.empty or not required.issubset(operational.columns):
        return {}

    operational_keys = operational[["本地SKU", "MSKU"]].copy()
    for column in operational_keys.columns:
        operational_keys[column] = operational_keys[column].map(
            lambda value: "" if value is None or pd.isna(value) else str(value).strip()
        )
    operational_keys["_库存SKU关联键"] = operational_keys["本地SKU"].str.upper()
    operational_keys["_虚拟SKU关联键"] = operational_keys["MSKU"].str.upper()
    operational_keys = operational_keys[
        operational_keys["_库存SKU关联键"].ne("")
        & operational_keys["_虚拟SKU关联键"].ne("")
    ].drop_duplicates(["_库存SKU关联键", "_虚拟SKU关联键"])
    if operational_keys.empty:
        return {}

    mapping = image_map.copy()
    mapping["_库存SKU关联键"] = mapping["库存SKU"].str.strip().str.upper()
    mapping["_虚拟SKU关联键"] = mapping["虚拟SKU"].str.strip().str.upper()
    matched = mapping.merge(
        operational_keys[["_库存SKU关联键", "_虚拟SKU关联键"]],
        on=["_库存SKU关联键", "_虚拟SKU关联键"],
        how="inner",
        validate="one_to_one",
    )
    return {
        str(row["_虚拟SKU关联键"]): {
            "url": str(row["库存图片链接"]),
            "inventory_sku": str(row["库存SKU"]),
            "virtual_sku": str(row["虚拟SKU"]),
        }
        for _, row in matched.iterrows()
    }


def _rows_with_sku_images(
    image_lookup: dict[str, dict[str, str]],
    sku_column: str = "SKU",
) -> Callable[[pd.DataFrame], list[dict[str, Any]]]:
    """Create a section row serializer that adds a non-column image field."""

    def serialize(frame: pd.DataFrame) -> list[dict[str, Any]]:
        result = records(frame)
        for row in result:
            value = row.get(sku_column)
            key = "" if value is None or pd.isna(value) else str(value).strip().upper()
            image = image_lookup.get(key)
            row["image"] = dict(image) if image else None
        return result

    return serialize


def _slow_moving_csv_frame(
    image_lookup: dict[str, dict[str, str]],
) -> Callable[[pd.DataFrame], pd.DataFrame]:
    """Flatten the slow-moving matrix identity and image fields for CSV export."""

    identity = [
        "SKU",
        "ASIN",
        "开发员",
        "调价生效日期",
        "本次调价降幅",
        "累计调价降幅",
        "最近限时活动名称",
        "最近促销开始日期",
        "最近促销截止日期",
        "最近促销折扣",
        "库存图片链接",
        "库存SKU",
        "虚拟SKU",
    ]
    overview = ["日均销量", "总库存数", "可售天数", "90天以上库存数合计", "90天以上占用资金合计", "库存计提", "弃置费"]
    stock = ["91-180天库存数", "181-330天库存数", "331-365天库存数", "366-455天库存数", "456天以上库存数"]
    capital = ["91-180天占用资金", "181-330天占用资金", "331-365天占用资金", "366-455天占用资金", "456天占用资金"]
    ordered = identity + overview + stock + capital
    amount_renames = {
        "90天以上占用资金合计": "90天以上占用资金合计（元）",
        "库存计提": "库存计提（元）",
        "弃置费": "弃置费（元）",
        **{column: f"{column}（元）" for column in capital},
        "本次调价降幅": "本次调价降幅（%）",
        "累计调价降幅": "累计调价降幅（%）",
        "最近促销折扣": "最近促销折扣（%）",
        "日均销量": "日均销量（件/天）",
        "总库存数": "总库存数（件）",
        "可售天数": "可售天数（天）",
    }

    def image_value(value: object, field: str) -> object:
        if value is None or pd.isna(value):
            return None
        key = str(value).strip().upper()
        return image_lookup.get(key, {}).get(field)

    def serialize(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        if "日均销量" not in result.columns:
            result["日均销量"] = pd.NA
        result["库存图片链接"] = result["SKU"].map(lambda value: image_value(value, "url"))
        result["库存SKU"] = result["SKU"].map(lambda value: image_value(value, "inventory_sku"))
        result["虚拟SKU"] = result["SKU"].map(lambda value: image_value(value, "virtual_sku"))
        columns = [column for column in ordered if column in result.columns]
        columns.extend(column for column in result.columns if column not in columns)
        return result[columns].rename(columns=amount_renames)

    return serialize


def warm_source_cache(source_key: str) -> None:
    titles = {
        "operational_sales": "运营原始表",
        "gross_profit": "毛利原始表",
        "rating": "Rating",
        "sales_volume_detail": "销量明细",
        "sales_amount_detail": "销售额明细",
        "sales_history_rolling": "往月销量原始表",
        "sku_image_map": "SKU图片映射表",
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
        metric("-26在售", count_26_onsale_skus(source), "integer"),
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
    image_lookup = _sku_image_lookup(operational, _optional_sku_image_map())
    detail = build_slow_moving_inventory_table(operational, threshold)
    detail = merge_slow_moving_promotion_data(detail, _last_promotion_rows())
    from backend.pricing import merge_adjustments
    detail = merge_adjustments(detail)
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
        "sections": [
            section(
                "detail",
                "滞销 SKU 明细",
                detail,
                formats={"日均销量": "数值", "可售天数": "数值"},
                rows_serializer=_rows_with_sku_images(image_lookup),
                export_frame_serializer=_slow_moving_csv_frame(image_lookup),
            )
        ],
    }


SLOW_MOVING_PROMOTION_COLUMNS = [
    "最近限时活动名称",
    "最近促销开始日期",
    "最近促销截止日期",
    "最近促销折扣",
]


def merge_slow_moving_promotion_data(
    detail: pd.DataFrame,
    promotions: pd.DataFrame,
) -> pd.DataFrame:
    """Attach durable last-promotion snapshots without changing slow-SKU rows."""

    result = detail.copy()
    result["_slow_moving_row_order"] = range(len(result))
    result["_promotion_sku"] = (
        result["SKU"].map(normalize_promotion_sku)
        if "SKU" in result.columns
        else ""
    )
    result = result.drop(columns=SLOW_MOVING_PROMOTION_COLUMNS, errors="ignore")

    source = promotions.copy()
    source_columns = {
        "最近限时活动名称": "promotion_name",
        "最近促销开始日期": "start_date",
        "最近促销截止日期": "end_date",
        "最近促销折扣": "discount_percent",
    }
    if "sku" not in source.columns:
        source["sku"] = pd.NA
    for target, source_column in source_columns.items():
        if source_column in source.columns:
            source[target] = source[source_column]
        elif target not in source.columns:
            source[target] = pd.NA
    source["_promotion_sku"] = source["sku"].map(normalize_promotion_sku)
    source = source[source["_promotion_sku"].ne("")].drop_duplicates(
        "_promotion_sku", keep="first"
    )
    for column in ["最近促销开始日期", "最近促销截止日期"]:
        parsed = pd.to_datetime(source[column], errors="coerce")
        source[column] = parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), pd.NA)
    source["最近促销折扣"] = pd.to_numeric(
        source["最近促销折扣"], errors="coerce"
    ).astype("Int64")

    result = result.merge(
        source[["_promotion_sku", *SLOW_MOVING_PROMOTION_COLUMNS]],
        on="_promotion_sku",
        how="left",
        sort=False,
        validate="many_to_one",
    )
    result = result.sort_values("_slow_moving_row_order", kind="stable")
    return result.drop(columns=["_slow_moving_row_order", "_promotion_sku"]).reset_index(drop=True)


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

    preferred = ["SKU", "ASIN", "Rating", "促销折扣", "开发员", "开售时间", "开售天数"]
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


def _active_product_promotion_rows(
    reference_date: date | datetime | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Load current promotion discounts without allowing promotion data to break products."""

    columns = ["SKU", "促销折扣"]
    reference = (
        pd.Timestamp(reference_date).date()
        if reference_date is not None
        else datetime.now(LOCAL_TIMEZONE).date()
    ).isoformat()
    try:
        with connect() as conn:
            rows = conn.execute(
                """SELECT sku, discount_percent
                FROM sku_promotions
                WHERE start_date <= ? AND (end_date IS NULL OR end_date >= ?)
                ORDER BY updated_at DESC, start_date DESC, id DESC""",
                (reference, reference),
            ).fetchall()
    except Exception:
        return pd.DataFrame(columns=columns)

    if not rows:
        return pd.DataFrame(columns=columns)
    promotions = pd.DataFrame([dict(row) for row in rows]).rename(
        columns={"sku": "SKU", "discount_percent": "促销折扣"}
    )
    promotions["SKU"] = promotions["SKU"].map(normalize_promotion_sku)
    promotions = promotions[promotions["SKU"].ne("")].copy()
    promotions["促销折扣"] = pd.to_numeric(promotions["促销折扣"], errors="coerce").astype("Int64")
    return promotions.drop_duplicates("SKU", keep="first")[columns].reset_index(drop=True)


def merge_product_promotion_data(detail: pd.DataFrame, promotions: pd.DataFrame) -> pd.DataFrame:
    """Attach active promotion discounts without changing product row cardinality or order."""

    result = detail.copy()
    result["_product_row_order"] = range(len(result))
    result["_promotion_sku"] = (
        result["SKU"].map(normalize_promotion_sku)
        if "SKU" in result.columns
        else ""
    )

    source = promotions.copy()
    for column in ["SKU", "促销折扣"]:
        if column not in source.columns:
            source[column] = pd.NA
    source["SKU"] = source["SKU"].map(normalize_promotion_sku)
    source = source[source["SKU"].ne("")].drop_duplicates("SKU", keep="first")
    source["促销折扣"] = pd.to_numeric(source["促销折扣"], errors="coerce").astype("Int64")

    result = result.merge(
        source[["SKU", "促销折扣"]].rename(columns={"SKU": "_promotion_sku"}),
        on="_promotion_sku",
        how="left",
        sort=False,
        validate="many_to_one",
    )
    result = result.sort_values("_product_row_order", kind="stable")
    result = result.drop(columns=["_product_row_order", "_promotion_sku"])
    from backend.pricing import merge_adjustments
    return merge_adjustments(result.reset_index(drop=True))


def _batch_monitor_updated_timestamp() -> float:
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT updated_at FROM batch_monitor_meta WHERE key = 'revision'"
            ).fetchone()
        return pd.Timestamp(row["updated_at"]).timestamp() if row else 0.0
    except Exception:
        return 0.0


def merge_listing_price_data(detail: pd.DataFrame) -> pd.DataFrame:
    result = detail.copy()
    try:
        source = latest_listing_wide()
    except Exception:
        source = pd.DataFrame()
    if source.empty or "SKU" not in result.columns:
        return result
    result["_listing_sku"] = result["SKU"].fillna("").astype(str).str.strip().str.upper()
    source["_listing_sku"] = source["MSKU"].fillna("").astype(str).str.strip().str.upper()
    source = source.drop_duplicates("_listing_sku", keep="last")
    country_names = {"DE": "德国", "FR": "法国", "ES": "西班牙", "IT": "意大利"}
    selected = ["_listing_sku"]
    renames = {}
    for code, country in country_names.items():
        for field, label in (
            (f"{code}_当前实际总价", f"{country}Listing当前实际总价"),
            (f"{code}_Listing原价", f"{country}Listing原价"),
            (f"{code}_Listing优惠价", f"{country}Listing优惠价"),
            (f"{code}_较开售价变化", f"{country}较开售价变化"),
        ):
            if field in source.columns:
                selected.append(field)
                renames[field] = label
    if len(selected) == 1:
        return result.drop(columns=["_listing_sku"])
    merged = result.merge(source[selected].rename(columns=renames), on="_listing_sku", how="left", sort=False, validate="many_to_one")
    return merged.drop(columns=["_listing_sku"])


NEW_PRODUCT_LAUNCH_STAGES = {"all", "0-6", "7-29", "30-59", "60-100"}
NEW_PRODUCT_STATUSES = {"all", "raise", "lower", "normal", "out_of_stock", "observing", "invalid"}
NEW_PRODUCT_STATUS_LABELS = {
    "raise": "建议涨价",
    "lower": "建议降价",
    "normal": "正常",
    "out_of_stock": "已断货",
    "observing": "新品观察中",
    "invalid": "数据异常",
}


def _new_product_business_day() -> date:
    return datetime.now(LOCAL_TIMEZONE).date()


def _new_product_source_paths() -> list[Path]:
    """Only these sources affect new-product calculations and presentation."""

    paths: set[Path] = set()
    for key in ("operational_sales", "gross_profit", "rating", "sku_image_map"):
        index = latest_source_index_path(key)
        if index.exists():
            paths.add(index)
        source = get_latest_source_path(key)
        if source and source.exists():
            paths.add(source)
    return sorted(paths, key=str)


def _new_product_revision() -> str:
    sources = revision_digest("new-product-sources-v1", _new_product_source_paths())
    return f"{sources}:{batch_monitor_revision()}"


_NEW_PRODUCT_BASE_LOCK = Lock()


@lru_cache(maxsize=2)
def _cached_new_product_base(revision: str, business_day: str) -> dict[str, Any]:
    """Aggregate and enrich once per source revision and business date."""

    del revision
    operational = load_source_frame("operational_sales", "运营原始表")
    options = developer_options(operational)
    detail = build_new_product_monitor_table(
        operational, _product_launch_rows(), reference_date=date.fromisoformat(business_day)
    )
    excluded_launch_count = int(detail.attrs.get("excluded_invalid_launch_count", 0))
    excluded_by_developer = detail.attrs.get("excluded_invalid_launch_by_developer", {})
    context_columns: list[str] = []
    if not detail.empty:
        try:
            gross = normalize_gross_profit_source(load_source_frame("gross_profit", "毛利原始表"))
            gross_rows = build_product_gross_columns(gross, ["ASIN", "MSKU"]).rename(columns={"MSKU": "SKU"})
            gross_rows["_sku_key"] = gross_rows["SKU"].fillna("").astype(str).str.strip().str.upper()
            gross_rows["_asin_key"] = gross_rows["ASIN"].fillna("").astype(str).str.strip().str.upper()
            context_columns.extend(
                column
                for country in PRODUCT_COUNTRIES
                for column in (f"{country}销量", f"{country}毛利率")
                if column in gross_rows.columns
            )
            gross_rows = gross_rows.drop_duplicates(["_sku_key", "_asin_key"], keep="first")
            detail["_sku_key"] = detail["SKU"].fillna("").astype(str).str.strip().str.upper()
            detail["_asin_key"] = detail["ASIN"].fillna("").astype(str).str.strip().str.upper()
            detail = detail.merge(
                gross_rows[["_sku_key", "_asin_key", *context_columns]],
                on=["_sku_key", "_asin_key"],
                how="left",
                validate="many_to_one",
            ).drop(columns=["_sku_key", "_asin_key"])
        except Exception:
            context_columns = []
        try:
            rating = normalize_rating_source(load_source_frame("rating", "Rating"))
            rating_rows = build_product_rating_columns(rating)
            if "Rating" in rating_rows.columns:
                detail = detail.merge(rating_rows, on="ASIN", how="left", validate="many_to_one")
                context_columns.append("Rating")
        except Exception:
            pass

    image_lookup: dict[str, dict[str, str]] = {}
    try:
        image_lookup = _sku_image_lookup(operational, _optional_sku_image_map())
    except Exception:
        pass

    source_records = load_latest_source_record("operational_sales")
    source_uploaded_at = None
    if not source_records.empty:
        uploaded_value = source_records.iloc[-1].get("上传时间")
        if not pd.isna(uploaded_value):
            source_uploaded_at = str(uploaded_value).strip() or None
    updated_at = max(
        [float(_batch_monitor_updated_timestamp() or 0),
         *(path.stat().st_mtime for path in _new_product_source_paths())]
    )
    return {
        "detail": detail,
        "developers": options,
        "context_columns": context_columns,
        "image_lookup": image_lookup,
        "source_uploaded_at": source_uploaded_at,
        "excluded_invalid_launch_count": excluded_launch_count,
        "excluded_invalid_launch_by_developer": excluded_by_developer,
        "updated_at": updated_at,
    }


def _new_product_base(revision: str, business_day: str) -> dict[str, Any]:
    # lru_cache alone allows duplicate concurrent misses. Keep cold requests
    # for summary, copy lists and details on the same single calculation.
    with _NEW_PRODUCT_BASE_LOCK:
        return _cached_new_product_base(revision, business_day)


@lru_cache(maxsize=32)
def _cached_new_product_bundle(
    developers: str | None,
    launch_stage: str,
    status: str,
    search: str | None,
    revision: str,
    business_day: str,
) -> dict[str, Any]:
    base = _new_product_base(revision, business_day)
    detail = base["detail"]
    options = base["developers"]
    chosen = selected_values(developers, options)
    excluded_launch_count = base["excluded_invalid_launch_count"]
    if options:
        chosen_developers = set(chosen)
        excluded_by_developer = base["excluded_invalid_launch_by_developer"]
        if developers:
            excluded_launch_count = sum(
                bool(chosen_developers.intersection(names))
                for names in excluded_by_developer.values()
            )
        detail_developers = detail["开发员"].fillna("").astype(str)
        selected_rows = detail_developers.map(
            lambda value: bool(chosen_developers.intersection(
                name.strip() for name in value.split("；") if name.strip()
            ))
        )
        detail = detail[selected_rows].copy()
    stage_bounds = {
        "0-6": (0, 6),
        "7-29": (7, 29),
        "30-59": (30, 59),
        "60-100": (60, 100),
    }
    if launch_stage not in NEW_PRODUCT_LAUNCH_STAGES:
        raise HTTPException(422, "未知新品开售阶段")
    if status not in NEW_PRODUCT_STATUSES:
        raise HTTPException(422, "未知新品提醒状态")
    scoped = detail.copy()
    if launch_stage != "all":
        start, end = stage_bounds[launch_stage]
        scoped = scoped[scoped["开售天数"].between(start, end)].copy()
    if search and search.strip():
        needle = search.strip()
        search_match = pd.Series(False, index=scoped.index)
        for column in ("SKU", "ASIN"):
            if column in scoped.columns:
                search_match |= scoped[column].fillna("").astype(str).str.contains(
                    needle, case=False, regex=False
                )
        scoped = scoped[search_match].copy()
    metrics_frame = scoped.copy()
    if status != "all":
        scoped = scoped[scoped["监控状态"].eq(NEW_PRODUCT_STATUS_LABELS[status])].copy()

    status_counts = metrics_frame["监控状态"].value_counts() if not metrics_frame.empty else pd.Series(dtype=int)
    metrics = [
        metric("新品 SKU 数", len(metrics_frame), "integer"),
        metric("建议涨价", int(status_counts.get("建议涨价", 0)), "integer"),
        metric("建议降价", int(status_counts.get("建议降价", 0)), "integer"),
        metric("可售数量合计", pd.to_numeric(metrics_frame.get("可售数量", pd.Series(dtype=float)), errors="coerce").sum(min_count=1), "integer"),
        metric("近30天销量", pd.to_numeric(metrics_frame.get("30天销量", pd.Series(dtype=float)), errors="coerce").sum(min_count=1), "integer"),
        metric("已断货", int(status_counts.get("已断货", 0)), "integer"),
        metric("新品观察中", int(status_counts.get("新品观察中", 0)), "integer"),
        metric("数据异常", int(status_counts.get("数据异常", 0)), "integer"),
    ]
    context_columns = base["context_columns"]
    source_uploaded_at = base["source_uploaded_at"]
    formats = {
        "开售天数": "整数",
        "可售数量": "整数",
        "日均销量": "数值",
        "可售覆盖天数": "数值",
        "昨天销量": "数值",
        "前天销量": "数值",
        "上前销量": "数值",
        "7天销量": "数值",
        "14天销量": "数值",
        "30天销量": "数值",
        "90天销量": "数值",
        **{column: "百分比" for column in context_columns if column.endswith("毛利率")},
    }
    return {
        **_base_payload(
            "新品监控",
            {"developers": options, "launch_stages": ["0-6", "7-29", "30-59", "60-100"]},
            {
                "developers": explicit_selected_values(developers, options),
                "launch_stage": launch_stage,
                "status": status,
                "search": search or "",
            },
        ),
        "has_data": not metrics_frame.empty,
        "message": None if not metrics_frame.empty else "当前筛选条件下没有符合范围的新品",
        "metrics": metrics,
        "calculation_date": business_day,
        "source_uploaded_at": source_uploaded_at,
        "excluded_invalid_launch_count": excluded_launch_count,
        "copy_lists": {
            "raise_skus": metrics_frame.loc[metrics_frame["监控状态"].eq("建议涨价"), "SKU"].drop_duplicates().astype(str).tolist(),
            "lower_skus": metrics_frame.loc[metrics_frame["监控状态"].eq("建议降价"), "SKU"].drop_duplicates().astype(str).tolist(),
            "calculation_date": business_day,
        },
        "sections": [
            section(
                "detail",
                "新品监控明细",
                scoped,
                formats=formats,
                rows_serializer=_rows_with_sku_images(base["image_lookup"]),
            )
        ],
        "_updated_at": base["updated_at"],
    }


def _new_product_bundle(
    developers: str | None = None,
    launch_stage: str = "all",
    status: str = "all",
    search: str | None = None,
) -> dict[str, Any]:
    business_day = _new_product_business_day().isoformat()
    return _cached_new_product_bundle(
        developers, launch_stage, status, search, _new_product_revision(), business_day
    )


def _new_product_response(
    bundle: dict[str, Any],
    page: int = 1,
    page_size: int = SUMMARY_PAGE_SIZE,
    sort_by: str | None = None,
    sort_order: str = "asc",
) -> dict[str, Any]:
    result = {key: value for key, value in bundle.items() if key not in {"sections", "_updated_at"}}
    result["sections"] = [
        _serialized_section(_section_model(bundle, "detail"), page, page_size,
                            sort_by=sort_by, sort_order=sort_order)
    ]
    result["updated_at"] = float(bundle.get("_updated_at") or 0)
    return result


def _build_products(developers: str | None, view: str | None = None) -> dict[str, Any]:
    if view not in {None, "detail", "low-margin"}:
        raise HTTPException(422, "产品视图只能是 detail 或 low-margin")
    include_detail = view in {None, "detail"}
    include_low_margin = view in {None, "low-margin"}
    operational = load_source_frame("operational_sales", "运营原始表")
    gross = load_source_frame("gross_profit", "毛利原始表")
    options = developer_options(operational)
    chosen = selected_values(developers, options)
    if options:
        operational = operational[operational["开发员"].fillna("").astype(str).str.strip().isin(chosen)].copy()
    image_lookup = _sku_image_lookup(operational, _optional_sku_image_map())
    sections = []
    detail = pd.DataFrame()
    low = pd.DataFrame()

    if include_detail:
        rating = load_source_frame("rating", "Rating")
        detail = merge_listing_price_data(
            merge_product_launch_data(
                merge_product_promotion_data(
                    product_management_display_table(build_product_management_table(operational, gross, rating)),
                    _active_product_promotion_rows(),
                ),
                _product_launch_rows(),
            )
        )
        sections.append(section(
            "detail",
            "产品管理明细",
            detail,
            formats={
                "开售天数": "整数",
                **{column: "数值" for column in PRODUCT_LAUNCH_PRICE_COLUMNS.values()},
                **{f"{country}较开售价变化": "百分比" for country in ("德国", "法国", "西班牙", "意大利")},
            },
            rows_serializer=_rows_with_sku_images(image_lookup),
        ))

    if include_low_margin:
        operational_skus = _normalized_sku_set(operational, "MSKU")
        low = merge_listing_price_data(build_low_margin_product_table(
            gross,
            developers=chosen or None,
            allowed_skus=operational_skus,
        ))
        sections.append(section(
            "low-margin",
            "低毛利率 SKU",
            low,
            rows_serializer=_rows_with_sku_images(image_lookup),
        ))

    metrics = [] if detail.empty else [
        metric("ASIN数", detail["ASIN"].nunique(), "integer"),
        metric("SKU数", len(detail), "integer"),
        metric("可售数量", pd.to_numeric(detail["可售数量"], errors="coerce").sum(), "integer"),
        metric("日均销量", pd.to_numeric(detail["日均销量"], errors="coerce").sum()),
        metric("30天销量", pd.to_numeric(detail["30天销量"], errors="coerce").sum(), "integer"),
    ]
    if not include_detail and not low.empty:
        metrics = [metric("低毛利 SKU 数", len(low), "integer"), metric("涉及 ASIN 数", low["ASIN"].nunique(), "integer")]
    return {
        **_base_payload("产品管理", {"developers": options}, {"developers": explicit_selected_values(developers, options)}),
        "has_data": any(not item["frame"].empty for item in sections),
        "message": "当前筛选条件下没有对应产品" if not any(not item["frame"].empty for item in sections) else None,
        "metrics": metrics,
        "sections": sections,
        "_updated_at": _batch_monitor_updated_timestamp(),
    }


def latest_detail_date(volume: pd.DataFrame, amount: pd.DataFrame) -> pd.Timestamp | None:
    return latest_department_detail_date(volume, amount)


_DEPARTMENT_PERFORMANCE_LOCK = Lock()


@lru_cache(maxsize=3)
def _cached_department_performance(
    revision: str,
    business_day: str,
) -> tuple[dict[str, pd.DataFrame], int, int]:
    del revision
    operational = load_source_frame("operational_sales", "运营原始表")
    volume = normalize_sales_volume_detail(load_source_frame("sales_volume_detail", "销量明细"))
    amount = normalize_sales_amount_detail(load_source_frame("sales_amount_detail", "销售额明细"))
    volume_duplicate_count = int(volume.duplicated(keep="first").sum())
    amount_duplicate_count = int(amount.duplicated(keep="first").sum())
    performance = build_department_performance_tables(
        operational,
        volume,
        amount,
        today=business_day,
        amount_history_df=load_department_sales_amount_history(),
        normalized_inputs=True,
    )
    return performance, volume_duplicate_count, amount_duplicate_count


def _department_performance(revision: str, business_day: str) -> tuple[dict[str, pd.DataFrame], int, int]:
    # lru_cache does not serialize cold misses; this lock merges same-version
    # builds when several dashboard sections load together after an upload.
    with _DEPARTMENT_PERFORMANCE_LOCK:
        return _cached_department_performance(revision, business_day)


def _build_department(month: str | None, view: str | None = None) -> dict[str, Any]:
    if view not in {None, "performance", "commission"}:
        raise HTTPException(422, "部门视图只能是 performance 或 commission")
    include_performance = view in {None, "performance"}
    include_commission = view in {None, "commission"}
    home = load_home_data() if include_commission else pd.DataFrame()
    months = _non_empty_options(home, "月份")
    chosen_month = month if month in months else (months[-1] if months else None)
    commission = pd.DataFrame()
    commission_details: dict[str, dict[str, object]] = {}
    if include_commission and chosen_month:
        month_data = home[home["月份"].astype(str).eq(chosen_month)].copy()
        counted, _ = split_counted_and_stopped_data(month_data)
        commission, commission_details = build_department_commission_monitor(
            counted, load_metric_config(), load_commission_config(), load_department_fee_config()
        )
    performance: dict[str, pd.DataFrame] = {}
    volume_duplicate_count = amount_duplicate_count = 0
    if include_performance:
        business_day = datetime.now(LOCAL_TIMEZONE).date().isoformat()
        performance, volume_duplicate_count, amount_duplicate_count = _department_performance(
            _page_revision("department", "performance"),
            business_day,
        )
    sections = []
    if include_commission:
        sections.append(section("commission", f"{chosen_month or ''} 人员提成汇总", commission))
    if include_performance:
        sections.extend(
            performance_section(f"performance-{index}", title, frame)
            for index, (title, frame) in enumerate(performance.items())
        )
    has_data = (any(not frame.empty for frame in performance.values()) if include_performance else False) or (not commission.empty if include_commission else False)
    payload = {
        **_base_payload("部门监控", {"months": months}, {"month": chosen_month}),
        "has_data": has_data,
        "sections": sections,
        "commission_config": {"month": chosen_month, "details": commission_details} if include_commission else None,
    }
    warnings = []
    if volume_duplicate_count:
        warnings.append(f"现有销量明细含 {volume_duplicate_count} 条完全重复记录，计算时已自动去重，原始上传文件仍保留")
    if amount_duplicate_count:
        warnings.append(f"现有销售额明细含 {amount_duplicate_count} 条完全重复记录，计算时已自动去重，原始上传文件仍保留")
    if warnings:
        payload["warnings"] = warnings
    return payload


def _build_department_assessment(month: str | None) -> dict[str, Any]:
    report_data = build_department_assessment_report(load_performance_reports(), month)
    report_paths = _report_paths(load_upload_records())
    updated_at = max((path.stat().st_mtime for path in report_paths), default=0)
    return {
        "title": "考核监控",
        "months": report_data["months"],
        "selected_month": report_data["selected_month"],
        "rows": report_data["rows"],
        "updated_at": updated_at,
        "has_data": bool(report_data["rows"]),
    }


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


_SALES_VOLUME_RANGE_PATTERN = re.compile(
    r"(?P<start>\d{4}-\d{2}-\d{2})\s*[~～]\s*(?P<end>\d{4}-\d{2}-\d{2})"
)


def _replenishment_site_sales_source() -> tuple[pd.DataFrame, dict[str, Any]]:
    source_path = get_latest_source_path("sales_volume_detail")
    empty = pd.DataFrame(
        columns=["ASIN", "销量明细已匹配", "销量明细DE销量", "销量明细FR销量", "销量明细ES销量", "销量明细IT销量"]
    )
    metadata: dict[str, Any] = {
        "source": None,
        "available": False,
        "period_start": None,
        "period_end": None,
        "day_count": 0,
    }
    if source_path is None:
        return empty, metadata

    metadata["source"] = "sales_volume_detail"
    records = load_latest_source_record("sales_volume_detail")
    original_name = str(records.iloc[-1]["原始文件名"]) if not records.empty else source_path.name
    uploaded_at = pd.to_datetime(records.iloc[-1]["上传时间"], errors="coerce") if not records.empty else pd.NaT
    period_start = None
    period_end = None
    match = _SALES_VOLUME_RANGE_PATTERN.search(original_name)
    if match:
        parsed_start = pd.to_datetime(match.group("start"), errors="coerce")
        parsed_end = pd.to_datetime(match.group("end"), errors="coerce")
        if not pd.isna(parsed_start) and not pd.isna(parsed_end) and parsed_start <= parsed_end:
            period_start = parsed_start
            period_end = parsed_end
    reference_date = period_end if period_end is not None else (uploaded_at if not pd.isna(uploaded_at) else None)

    try:
        summary, dates = build_replenishment_site_sales_summary(
            load_source_frame("sales_volume_detail", "销量明细"),
            reference_date=reference_date,
            period_start=period_start,
            period_end=period_end,
        )
    except (KeyError, TypeError, ValueError):
        return empty, metadata
    if not dates:
        return empty, metadata
    metadata.update(
        {
            "available": True,
            "period_start": dates[0].date().isoformat(),
            "period_end": dates[-1].date().isoformat(),
            "day_count": len(dates),
        }
    )
    return summary, metadata


def _replenishment_base_paths() -> list[Path]:
    paths: list[Path] = []
    for key in ("operational_sales", "gross_profit", "rating", "sales_volume_detail", "sku_image_map"):
        path = get_latest_source_path(key)
        if path:
            paths.append(path)
        index_path = latest_source_index_path(key)
        if index_path.exists():
            paths.append(index_path)
    for name in ("replenishment_coverage_rules", "replenishment_product_tags", "store_config"):
        path = CONFIG_DIR / f"{name}.csv"
        if path.exists():
            paths.append(path)
    history_index = sales_history_index_path()
    if history_index.exists():
        paths.append(history_index)
    paths.extend(get_sales_history_paths())
    paths.extend(
        [
            Path(__file__).resolve(),
            Path(build_replenishment_management_tables.__code__.co_filename).resolve(),
        ]
    )
    return sorted(set(paths), key=str)


def _promotion_snapshot_revision() -> str:
    promotions = _last_promotion_rows()
    if not promotions.empty and "sku" in promotions.columns:
        promotions = promotions.sort_values("sku", kind="stable")
    payload = promotions.astype(object).where(pd.notna(promotions), None).to_dict("records")
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


@lru_cache(maxsize=4)
def _cached_replenishment_base_tables(revision: str) -> dict[str, pd.DataFrame]:
    def build() -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
        operational = load_source_frame("operational_sales", "运营原始表")
        gross = load_source_frame("gross_profit", "毛利原始表") if get_latest_source_path("gross_profit") else pd.DataFrame()
        rating = load_source_frame("rating", "Rating") if get_latest_source_path("rating") else pd.DataFrame()
        image_map = load_source_frame("sku_image_map", "SKU图片映射表") if get_latest_source_path("sku_image_map") else pd.DataFrame()
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
            sku_image_map=normalize_sku_image_map(image_map) if not image_map.empty else None,
            only_needed=False,
        )
        site_sales, site_sales_metadata = _replenishment_site_sales_source()
        site_columns = [f"销量明细{code}销量" for code in ("DE", "FR", "ES", "IT")]
        detail = tables["detail"].drop(columns=["销量明细已匹配", *site_columns], errors="ignore").copy()
        if not site_sales.empty:
            detail = detail.merge(site_sales, on="ASIN", how="left", sort=False, validate="many_to_one")
        else:
            detail["销量明细已匹配"] = False
            for column in site_columns:
                detail[column] = pd.NA
        detail["销量明细已匹配"] = detail["销量明细已匹配"].fillna(False).astype(bool)
        for column in site_columns:
            if column not in detail:
                detail[column] = pd.NA
        tables["detail"] = detail
        return (
            {key: tables[key] for key in ("detail", "sku_detail", "history")},
            {
                "site_sales_metadata": site_sales_metadata,
                "history_source": "rolling" if history_paths else None,
            },
        )

    frames, metadata = load_or_build_frame_bundle("replenishment-base", revision, build)
    return {**frames, **metadata}


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
    source_revision = revision_digest("replenishment-base-v2", paths)
    calculation_day = datetime.now(LOCAL_TIMEZONE).date().isoformat()
    revision = f"{source_revision}:{calculation_day}:{_promotion_snapshot_revision()}"
    base = _cached_replenishment_base_tables(revision)
    switches = _read_optional_replenishment_config(
        "replenishment_switches",
        normalize_replenishment_switches,
    )
    return {
        **base,
        "detail": _apply_replenishment_switches(base["detail"], switches),
    }


_REPLENISHMENT_WARM_LOCK = Lock()
_REPLENISHMENT_WARM_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="replenishment-warm")
_REPLENISHMENT_WARM_TIMER: Timer | None = None
_LOGGER = logging.getLogger(__name__)


def _warm_replenishment_sources() -> None:
    try:
        _replenishment_tables()
        cached_listing_bundle()
    except Exception:
        _LOGGER.exception("补货数据后台预热失败；后续请求会按当前版本重试")


def _submit_replenishment_warmup() -> None:
    global _REPLENISHMENT_WARM_TIMER
    with _REPLENISHMENT_WARM_LOCK:
        _REPLENISHMENT_WARM_TIMER = None
    try:
        _REPLENISHMENT_WARM_EXECUTOR.submit(_warm_replenishment_sources)
    except RuntimeError:
        # A debounced timer can fire while the process or test interpreter exits.
        _LOGGER.debug("Skipping replenishment warmup because the executor is shutting down")


def schedule_replenishment_warmup() -> None:
    """Debounce source/config writes and warm current tables off the request path."""
    global _REPLENISHMENT_WARM_TIMER
    with _REPLENISHMENT_WARM_LOCK:
        if _REPLENISHMENT_WARM_TIMER is not None:
            _REPLENISHMENT_WARM_TIMER.cancel()
        timer = Timer(0.35, _submit_replenishment_warmup)
        timer.daemon = True
        _REPLENISHMENT_WARM_TIMER = timer
        timer.start()


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
    operational_row: dict[str, Any] | None = None,
    site_sales_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    monitor_row = operational_row if operational_row is not None else row
    recent_sales = {
        "yesterday": _replenishment_number(monitor_row.get("昨天销量")),
        "day_before_yesterday": _replenishment_number(monitor_row.get("前天销量")),
        "two_days_before": _replenishment_number(monitor_row.get("上前销量")),
    }
    period_sales = {
        "days_7": _replenishment_number(monitor_row.get("7天销量")),
        "days_14": _replenishment_number(monitor_row.get("14天销量")),
        "days_30": _replenishment_number(monitor_row.get("30天销量")),
        "days_90": _replenishment_number(monitor_row.get("90天销量")),
    }
    raw_values = [row.get(column) for column in SALES_HISTORY_GENERIC_MONTH_COLUMNS]
    available = any(value is not None and not pd.isna(value) for value in raw_values)
    site_metadata = site_sales_metadata or {}
    source_available = bool(site_metadata.get("available"))
    matched = monitor_row.get("销量明细已匹配")
    site_matched = matched is not None and not pd.isna(matched) and bool(matched)
    site_sales = {
        code: (_replenishment_number(monitor_row.get(f"销量明细{code}销量")) or 0)
        if source_available and site_matched else None
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
        "site_sales_source": site_metadata.get("source"),
        "site_sales_available": source_available,
        "site_sales_matched": site_matched,
        "site_sales_period_start": site_metadata.get("period_start"),
        "site_sales_period_end": site_metadata.get("period_end"),
        "site_sales_days": int(site_metadata.get("day_count") or 0),
        "peak_months": peak_months,
        "recent_sales": recent_sales,
        "period_sales": period_sales,
        **metadata,
        "period_start": months[0]["month"] if months else None,
        "period_end": months[-1]["month"] if months else None,
        # Keep the full chronological series on both group rows and details.
        # ``peak_months`` remains the legacy ranked compatibility field.
        "months": months if available else [],
    }
    if include_months:
        result["months"] = months if available else []
    return result


def _listing_price_values(values: Any) -> list[float]:
    result: list[float] = []
    for value in values or []:
        try:
            if value is None or pd.isna(value):
                continue
            result.append(float(value))
        except (TypeError, ValueError):
            continue
    return result


def _listing_prices_match(values: list[float]) -> bool:
    return not values or max(values) - min(values) <= 0.01


def _listing_event_item(event: dict[str, Any]) -> dict[str, Any]:
    old_price = _listing_history_number(event.get("old_effective_price"))
    new_price = _listing_history_number(event.get("new_effective_price"))
    amount_change = new_price - old_price if old_price is not None and new_price is not None else None
    percent_change = (
        new_price / old_price - 1
        if old_price is not None and new_price is not None and old_price > 0
        else None
    )
    return {
        "sku": str(event.get("sku") or ""),
        "date": event.get("date"),
        "previous_date": event.get("previous_date"),
        "gap_days": event.get("gap_days"),
        "observed_as": event.get("observed_as"),
        "type": event.get("type"),
        "old_price": old_price,
        "new_price": new_price,
        "amount_change": amount_change,
        "percent_change": percent_change,
    }


def _replenishment_sku_sales_scores(sku_detail: pd.DataFrame | None) -> dict[str, float]:
    """Return one comparable sales score per SKU for representative pricing.

    Replenishment SKU rows can contain more than one store row, so the score is
    summed by SKU. The 30-day volume is the primary signal, with shorter
    windows used only when the longer window is unavailable.
    """
    if sku_detail is None or sku_detail.empty or "MSKU" not in sku_detail.columns:
        return {}
    metrics = [column for column in ("30天销量", "14天销量", "7天销量", "昨天销量", "前天销量", "上前销量") if column in sku_detail.columns]
    if not metrics:
        return {}
    frame = sku_detail[["MSKU", *metrics]].copy()
    frame["_sku"] = frame["MSKU"].fillna("").astype(str).str.strip().str.upper()
    frame = frame[frame["_sku"].ne("")]
    if frame.empty:
        return {}
    numeric = frame[metrics].apply(pd.to_numeric, errors="coerce")
    frame["_sales_score"] = numeric.bfill(axis=1).iloc[:, 0]
    grouped = frame.groupby("_sku", sort=False)["_sales_score"].sum(min_count=1).dropna()
    return {str(sku): float(score) for sku, score in grouped.items()}


def _replenishment_representative_sku(sku_set: set[str], sales_scores: dict[str, float] | None) -> str | None:
    if not sku_set:
        return None
    scores = {str(sku).strip().upper(): score for sku, score in (sales_scores or {}).items()}
    return sorted(
        sku_set,
        key=lambda sku: (-scores.get(str(sku).strip().upper(), float("-inf")), str(sku)),
    )[0]


def _latest_replenishment_price_change(
    asin: str,
    sku_set: set[str],
    country: str,
    events: list[dict[str, Any]],
    sales_scores: dict[str, float] | None = None,
    history: pd.DataFrame | None = None,
) -> dict[str, Any] | None:
    relevant_types = {"实际总价涨跌", "恢复可售", "失去可售"}
    candidates = [
        event for event in events
        if str(event.get("asin") or "").strip().upper() == asin
        and str(event.get("sku") or "").strip().upper() in sku_set
        and str(event.get("country") or "").strip().upper() == country
        and event.get("type") in relevant_types
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda event: (
            str(event.get("date") or ""),
            str(event.get("previous_date") or ""),
            str(event.get("sku") or ""),
        ),
        reverse=True,
    )
    latest_key = (
        str(candidates[0].get("date") or ""),
        str(candidates[0].get("previous_date") or ""),
    )
    latest = [
        event for event in candidates
        if (
            str(event.get("date") or ""),
            str(event.get("previous_date") or ""),
        ) == latest_key
    ]
    availability = [event for event in latest if event.get("type") in {"恢复可售", "失去可售"}]
    selected = availability or [event for event in latest if event.get("type") == "实际总价涨跌"]
    if not selected:
        return None
    items = [_listing_event_item(event) for event in selected]
    signatures = {
        (
            None if item["old_price"] is None else round(item["old_price"], 2),
            None if item["new_price"] is None else round(item["new_price"], 2),
        )
        for item in items
    }
    mixed = len(signatures) > 1
    status = "多SKU变价" if mixed else (
        "变价" if items[0]["type"] == "实际总价涨跌" else str(items[0]["type"] or "变价")
    )
    normalized_scores = {str(sku).strip().upper(): score for sku, score in (sales_scores or {}).items()}
    representative = sorted(
        items,
        key=lambda item: (
            -normalized_scores.get(str(item["sku"]).strip().upper(), float("-inf")),
            str(item["sku"]),
        ),
    )[0]
    first = items[0]
    return {
        "status": status,
        "type": "多SKU变价" if mixed else first["type"],
        "date": first["date"],
        "previous_date": first["previous_date"],
        "gap_days": first["gap_days"],
        "observed_as": first["observed_as"],
        "old_price": None if mixed else first["old_price"],
        "new_price": None if mixed else first["new_price"],
        "amount_change": None if mixed else first["amount_change"],
        "percent_change": None if mixed else first["percent_change"],
        "sku_count": len(items),
        "items": items,
        "representative_sku": representative["sku"] if mixed else None,
        "representative_sales": normalized_scores.get(str(representative["sku"]).strip().upper()) if mixed else None,
        "representative_old_price": representative["old_price"] if mixed else None,
        "representative_new_price": representative["new_price"] if mixed else None,
        "representative_amount_change": representative["amount_change"] if mixed else None,
        "representative_percent_change": representative["percent_change"] if mixed else None,
    }


def _listing_history_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _listing_event_response(event: dict[str, Any]) -> dict[str, Any]:
    result = {key: None if value is None or pd.isna(value) else value for key, value in event.items()}
    for column in ("old_base_price", "new_base_price", "old_effective_price", "new_effective_price"):
        if column in result:
            result[column] = _listing_history_number(result[column])
    return result


def _listing_history_flag(value: object) -> bool:
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "是"}


def _replenishment_price_history(
    history: pd.DataFrame | None,
    asin: str,
    country: str,
    representative_sku: str | None,
    history_index: dict[tuple[str, str, str], pd.DataFrame] | None = None,
) -> list[dict[str, Any]]:
    if history is None or history.empty or not representative_sku:
        return []
    required = {"日期", "MSKU", "ASIN", "国家"}
    if not required.issubset(history.columns):
        return []
    if history_index is not None:
        subset = history_index.get((str(asin).strip().upper(), str(representative_sku).strip().upper(), country.upper()), history.iloc[:0])
    else:
        subset = history[
            history["ASIN"].astype(str).str.strip().str.upper().eq(str(asin).strip().upper())
            & history["MSKU"].astype(str).str.strip().str.upper().eq(str(representative_sku).strip().upper())
            & history["国家"].astype(str).str.strip().str.upper().eq(country.upper())
        ].copy()
    if subset.empty:
        return []
    subset["_date"] = pd.to_datetime(subset["日期"], errors="coerce")
    subset = subset.dropna(subset=["_date"]).sort_values("_date", kind="stable")
    points: list[dict[str, Any]] = []
    previous_date: date | None = None
    previous_price: float | None = None
    for row in subset.to_dict("records"):
        current_date = pd.Timestamp(row["_date"]).date()
        current_price = _listing_history_number(row.get("当前实际总价"))
        base_price = _listing_history_number(row.get("Listing原价"))
        promo_price = _listing_history_number(row.get("Listing优惠价"))
        gap_days = (current_date - previous_date).days if previous_date else None
        amount_change = None
        percent_change = None
        if previous_price is not None and current_price is not None and abs(current_price - previous_price) > 0.01:
            amount_change = round(current_price - previous_price, 2)
            percent_change = (current_price / previous_price - 1) if previous_price > 0 else None
        points.append({
            "date": current_date.isoformat(),
            "current_price": current_price,
            "listing_price": base_price,
            "promotion_price": promo_price,
            "currency": str(row.get("币种") or "").strip() or None,
            "is_promotion": _listing_history_flag(row.get("促销中")),
            "is_available": current_price is not None,
            "anomaly": None if row.get("异常类型") is None or pd.isna(row.get("异常类型")) else str(row.get("异常类型")),
            "gap_days": gap_days,
            "observed_as": "首次观察到" if gap_days is not None and gap_days > 1 else None,
            "previous_price": previous_price,
            "amount_change": amount_change,
            "percent_change": percent_change,
        })
        previous_date = current_date
        previous_price = current_price
    return points

def _replenishment_listing_summary(
    asin: str,
    sku_values: list[str],
    source: pd.DataFrame,
    events: list[dict[str, Any]],
    sales_scores: dict[str, float] | None = None,
    history: pd.DataFrame | None = None,
    source_by_asin: dict[str, pd.DataFrame] | None = None,
    history_by_key: dict[tuple[str, str, str], pd.DataFrame] | None = None,
    events_by_asin_country: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    if source.empty:
        return None
    normalized_asin = str(asin or "").strip().upper()
    candidates = (source_by_asin.get(normalized_asin) if source_by_asin is not None else source[source["ASIN"].astype(str).str.upper().eq(normalized_asin)].copy())
    if candidates is None:
        return None
    if candidates.empty:
        return None
    sku_set = {str(value).strip().upper() for value in sku_values if str(value).strip()}
    selected = candidates[candidates["MSKU"].astype(str).str.upper().isin(sku_set)]
    if selected.empty:
        selected = candidates
        sku_set = {str(value).strip().upper() for value in selected["MSKU"].dropna().tolist() if str(value).strip()}
    sales_scores = {str(sku).strip().upper(): score for sku, score in (sales_scores or {}).items()}
    representative_sku = _replenishment_representative_sku(sku_set, sales_scores)
    countries = {}
    for code in ("DE", "FR", "ES", "IT"):
        history_points = _replenishment_price_history(history, normalized_asin, code, representative_sku, history_by_key)
        current = _listing_price_values(selected.get(f"{code}_当前实际总价", pd.Series(dtype=float)).dropna().tolist())
        launch = _listing_price_values(selected.get(f"{code}_开售价", pd.Series(dtype=float)).dropna().tolist())
        changes = _listing_price_values(selected.get(f"{code}_较开售价变化", pd.Series(dtype=float)).dropna().tolist())
        current_matches = _listing_prices_match(current)
        launch_matches = _listing_prices_match(launch)
        change_matches = _listing_prices_match(changes)
        latest_change = _latest_replenishment_price_change(normalized_asin, sku_set, code, events_by_asin_country.get((normalized_asin, code), []) if events_by_asin_country is not None else events, sales_scores)
        if not current_matches:
            representative_sku = _replenishment_representative_sku(sku_set, sales_scores)
            representative_values = selected.loc[
                selected["MSKU"].astype(str).str.strip().str.upper().eq(str(representative_sku or "").upper()),
                f"{code}_当前实际总价",
            ] if representative_sku and f"{code}_当前实际总价" in selected.columns else pd.Series(dtype=float)
            representative_current = _listing_price_values(representative_values.dropna().tolist())
            if latest_change is None:
                latest_change = {
                    "status": "多SKU变价",
                    "type": "多SKU变价",
                    "date": None,
                    "previous_date": None,
                    "gap_days": None,
                    "observed_as": None,
                    "old_price": None,
                    "new_price": None,
                    "amount_change": None,
                    "percent_change": None,
                    "sku_count": len(current),
                    "items": [],
                    "representative_sku": representative_sku,
                    "representative_sales": (sales_scores or {}).get(str(representative_sku or "").upper()),
                    "representative_old_price": None,
                    "representative_new_price": representative_current[0] if representative_current else None,
                    "representative_amount_change": None,
                    "representative_percent_change": None,
                }
            else:
                latest_change = {
                    **latest_change,
                    "status": "多SKU变价",
                    "type": "多SKU变价",
                    "old_price": None,
                    "new_price": None,
                    "amount_change": None,
                    "percent_change": None,
                }
                if representative_current:
                    latest_change["representative_new_price"] = representative_current[0]
        countries[code] = {
            "current_price": current[0] if current_matches and current else None,
            "launch_price": launch[0] if launch_matches and launch else None,
            "launch_change": changes[0] if change_matches and changes else None,
            "status": "不一致" if not current_matches or not launch_matches or not change_matches else ("无当前价" if not current else "有价格"),
            "representative_sku": representative_sku,
            "history": history_points,
            "latest_change": latest_change,
        }
    recent = [item for item in events if item["asin"].upper() == normalized_asin and item["sku"].upper() in {str(value).strip().upper() for value in sku_values}]
    return {"status": "不一致" if any(item["status"] == "不一致" for item in countries.values()) else "一致", "recent_event": _listing_event_response(recent[0]) if recent else None, "countries": countries}


def _replenishment_group_rows(
    frame: pd.DataFrame,
    history_source: str | None = None,
    site_sales_metadata: dict[str, Any] | None = None,
    sku_detail: pd.DataFrame | None = None,
    include_pricing: bool = True,
) -> list[dict[str, Any]]:
    country_columns = {
        "DE": "德国",
        "FR": "法国",
        "ES": "西班牙",
        "IT": "意大利",
    }
    result: list[dict[str, Any]] = []
    if include_pricing:
        listing_source, listing_history_source, listing_events = cached_listing_bundle()
    else:
        listing_source = pd.DataFrame()
        listing_history_source = pd.DataFrame()
        listing_events = ()
    sales_scores = _replenishment_sku_sales_scores(sku_detail)
    source_by_asin: dict[str, pd.DataFrame] = {}
    if include_pricing and not listing_source.empty and "ASIN" in listing_source.columns:
        source_by_asin = {
            str(key).strip().upper(): group
            for key, group in listing_source.groupby(listing_source["ASIN"].astype(str).str.strip().str.upper(), sort=False)
        }
    history_by_key: dict[tuple[str, str, str], pd.DataFrame] = {}
    if include_pricing and not listing_history_source.empty:
        history_by_key = {
            (str(key[0]).strip().upper(), str(key[1]).strip().upper(), str(key[2]).strip().upper()): group
            for key, group in listing_history_source.groupby(["ASIN", "MSKU", "国家"], sort=False)
        }
    events_by_asin_country: dict[tuple[str, str], list[dict[str, Any]]] = {}
    if include_pricing:
        for event in listing_events:
            key = (str(event.get("asin") or "").strip().upper(), str(event.get("country") or "").strip().upper())
            events_by_asin_country.setdefault(key, []).append(event)
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
        def _text_value(value: object) -> str:
            if value is None or pd.isna(value):
                return ""
            return str(value).strip()

        image_url = _text_value(row.get("库存图片链接"))
        image = None
        if image_url:
            virtual_sku = _text_value(row.get("虚拟SKU"))
            original_sku = _text_value(row.get("原SKU"))
            image = {
                "url": image_url,
                "inventory_sku": _text_value(row.get("库存SKU")),
                "virtual_sku": virtual_sku,
                "source_role": "original" if virtual_sku.upper() == original_sku.upper() else "follower",
            }
        promotion = None
        if any(row.get(column) is not None for column in ("最近促销开始日期", "最近促销截止日期", "最近促销折扣")):
            promotion = {
                "start_date": row.get("最近促销开始日期"),
                "end_date": row.get("最近促销截止日期"),
                "discount_percent": row.get("最近促销折扣"),
            }
        asin_value = str(row.get("ASIN") or "").split("；")[0]
        sku_values = [str(row.get("原SKU") or "")] + _split_compact(row.get("跟卖SKU"))
        pricing = _replenishment_listing_summary(asin_value, sku_values, listing_source, listing_events, sales_scores, listing_history_source, source_by_asin, history_by_key, events_by_asin_country) if include_pricing else None
        result.append(
            {
                "group_id": str(row.get("补货组ID") or ""),
                "identity": {
                    "asin": str(row.get("ASIN") or ""),
                    "image": image,
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
                "pricing": pricing,
                "history": _replenishment_history(row, source=history_source, site_sales_metadata=site_sales_metadata),
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
                row_serializer=lambda frame, include_pricing=True: _replenishment_group_rows(
                    frame,
                    tables.get("history_source"),
                    tables.get("site_sales_metadata"),
                    tables.get("sku_detail"),
                    include_pricing=include_pricing,
                ),
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
    for key in ("operational_sales", "gross_profit", "rating", "sales_volume_detail", "sales_amount_detail", "sku_image_map"):
        path = get_latest_source_path(key)
        if path:
            paths.append(path)
        source_index = DATA_DIR / "sources" / f"{key}_source.csv"
        if source_index.exists():
            paths.append(source_index)
    department_amount_history = department_sales_amount_history_path()
    if department_amount_history.exists():
        paths.append(department_amount_history)
    history_index = sales_history_index_path()
    if history_index.exists():
        paths.append(history_index)
    paths.extend(get_sales_history_paths())
    listing_index = listing_index_path()
    if listing_index.exists():
        paths.append(listing_index)
    listing_dir = listing_root()
    paths.extend(path for path in listing_dir.glob('*.csv') if path.is_file())
    paths.extend(path for path in listing_dir.glob('*.xlsx') if path.is_file())
    return sorted(set(paths), key=str)


def dashboard_revision() -> str:
    paths = _revision_paths()
    return revision_digest("dashboard-derived", paths) if paths else "empty"


def _page_dependency_paths(page_name: str, view: str | None = None) -> list[Path]:
    source_keys: dict[str, tuple[str, ...]] = {
        "sales": ("operational_sales",),
        "slow-moving": ("operational_sales", "sku_image_map"),
        "products": ("operational_sales", "gross_profit", "sku_image_map", "rating"),
        "department": ("operational_sales", "sales_volume_detail", "sales_amount_detail"),
        "replenishment": ("operational_sales", "gross_profit", "rating", "sku_image_map", "sales_volume_detail"),
    }
    paths: list[Path] = []
    if page_name == "overview" or (page_name == "department" and view != "performance"):
        paths.append(DATA_DIR / "upload_records.csv")
        records_frame = load_upload_records()
        paths.extend(_report_paths(records_frame))
    page_source_keys = source_keys.get(page_name, ())
    if page_name == "department" and view == "commission":
        page_source_keys = ()
    for key in page_source_keys:
        paths.extend([DATA_DIR / "sources" / f"{key}_source.csv"])
        source = get_latest_source_path(key)
        if source:
            paths.append(source)
    config_names: dict[str, tuple[str, ...]] = {
        "overview": ("metrics_config", "store_config", "monthly_targets", "commission_config", "department_fee_config"),
        "sales": ("store_config",),
        "slow-moving": ("store_config",),
        "department": ("store_config", "metrics_config", "commission_config", "department_fee_config", "sales_amount_detail"),
        "replenishment": ("replenishment_coverage_rules", "replenishment_switches", "replenishment_product_tags"),
    }
    if page_name == "department":
        if view == "performance":
            config_names["department"] = ("store_config",)
            paths.append(department_sales_amount_history_path())
        elif view == "commission":
            config_names["department"] = ("store_config", "metrics_config", "commission_config", "department_fee_config")
    paths.extend(CONFIG_DIR / f"{name}.csv" for name in config_names.get(page_name, ()))
    if page_name == "replenishment":
        paths.extend(get_sales_history_paths())
        paths.extend([sales_history_index_path(), DATA_DIR / "sources" / "sales_history_rolling_source.csv"])
    if page_name == "products":
        paths.append(listing_index_path())
        try:
            listing_index = pd.read_csv(listing_index_path(), encoding="utf-8-sig")
            if not listing_index.empty and "保存文件名" in listing_index.columns:
                latest_name = str(listing_index.iloc[-1]["保存文件名"] or "").strip()
                if latest_name and Path(latest_name).name == latest_name:
                    paths.append(listing_root() / latest_name)
        except Exception:
            pass
    return sorted(set(paths), key=str)


def _page_revision(page_name: str, view: str | None = None) -> str:
    paths = _page_dependency_paths(page_name, view)
    digest = hashlib.sha256(f"dashboard-page-v2:{page_name}:{view or 'all'}".encode("utf-8"))
    updated_at = 0.0
    for path in paths:
        try:
            stat = path.stat()
            digest.update(f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8"))
            updated_at = max(updated_at, stat.st_mtime)
        except OSError:
            digest.update(f"{path}:missing".encode("utf-8"))
    if page_name == "products":
        from backend.promotions import promotion_revision
        digest.update(batch_monitor_revision().encode("ascii"))
        digest.update(promotion_revision().encode("ascii"))
    elif page_name in {"slow-moving", "replenishment"}:
        from backend.promotions import promotion_revision
        digest.update(promotion_revision().encode("ascii"))
    return f"{digest.hexdigest()}|{updated_at:.6f}"


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
    view: str | None,
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
        return _build_products(developers, view)
    if page_name == "department":
        return _build_department(month, view)
    if page_name == "replenishment":
        return _build_replenishment(developers, min_qty)
    raise HTTPException(404, "未知看板页面")


def clear_dashboard_caches() -> None:
    _cached_bundle.cache_clear()
    _cached_department_performance.cache_clear()
    _cached_new_product_bundle.cache_clear()
    _cached_new_product_base.cache_clear()
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
    view: str | None = None,
) -> dict[str, Any]:
    revision = _page_revision(page_name, view)
    bundle = _cached_bundle(
        page_name,
        developers,
        months,
        departments,
        store_types,
        threshold,
        month,
        min_qty,
        view,
        revision.split("|", 1)[0],
    )
    if "_updated_at" not in bundle:
        try:
            bundle["_updated_at"] = float(revision.rsplit("|", 1)[1])
        except (IndexError, ValueError):
            bundle["_updated_at"] = 0.0
    return bundle


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
    include_pricing: bool = True,
) -> dict[str, Any]:
    filtered = _query_frame(model["frame"], search, sort_by, sort_order, model.get("columns"))
    total = len(filtered)
    start = (page - 1) * page_size
    visible = filtered.iloc[start : start + page_size]
    rows_serializer = model.get("rows_serializer")
    result = {
        "key": model["key"],
        "title": model["title"],
        "columns": model["columns"],
        "rows": rows_serializer(visible) if rows_serializer else records(visible),
        "chart": model["chart"],
        "page": page,
        "page_size": page_size,
        "total": total,
        "paginated": total > page_size,
        "summary": _section_summary(filtered, model.get("summary_mode")),
    }
    row_serializer = model.get("row_serializer")
    if row_serializer:
        if model.get("key") == "detail" and model.get("title") == "ASIN补货汇总":
            result["group_rows"] = row_serializer(visible, include_pricing=include_pricing)
        else:
            result["group_rows"] = row_serializer(visible)
    return result


def _serialize_bundle(bundle: dict[str, Any], include_pricing: bool = True) -> dict[str, Any]:
    result = {
        key: value
        for key, value in bundle.items()
        if key not in {"sections", "_updated_at"}
    }
    result["sections"] = [_serialized_section(item, include_pricing=include_pricing) for item in bundle.get("sections", [])]
    replenishment_section = next(
        (item for item in result["sections"] if item.get("key") == "detail" and "group_rows" in item),
        None,
    )
    if replenishment_section:
        result["group_rows"] = replenishment_section["group_rows"]
    result["updated_at"] = float(bundle.get("_updated_at") or 0)
    return result


def _dashboard_response(page_name: str, include_pricing: bool = True, **filters: Any) -> dict[str, Any]:
    try:
        return _serialize_bundle(_bundle(page_name, **filters), include_pricing=include_pricing)
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
def products(developers: str | None = None, view: str | None = Query(None, pattern="^(detail|low-margin)$")):
    return _dashboard_response("products", developers=developers, view=view)


@router.get("/new-products")
def new_products(
    developers: str | None = None,
    launch_stage: str = "all",
    search: str | None = Query(None, max_length=200),
):
    return _new_product_response(
        _new_product_bundle(developers=developers, launch_stage=launch_stage, search=search)
    )


@router.get("/new-products/view")
def new_products_view(
    developers: str | None = None,
    launch_stage: str = "all",
    status: str = "all",
    search: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(SUMMARY_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    sort_by: str | None = Query(None, max_length=100),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
):
    """Return one consistent summary, full copy lists and requested table page."""

    bundle = _new_product_bundle(developers=developers, launch_stage=launch_stage, status=status, search=search)
    return _new_product_response(bundle, page, page_size, sort_by, sort_order)


@router.get("/new-products/copy-lists")
def new_product_copy_lists(
    developers: str | None = None,
    launch_stage: str = "all",
    search: str | None = Query(None, max_length=200),
):
    bundle = _new_product_bundle(
        developers=developers,
        launch_stage=launch_stage,
        status="all",
        search=search,
    )
    frame = _section_model(bundle, "detail")["frame"]
    raise_skus = frame.loc[frame["监控状态"].eq("建议涨价"), "SKU"].drop_duplicates().astype(str).tolist()
    lower_skus = frame.loc[frame["监控状态"].eq("建议降价"), "SKU"].drop_duplicates().astype(str).tolist()
    return {
        "raise_skus": raise_skus,
        "lower_skus": lower_skus,
        "calculation_date": bundle["calculation_date"],
    }


@router.get("/department")
def department(
    month: str | None = None,
    view: str | None = Query(None, pattern="^(performance|commission)$"),
):
    return _dashboard_response("department", month=month, view=view)



@router.put("/department/commission-config")
def save_department_commission_config(payload: dict[str, Any]):
    """Update selected-month raw commission and department fee rows from the department page."""
    month = str(payload.get("month") or "").strip()
    if not month:
        raise HTTPException(422, "缺少配置月份")
    commission_rows = payload.get("commission_rows") or []
    fee_rows = payload.get("department_fee_rows") or []
    if not isinstance(commission_rows, list) or not isinstance(fee_rows, list):
        raise HTTPException(422, "配置行必须是数组")
    try:
        from backend.config_api import (
            _CONFIG_WRITE_LOCK,
            _atomic_write_config,
            _invalidate_dashboard_cache,
            read_config,
            validate_and_normalize_config,
        )
        from dashboard.data_processing import normalize_month

        month = normalize_month(month) or month
        with _CONFIG_WRITE_LOCK:
            existing_commission = read_config("commission_config")
            existing_fee = read_config("department_fee_config")
            updates_commission = pd.DataFrame(commission_rows)
            updates_fee = pd.DataFrame(fee_rows)
            for frame, expected_month, name in (
                (updates_commission, month, "commission_config"),
                (updates_fee, month, "department_fee_config"),
            ):
                if not frame.empty and "月份" in frame.columns:
                    normalized_months = frame["月份"].map(normalize_month).fillna("")
                    if normalized_months.ne(expected_month).any():
                        raise ValueError(f"{name}只能修改当前月份")
            def merge_updates(existing: pd.DataFrame, updates: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
                if updates.empty:
                    return existing
                working = existing.copy()
                existing_key = working[keys].fillna("").astype(str).apply(lambda column: column.str.strip()).astype(str).agg("|".join, axis=1)
                update_key = updates.reindex(columns=keys).fillna("").astype(str).apply(lambda column: column.str.strip()).astype(str).agg("|".join, axis=1)
                working = working[~existing_key.isin(set(update_key))]
                return pd.concat([working, updates], ignore_index=True)
            commission_frame = validate_and_normalize_config(
                "commission_config", merge_updates(existing_commission, updates_commission, ["月份", "开发员"])
            )
            fee_frame = validate_and_normalize_config(
                "department_fee_config", merge_updates(existing_fee, updates_fee, ["月份", "部门"])
            )
            for frame, column in ((commission_frame, "职位提点"), (fee_frame, "费用率")):
                values = pd.to_numeric(frame[column], errors="coerce").dropna()
                if ((values < 0) | (values > 1)).any():
                    raise ValueError(f"{column}必须在0到1之间")
            commission_path = _atomic_write_config("commission_config", commission_frame)
            fee_path = _atomic_write_config("department_fee_config", fee_frame)
            _invalidate_dashboard_cache()
        return {"ok": True, "updated_at": max(commission_path.stat().st_mtime, fee_path.stat().st_mtime)}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422, f"提成配置保存失败：{exc}") from exc


@router.get("/department/assessment")
def department_assessment(month: str | None = None):
    try:
        return _build_department_assessment(month)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"考核监控计算失败：{exc}") from exc


@router.get("/replenishment")
def replenishment(
    developers: str | None = None,
    min_qty: int = Query(30, ge=0),
    include_pricing: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(SUMMARY_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    search: str | None = Query(None, max_length=200),
    sort_by: str | None = Query(None, max_length=100),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
):
    try:
        bundle = _bundle("replenishment", developers=developers, min_qty=min_qty)
        result = {key: value for key, value in bundle.items() if key not in {"sections", "_updated_at"}}
        result["sections"] = [
            _serialized_section(
                _section_model(bundle, "detail"), page, page_size, search, sort_by, sort_order,
                include_pricing=include_pricing,
            )
        ]
        result["group_rows"] = result["sections"][0].get("group_rows", [])
        result["updated_at"] = float(bundle.get("_updated_at") or 0)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"补货看板计算失败：{exc}") from exc


@router.get("/replenishment/pricing")
def replenishment_pricing(group_ids: str = Query("", max_length=5000)):
    identifiers = [item.strip() for item in group_ids.split(",") if item.strip()]
    if len(identifiers) > MAX_PAGE_SIZE:
        raise HTTPException(422, f"一次最多查询 {MAX_PAGE_SIZE} 个补货组")
    try:
        tables = _replenishment_tables()
        detail = tables["detail"]
        if identifiers:
            wanted = set(identifiers)
            frame = detail[detail["补货组ID"].astype(str).isin(wanted)].reset_index(drop=True)
        else:
            frame = detail.iloc[:0].copy()
        rows = _replenishment_group_rows(
            frame,
            tables.get("history_source"),
            tables.get("site_sales_metadata"),
            tables.get("sku_detail"),
            include_pricing=True,
        )
        return {
            "revision": _page_revision("replenishment"),
            "rows": {row["group_id"]: row.get("pricing") for row in rows},
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"补货价格读取失败：{exc}") from exc

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
        if "MSKU" in sku_detail.columns:
            sku_prices = latest_listing_wide()
            if not sku_prices.empty:
                sku_detail = sku_detail.merge(sku_prices, left_on="MSKU", right_on="MSKU", how="left", sort=False)
        asin = str(match.iloc[0]["ASIN"]).split("；")[0]
        summary_row = records(match.head(1))[0]
        history = tables["history"]
        history_row = records(history[history["ASIN"].astype(str).eq(asin)].head(1)) if not history.empty else []
        return {
            "group": summary_row,
            "sku_columns": column_definitions(sku_detail),
            "sku_rows": records(sku_detail),
            "sales_history": _replenishment_history(
                history_row[0] if history_row else {},
                include_months=True,
                source=tables.get("history_source"),
                operational_row=summary_row,
                site_sales_metadata=tables.get("site_sales_metadata"),
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
    search: str | None = Query(None, max_length=200),
    sort_by: str | None = Query(None, max_length=100),
    sort_order: str = Query('asc', pattern='^(asc|desc)$'),
):
    try:
        tables = _replenishment_tables()
        operational = load_source_frame("operational_sales", "运营原始表")
        options = developer_options(operational)
        detail = _filter_replenishment_detail(tables["detail"], developers, min_qty, options)
        detail = _query_frame(detail, search, sort_by, sort_order, column_definitions(detail))
        sku_detail = tables["sku_detail"].copy()
        sku_detail = sku_detail[sku_detail["补货组ID"].isin(set(detail["补货组ID"]))].copy()
        group_order = {group_id: index for index, group_id in enumerate(detail["补货组ID"].tolist())}
        sku_detail["_export_order"] = sku_detail["补货组ID"].map(group_order).fillna(len(group_order))
        sku_detail = sku_detail.sort_values("_export_order", kind="stable").drop(columns=["_export_order"])
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


@router.get("/new-products/sections/detail")
def new_products_section(
    page: int = Query(1, ge=1),
    page_size: int = Query(SUMMARY_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    search: str | None = Query(None, max_length=200),
    sort_by: str | None = Query(None, max_length=100),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    developers: str | None = None,
    launch_stage: str = "all",
    status: str = "all",
):
    bundle = _new_product_bundle(
        developers=developers,
        launch_stage=launch_stage,
        status=status,
        search=search,
    )
    return _serialized_section(
        _section_model(bundle, "detail"), page, page_size, search, sort_by, sort_order
    )


@router.get("/new-products/sections/detail/export.csv")
def export_new_products(
    search: str | None = Query(None, max_length=200),
    sort_by: str | None = Query(None, max_length=100),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    developers: str | None = None,
    launch_stage: str = "all",
    status: str = "all",
):
    bundle = _new_product_bundle(
        developers=developers,
        launch_stage=launch_stage,
        status=status,
        search=search,
    )
    model = _section_model(bundle, "detail")
    frame = _query_frame(model["frame"], search, sort_by, sort_order, model.get("columns"))
    filename = quote(f"{model['title']}.csv")
    return StreamingResponse(
        _csv_chunks(frame),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


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
    include_pricing: bool = True,
    view: str | None = None,
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
            view=view,
        )
        return _serialized_section(_section_model(bundle, section_key), page, page_size, search, sort_by, sort_order, include_pricing=include_pricing)
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
    view: str | None = None,
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
            view=view,
        )
        model = _section_model(bundle, section_key)
        frame = _query_frame(model["frame"], search, sort_by, sort_order, model.get("columns"))
        export_frame_serializer = model.get("export_frame_serializer")
        if export_frame_serializer:
            frame = export_frame_serializer(frame)
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
