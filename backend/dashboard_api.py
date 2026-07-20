from __future__ import annotations

import io
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from dashboard.data_processing import (
    build_alerts,
    build_department_performance_tables,
    build_low_margin_product_table,
    build_person_commission_summary,
    build_product_management_table,
    build_replenishment_management_tables,
    build_sales_dashboard_tables,
    build_slow_moving_inventory_table,
    compute_metric_table,
    count_chen_26_onsale_skus,
    duplicate_row_issues,
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
from dashboard.report_store import DATA_DIR, get_latest_source_path, load_reports_from_records, load_upload_records


ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "configs"
SUMMARY_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


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
) -> dict[str, Any]:
    frame = frame.reset_index(drop=True)
    columns = column_definitions(frame, formats)
    return {"key": key, "title": title, "frame": frame, "columns": columns, "chart": chart_definition(chart, columns)}


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
    path = source_path(key, title)
    return load_or_build_parquet(f"source-{key}-raw", [path], lambda: read_local_table(path))


def warm_source_cache(source_key: str) -> None:
    titles = {
        "operational_sales": "运营原始表",
        "gross_profit": "毛利原始表",
        "rating": "Rating",
        "sales_volume_detail": "销量明细",
        "sales_amount_detail": "销售额明细",
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
            section("stores", "店铺明细", stores, {"x": "店铺编码", "series": ["昨日订单", "30天日均"]}),
            section("levels", "产品等级", tables["levels"]),
            section("date-compare", "日期对比", tables["date_compare"]),
        ],
    }


def _build_slow_moving(developers: str | None, threshold: str) -> dict[str, Any]:
    thresholds = ["90天以上", "180天以上", "365天以上"]
    if threshold not in thresholds:
        raise HTTPException(422, "非法库龄范围")
    operational = load_source_frame("operational_sales", "运营原始表")
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


def _build_products(developers: str | None) -> dict[str, Any]:
    operational = load_source_frame("operational_sales", "运营原始表")
    gross = load_source_frame("gross_profit", "毛利原始表")
    rating = load_source_frame("rating", "Rating")
    options = developer_options(operational)
    chosen = selected_values(developers, options)
    if options:
        operational = operational[operational["开发员"].fillna("").astype(str).str.strip().isin(chosen)].copy()
    detail = product_management_display_table(build_product_management_table(operational, gross, rating))
    low = build_low_margin_product_table(gross, developers=chosen or None)
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
        "sections": [section("low-margin", "低毛利率 SKU", low), section("detail", "产品管理明细", detail)],
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
        section(f"performance-{index}", title, performance_with_total(frame))
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


def _build_replenishment(developers: str | None) -> dict[str, Any]:
    operational = load_source_frame("operational_sales", "运营原始表")
    gross = load_source_frame("gross_profit", "毛利原始表")
    rating = load_source_frame("rating", "Rating")
    options = developer_options(operational)
    chosen = selected_values(developers, options)
    if options:
        operational = operational[operational["开发员"].fillna("").astype(str).str.strip().isin(chosen)].copy()
    target_path = CONFIG_DIR / "replenishment_targets.csv"
    targets = normalize_replenishment_targets(read_local_table(target_path)) if target_path.exists() else normalize_replenishment_targets(pd.DataFrame())
    tables = build_replenishment_management_tables(operational, gross, rating, targets)
    detail, distribution = tables["detail"], tables["store_distribution"]
    metrics = [] if detail.empty else [
        metric("需补货ASIN数", detail["ASIN"].nunique(), "integer"),
        metric("预计补货总库存数", pd.to_numeric(detail["建议补货数量"], errors="coerce").fillna(0).sum(), "integer"),
        metric("涉及店铺数", distribution["店铺编码"].nunique() if not distribution.empty else 0, "integer"),
    ]
    return {
        **_base_payload("补货管理", {"developers": options}, {"developers": chosen}),
        "has_data": not detail.empty,
        "message": "当前筛选条件下没有需要补货的 ASIN" if detail.empty else None,
        "metrics": metrics,
        "sections": [
            section("distribution", "需补货店铺分布", distribution, {"x": "店铺编码", "series": ["需补货ASIN数"]}),
            section("detail", "补货明细", detail),
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
    return sorted(set(paths), key=str)


def dashboard_revision() -> str:
    paths = _revision_paths()
    return revision_digest("dashboard-derived", paths) if paths else "empty"


@lru_cache(maxsize=48)
def _cached_bundle(
    page_name: str,
    developers: str | None,
    months: str | None,
    departments: str | None,
    store_types: str | None,
    threshold: str,
    month: str | None,
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
        return _build_replenishment(developers)
    raise HTTPException(404, "未知看板页面")


def clear_dashboard_caches() -> None:
    _cached_bundle.cache_clear()
    clear_parquet_memory_cache()


def _bundle(
    page_name: str,
    developers: str | None = None,
    months: str | None = None,
    departments: str | None = None,
    store_types: str | None = None,
    threshold: str = "90天以上",
    month: str | None = None,
) -> dict[str, Any]:
    return _cached_bundle(
        page_name,
        developers,
        months,
        departments,
        store_types,
        threshold,
        month,
        dashboard_revision(),
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
            mask |= result[column].fillna("").astype(str).str.contains(needle, case=False, regex=False)
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
    return {
        "key": model["key"],
        "title": model["title"],
        "columns": model["columns"],
        "rows": records(visible),
        "chart": model["chart"],
        "page": page,
        "page_size": page_size,
        "total": total,
        "paginated": total > page_size,
    }


def _serialize_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in bundle.items() if key != "sections"}
    result["sections"] = [_serialized_section(item) for item in bundle.get("sections", [])]
    result["updated_at"] = max((path.stat().st_mtime for path in _revision_paths()), default=0)
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
def replenishment(developers: str | None = None):
    return _dashboard_response("replenishment", developers=developers)


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
):
    try:
        bundle = _bundle(page_name, developers, months, departments, store_types, threshold, month)
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
):
    try:
        bundle = _bundle(page_name, developers, months, departments, store_types, threshold, month)
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
