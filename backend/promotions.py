from __future__ import annotations

import csv
import io
import json
import sqlite3
import unicodedata
import uuid
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.dashboard_api import load_source_frame, source_path
import backend.db as db
from backend.db import connect
from dashboard.data_processing import CONFIG_DIR, exclude_stopped_store_operational_rows, load_business_config
from dashboard.parquet_cache import revision_digest
from dashboard.report_store import get_latest_source_path
from dashboard.promotions import (
    PROMOTION_CANDIDATE_COLUMNS,
    PROMOTION_DISCOUNTS,
    PROMOTION_SKU_METRIC_COLUMNS,
    build_promotion_candidates,
    build_promotion_sku_metrics,
    normalize_promotion_sku,
)


router = APIRouter(prefix="/api/promotions", tags=["promotions"])
PromotionStatus = Literal["pending", "active", "ended"]
PromotionStatusFilter = Literal["pending", "active", "ended", "all"]
SortOrder = Literal["asc", "desc"]
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
LOCAL_TIMEZONE = timezone(timedelta(hours=8))


CANDIDATE_COLUMNS: list[dict[str, Any]] = [
    {"key": "sku", "label": "SKU", "type": "string", "format": "text", "sortable": True},
    {"key": "asin", "label": "ASIN", "type": "string", "format": "text", "sortable": True},
    {"key": "developer", "label": "开发员", "type": "string", "format": "text", "sortable": True},
    {"key": "available_inventory", "label": "可售库存", "type": "number", "format": "number", "precision": 2, "sortable": True},
    {"key": "sales_90d", "label": "90天销量", "type": "number", "format": "number", "precision": 2, "sortable": True},
    {"key": "aged_inventory_90d", "label": "90天以上库存", "type": "number", "format": "number", "precision": 2, "sortable": True},
    {"key": "average_7d", "label": "7天日均", "type": "number", "format": "number", "precision": 2, "sortable": True},
    {"key": "average_30d", "label": "30天日均", "type": "number", "format": "number", "precision": 2, "sortable": True},
    {"key": "daily_lift", "label": "日均提升", "type": "number", "format": "number", "precision": 2, "sortable": True},
    {"key": "discount_percent", "label": "建议折扣", "type": "number", "format": "number", "unit": "%", "precision": 0, "sortable": True},
    {"key": "rule_key", "label": "命中策略", "type": "string", "format": "text", "sortable": True},
]

RECORD_COLUMNS: list[dict[str, Any]] = [
    {"key": "sku", "label": "SKU", "type": "string", "format": "text", "sortable": True},
    {"key": "promotion_name", "label": "促销名称", "type": "string", "format": "text", "sortable": True},
    {"key": "asin_snapshot", "label": "ASIN（标记时）", "type": "string", "format": "text", "sortable": True},
    {"key": "developer_snapshot", "label": "开发员（标记时）", "type": "string", "format": "text", "sortable": True},
    {"key": "discount_percent", "label": "促销折扣", "type": "number", "format": "number", "unit": "%", "precision": 0, "sortable": True},
    {"key": "rule_key", "label": "命中策略", "type": "string", "format": "text", "sortable": True},
    {"key": "start_date", "label": "开始日期", "type": "date", "format": "date", "sortable": True},
    {"key": "end_date", "label": "结束日期", "type": "date", "format": "date", "sortable": True},
    {"key": "status", "label": "状态", "type": "string", "format": "text", "sortable": True},
    {"key": "average_7d", "label": "7天日均", "type": "number", "format": "number", "precision": 2, "sortable": True},
    {"key": "average_30d", "label": "30天日均", "type": "number", "format": "number", "precision": 2, "sortable": True},
    {"key": "daily_lift", "label": "日均提升", "type": "number", "format": "number", "precision": 2, "sortable": True},
    {"key": "source_missing", "label": "源数据缺失", "type": "boolean", "format": "boolean", "sortable": True},
]

LAST_PROMOTION_COLUMNS: list[dict[str, Any]] = [
    {"key": "sku", "label": "SKU", "type": "string", "format": "text", "sortable": True},
    {"key": "promotion_content", "label": "促销内容", "type": "string", "format": "text", "sortable": True},
]

LAST_PROMOTION_EXPORT_FIELDS = [
    ("sku", "SKU"),
    ("promotion_content", "促销内容"),
]

CANDIDATE_EXPORT_FIELDS = [
    ("sku", "SKU"),
    ("asin", "ASIN"),
    ("developer", "开发员"),
    ("available_inventory", "可售库存"),
    ("sales_90d", "90天销量"),
    ("aged_inventory_90d", "90天以上库存"),
    ("average_7d", "7天日均"),
    ("average_30d", "30天日均"),
    ("daily_lift", "日均提升"),
    ("discount_percent", "建议折扣(%)"),
    ("rule_key", "命中策略"),
]

RECORD_EXPORT_FIELDS = [
    ("sku", "SKU"),
    ("promotion_name", "促销名称"),
    ("asin_snapshot", "ASIN（标记时）"),
    ("developer_snapshot", "开发员（标记时）"),
    ("discount_percent", "促销折扣(%)"),
    ("rule_key", "命中策略"),
    ("start_date", "开始日期"),
    ("end_date", "结束日期"),
    ("status", "状态"),
    ("available_inventory", "当前可售库存"),
    ("sales_90d", "当前90天销量"),
    ("aged_inventory_90d", "当前90天以上库存"),
    ("average_7d", "当前7天日均"),
    ("average_30d", "当前30天日均"),
    ("daily_lift", "当前日均提升"),
    ("source_missing", "源数据缺失"),
]


def today() -> date:
    return datetime.now(LOCAL_TIMEZONE).date()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _promotion_data_updated_at() -> str | None:
    timestamps: list[datetime] = []
    try:
        source = source_path("operational_sales", "运营原始表")
        timestamps.append(datetime.fromtimestamp(source.stat().st_mtime, timezone.utc))
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    with connect() as conn:
        latest = conn.execute("SELECT MAX(updated_at) AS updated_at FROM sku_promotions").fetchone()["updated_at"]
    if latest:
        timestamps.append(datetime.fromisoformat(str(latest).replace("Z", "+00:00")))
    return max(timestamps).replace(microsecond=0).isoformat() if timestamps else None


class PromotionDateInput(BaseModel):
    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_date_order(self):
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        return self


class PromotionNameInput(PromotionDateInput):
    promotion_name: str = Field(min_length=1, max_length=100)

    @field_validator("promotion_name")
    @classmethod
    def normalize_promotion_name(cls, value: str) -> str:
        return _normalize_promotion_name(value)


def _normalize_promotion_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise ValueError("促销名称不能为空")
    if len(normalized) > 100:
        raise ValueError("促销名称不能超过 100 个字符")
    return normalized


class PromotionCreate(PromotionNameInput):
    skus: list[str] = Field(min_length=1, max_length=5000)

    @field_validator("skus")
    @classmethod
    def normalize_skus(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            sku = normalize_promotion_sku(value)
            if not sku:
                raise ValueError("SKU 不能为空")
            if len(sku) > 200:
                raise ValueError("SKU 不能超过 200 个字符")
            if sku not in seen:
                seen.add(sku)
                result.append(sku)
        if not result:
            raise ValueError("至少选择一个 SKU")
        return result


class ManualPromotionCreate(PromotionCreate):
    discount_percent: int = Field(ge=1, le=99)


class PromotionUpdate(PromotionNameInput):
    pass


class PromotionActivityDelete(BaseModel):
    promotion_name: str = Field(min_length=1, max_length=100)

    @field_validator("promotion_name")
    @classmethod
    def normalize_promotion_name(cls, value: str) -> str:
        return _normalize_promotion_name(value)


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    clean = frame.where(pd.notna(frame), None)
    return json.loads(clean.to_json(orient="records", date_format="iso", force_ascii=False))


@lru_cache(maxsize=4)
def _cached_promotion_frames(
    source_path_text: str,
    source_revision: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    del source_path_text, source_revision
    raw = load_source_frame("operational_sales", "运营原始表")
    store_config, _ = load_business_config()
    raw = exclude_stopped_store_operational_rows(raw, store_config)
    metrics = build_promotion_sku_metrics(raw)
    candidates = build_promotion_candidates(raw)
    return metrics, candidates


def load_promotion_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    path = source_path("operational_sales", "运营原始表")
    revision = revision_digest("promotion-derived", [path, CONFIG_DIR / "store_config.csv"])
    metrics, candidates = _cached_promotion_frames(str(path), revision)
    return metrics.copy(deep=False), candidates.copy(deep=False)


def clear_promotion_caches() -> None:
    _cached_promotion_frames.cache_clear()


def promotion_revision() -> str:
    """Revision for promotion views, including candidate inputs and SQLite records."""
    paths = [CONFIG_DIR / "store_config.csv", db.DB_PATH]
    operational = get_latest_source_path("operational_sales")
    if operational:
        paths.append(operational)
    existing = [path for path in paths if path.is_file()]
    return revision_digest("app-promotions", existing) if existing else "empty"


def _promotion_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        return load_promotion_frames()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"促销数据计算失败：{exc}") from exc


def _metrics_or_empty() -> pd.DataFrame:
    try:
        metrics, _ = _promotion_frames()
        return metrics
    except HTTPException as exc:
        if exc.status_code == 404:
            return pd.DataFrame(columns=PROMOTION_SKU_METRIC_COLUMNS)
        raise


def _selected_developers(value: str | None) -> list[str]:
    if not value:
        return []
    return list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def _developer_options(frame: pd.DataFrame, column: str = "developer") -> list[str]:
    if column not in frame.columns or frame.empty:
        return []
    values = frame[column].fillna("").astype(str).str.strip()
    return sorted(values[values.ne("")].drop_duplicates().tolist())


def _query_frame(
    frame: pd.DataFrame,
    *,
    search: str | None,
    developers: str | None,
    developer_column: str,
    sort_by: str,
    sort_order: SortOrder,
    search_columns: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    result = frame.copy()
    options = _developer_options(result, developer_column)
    if search and search.strip():
        needle = search.strip()
        mask = pd.Series(False, index=result.index)
        for column in search_columns:
            if column in result.columns:
                mask |= result[column].fillna("").astype(str).str.contains(needle, case=False, regex=False)
        result = result[mask]
    selected = _selected_developers(developers)
    if selected and developer_column in result.columns:
        result = result[result[developer_column].fillna("").astype(str).isin(selected)]
    if sort_by not in result.columns:
        raise HTTPException(422, f"不支持按字段排序：{sort_by}")
    result = result.sort_values(sort_by, ascending=sort_order == "asc", kind="stable", na_position="last")
    return result.reset_index(drop=True), options


def _blocked_skus(reference: date | None = None) -> set[str]:
    reference_text = (reference or today()).isoformat()
    with connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT sku FROM sku_promotions
            WHERE end_date IS NULL OR end_date >= ?""",
            (reference_text,),
        ).fetchall()
    return {row["sku"] for row in rows}


def _candidate_frame(discount: int) -> pd.DataFrame:
    if discount not in PROMOTION_DISCOUNTS:
        raise HTTPException(422, "促销折扣只允许 5、8 或 10")
    _, candidates = _promotion_frames()
    result = candidates[candidates["discount_percent"].eq(discount)].copy()
    blocked = _blocked_skus()
    if blocked:
        result = result[~result["sku"].isin(blocked)]
    return result.reset_index(drop=True)


def _candidate_query(
    discount: int,
    *,
    search: str | None,
    developers: str | None,
    sort_by: str,
    sort_order: SortOrder,
) -> tuple[pd.DataFrame, list[str]]:
    return _query_frame(
        _candidate_frame(discount),
        search=search,
        developers=developers,
        developer_column="developer",
        sort_by=sort_by,
        sort_order=sort_order,
        search_columns=["sku", "asin", "developer", "rule_key"],
    )


def _status(start_date: str, end_date: str | None, reference: date | None = None) -> PromotionStatus:
    reference_text = (reference or today()).isoformat()
    if start_date > reference_text:
        return "pending"
    if end_date is None or end_date >= reference_text:
        return "active"
    return "ended"


def _metrics_by_sku(metrics: pd.DataFrame) -> dict[str, dict[str, Any]]:
    return {str(row["sku"]): row for row in _frame_records(metrics)}


def _serialize_promotion(row: Any, metrics_by_sku: dict[str, dict[str, Any]]) -> dict[str, Any]:
    record = dict(row)
    current = metrics_by_sku.get(record["sku"])
    source_missing = current is None
    for column in PROMOTION_SKU_METRIC_COLUMNS:
        if column == "sku":
            continue
        record[column] = current.get(column) if current is not None else None
    record["asin"] = record.get("asin") or record["asin_snapshot"]
    record["developer"] = record.get("developer") or record["developer_snapshot"]
    record["source_missing"] = source_missing
    record["status"] = _status(record["start_date"], record["end_date"])
    return record


def _promotion_rows() -> list[Any]:
    with connect() as conn:
        return conn.execute("SELECT * FROM sku_promotions ORDER BY created_at DESC, id DESC").fetchall()


def _records_frame() -> pd.DataFrame:
    metrics = _metrics_or_empty()
    current = _metrics_by_sku(metrics)
    rows = [_serialize_promotion(row, current) for row in _promotion_rows()]
    columns = ["id", "sku", "promotion_name", "asin_snapshot", "developer_snapshot", "discount_percent", "rule_key", "start_date", "end_date", "created_at", "updated_at", *[column for column in PROMOTION_SKU_METRIC_COLUMNS if column != "sku"], "source_missing", "status"]
    return pd.DataFrame(rows, columns=list(dict.fromkeys(columns)))


def _last_promotion_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    if parsed.year != today().year:
        return f"{parsed.year}/{parsed.month}/{parsed.day}"
    return f"{parsed.month}/{parsed.day}"


def _last_promotion_content(row: dict[str, Any]) -> str:
    start = _last_promotion_date(str(row["start_date"]))
    name = str(row.get("promotion_name") or "历史未命名促销")
    discount = int(row["discount_percent"])
    end_date = row.get("end_date")
    if end_date:
        return f"{start}~{_last_promotion_date(str(end_date))} {name} -{discount}%"
    return f"{start}起 {name} -{discount}%（持续）"


def _last_promotions_frame() -> pd.DataFrame:
    with connect() as conn:
        rows = [dict(row) for row in conn.execute(
            """SELECT sku, promotion_id, promotion_name, discount_percent, start_date, end_date, updated_at
            FROM sku_last_promotions"""
        ).fetchall()]
    for row in rows:
        row["promotion_content"] = _last_promotion_content(row)
    columns = [
        "sku", "promotion_content", "promotion_id", "promotion_name", "discount_percent",
        "start_date", "end_date", "updated_at",
    ]
    return pd.DataFrame(rows, columns=columns)


def _upsert_last_promotion(
    conn: sqlite3.Connection,
    *,
    promotion_id: str,
    sku: str,
    promotion_name: str,
    discount_percent: int,
    start_date: str,
    end_date: str | None,
    updated_at: str,
) -> None:
    conn.execute(
        """INSERT INTO sku_last_promotions
        (sku, promotion_id, promotion_name, discount_percent, start_date, end_date, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sku) DO UPDATE SET
            promotion_id = excluded.promotion_id,
            promotion_name = excluded.promotion_name,
            discount_percent = excluded.discount_percent,
            start_date = excluded.start_date,
            end_date = excluded.end_date,
            updated_at = excluded.updated_at""",
        (sku, promotion_id, promotion_name, discount_percent, start_date, end_date, updated_at),
    )


def _activity_status(rows: pd.DataFrame) -> PromotionStatus:
    statuses = set(rows["status"].dropna().astype(str))
    if "active" in statuses:
        return "active"
    if "pending" in statuses:
        return "pending"
    return "ended"


def _promotion_activity_summaries(rows: pd.DataFrame) -> list[dict[str, Any]]:
    """Build durable review rows for all promotion activities, including ended ones."""
    if rows.empty:
        return []

    summaries: list[dict[str, Any]] = []
    grouped = rows.groupby("promotion_name", sort=False, dropna=False)
    for name, group in grouped:
        promotion_name = str(name or "历史未命名促销")
        status = _activity_status(group)
        available = group[~group["source_missing"]].copy()
        summaries.append(
            {
                "promotion_name": promotion_name,
                "start_date": str(group["start_date"].min()),
                "end_date": None if group["end_date"].isna().any() else str(group["end_date"].max()),
                "status": status,
                "sku_count": int(len(group)),
                "discount_percents": sorted({int(value) for value in group["discount_percent"].dropna()}),
                "source_missing_count": int(group["source_missing"].sum()),
                "average_7d": round(float(available["average_7d"].sum()), 6) if not available.empty else 0.0,
                "average_30d": round(float(available["average_30d"].sum()), 6) if not available.empty else 0.0,
                "daily_lift": round(float(available["daily_lift"].sum()), 6) if not available.empty else 0.0,
            }
        )

    status_order = {"active": 0, "pending": 1, "ended": 2}
    return sorted(
        summaries,
        key=lambda item: (status_order[str(item["status"])], item["start_date"], item["promotion_name"]),
        reverse=False,
    )


def _conflict(message: str, skus: list[str]) -> HTTPException:
    return HTTPException(
        409,
        {"message": message, "count": len(skus), "examples": skus[:3]},
    )


def _stream_csv(
    rows: list[dict[str, Any]],
    fields: list[tuple[str, str]],
) -> Iterator[str]:
    yield "\ufeff"
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([label for _, label in fields])
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    status_labels = {"pending": "待开始", "active": "正在促销", "ended": "已结束"}
    for row in rows:
        values: list[Any] = []
        for key, _ in fields:
            value = row.get(key)
            if key == "status":
                value = status_labels.get(str(value), value)
            elif key == "source_missing":
                value = "是" if value else "否"
            values.append("" if value is None else value)
        writer.writerow(values)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


def _csv_response(
    rows: list[dict[str, Any]],
    fields: list[tuple[str, str]],
    filename: str,
) -> StreamingResponse:
    return StreamingResponse(
        _stream_csv(rows, fields),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/overview")
def promotion_overview(developers: str | None = Query(None, max_length=2000)):
    metrics = _metrics_or_empty()
    metrics_lookup = _metrics_by_sku(metrics)
    with connect() as conn:
        promotion_rows = conn.execute(
            """SELECT * FROM sku_promotions
            ORDER BY promotion_name, start_date, sku"""
        ).fetchall()
    serialized = [_serialize_promotion(row, metrics_lookup) for row in promotion_rows]
    all_records = pd.DataFrame(serialized)
    developer_options = _developer_options(all_records, "developer_snapshot")
    selected = _selected_developers(developers)
    if selected and not all_records.empty:
        all_records = all_records[all_records["developer_snapshot"].fillna("").astype(str).isin(selected)]

    activity_summaries = _promotion_activity_summaries(all_records)
    all_active = all_records[all_records["status"].eq("active")].copy() if not all_records.empty else all_records
    source_missing_count = int(all_active["source_missing"].sum()) if not all_active.empty else 0
    available = all_active[~all_active["source_missing"]].copy() if not all_active.empty else all_active
    active_count = len(available)
    average_7d_total = float(available["average_7d"].sum()) if active_count else 0.0
    average_30d_total = float(available["average_30d"].sum()) if active_count else 0.0
    daily_lift_total = float(available["daily_lift"].sum()) if active_count else 0.0
    return {
        "active_sku_count": active_count,
        "average_7d_total": round(average_7d_total, 6),
        "average_30d_total": round(average_30d_total, 6),
        "daily_lift_total": round(daily_lift_total, 6),
        "daily_lift_average": round(daily_lift_total / active_count, 6) if active_count else 0.0,
        "source_missing_count": source_missing_count,
        "by_promotion": activity_summaries,
        "developers": developer_options,
        "selected_developers": selected,
        "updated_at": _promotion_data_updated_at(),
    }


@router.get("/candidates/{discount}")
def promotion_candidates(
    discount: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    search: str | None = Query(None, max_length=200),
    developers: str | None = Query(None, max_length=2000),
    sort_by: str = Query("sku", max_length=64),
    sort_order: SortOrder = "asc",
):
    frame, options = _candidate_query(
        discount,
        search=search,
        developers=developers,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total = len(frame)
    start = (page - 1) * page_size
    rows = _frame_records(frame.iloc[start : start + page_size])
    return {
        "columns": CANDIDATE_COLUMNS,
        "rows": rows,
        "page": page,
        "page_size": page_size,
        "total": total,
        "developers": options,
    }


@router.get("/candidates/{discount}/skus.txt")
def promotion_candidate_skus(
    discount: int,
    search: str | None = Query(None, max_length=200),
    developers: str | None = Query(None, max_length=2000),
    sort_by: str = Query("sku", max_length=64),
    sort_order: SortOrder = "asc",
):
    frame, _ = _candidate_query(
        discount,
        search=search,
        developers=developers,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    content = "\n".join(frame["sku"].astype(str).drop_duplicates().tolist())
    if content:
        content += "\n"
    return Response(
        content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="promotion-candidates-{discount}-skus.txt"'},
    )


@router.get("/candidates/{discount}/export.csv")
def export_promotion_candidates(
    discount: int,
    search: str | None = Query(None, max_length=200),
    developers: str | None = Query(None, max_length=2000),
    sort_by: str = Query("sku", max_length=64),
    sort_order: SortOrder = "asc",
):
    frame, _ = _candidate_query(
        discount,
        search=search,
        developers=developers,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return _csv_response(
        _frame_records(frame),
        CANDIDATE_EXPORT_FIELDS,
        f"promotion-candidates-{discount}.csv",
    )


def _query_records(
    *,
    status: PromotionStatusFilter,
    search: str | None,
    developers: str | None,
    sort_by: str,
    sort_order: SortOrder,
) -> tuple[pd.DataFrame, list[str]]:
    frame = _records_frame()
    if status != "all" and not frame.empty:
        frame = frame[frame["status"].eq(status)]
    return _query_frame(
        frame,
        search=search,
        developers=developers,
        developer_column="developer_snapshot",
        sort_by=sort_by,
        sort_order=sort_order,
        search_columns=["sku", "promotion_name", "asin_snapshot", "developer_snapshot", "rule_key"],
    )


@router.get("/records")
def promotion_records(
    status: PromotionStatusFilter = "active",
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    search: str | None = Query(None, max_length=200),
    developers: str | None = Query(None, max_length=2000),
    sort_by: str = Query("start_date", max_length=64),
    sort_order: SortOrder = "desc",
):
    frame, options = _query_records(
        status=status,
        search=search,
        developers=developers,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total = len(frame)
    start = (page - 1) * page_size
    return {
        "columns": RECORD_COLUMNS,
        "rows": _frame_records(frame.iloc[start : start + page_size]),
        "page": page,
        "page_size": page_size,
        "total": total,
        "developers": options,
    }


def _query_last_promotions(
    *,
    search: str | None,
    sort_by: str,
    sort_order: SortOrder,
) -> pd.DataFrame:
    frame = _last_promotions_frame()
    if search and search.strip():
        needle = search.strip()
        mask = (
            frame["sku"].fillna("").astype(str).str.contains(needle, case=False, regex=False)
            | frame["promotion_content"].fillna("").astype(str).str.contains(needle, case=False, regex=False)
        )
        frame = frame[mask]
    allowed_sort_columns = {"sku", "promotion_content", "start_date", "end_date", "promotion_name", "discount_percent", "updated_at"}
    if sort_by not in allowed_sort_columns:
        raise HTTPException(422, f"不支持按字段排序：{sort_by}")
    return frame.sort_values(
        sort_by,
        ascending=sort_order == "asc",
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)


@router.get("/last-promotions")
def last_promotions(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    search: str | None = Query(None, max_length=200),
    sort_by: str = Query("updated_at", max_length=64),
    sort_order: SortOrder = "desc",
):
    frame = _query_last_promotions(
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total = len(frame)
    start = (page - 1) * page_size
    return {
        "columns": LAST_PROMOTION_COLUMNS,
        "rows": _frame_records(frame.iloc[start : start + page_size]),
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/last-promotions/export.csv")
def export_last_promotions(
    search: str | None = Query(None, max_length=200),
    sort_by: str = Query("updated_at", max_length=64),
    sort_order: SortOrder = "desc",
):
    frame = _query_last_promotions(
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return _csv_response(
        _frame_records(frame),
        LAST_PROMOTION_EXPORT_FIELDS,
        "last-promotions.csv",
    )


@router.get("/records/export.csv")
def export_promotion_records(
    status: PromotionStatusFilter = "active",
    search: str | None = Query(None, max_length=200),
    developers: str | None = Query(None, max_length=2000),
    sort_by: str = Query("start_date", max_length=64),
    sort_order: SortOrder = "desc",
):
    frame, _ = _query_records(
        status=status,
        search=search,
        developers=developers,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return _csv_response(_frame_records(frame), RECORD_EXPORT_FIELDS, "promotion-records.csv")


@router.post("", status_code=201)
def create_promotions(payload: PromotionCreate):
    _, candidates = _promotion_frames()
    candidate_lookup = {str(row["sku"]): row for row in _frame_records(candidates)}
    invalid = [sku for sku in payload.skus if sku not in candidate_lookup]
    if invalid:
        raise _conflict("所选 SKU 已不再满足促销策略，请刷新后重试", invalid)

    return _persist_promotions(payload, candidate_lookup)


@router.post("/manual", status_code=201)
def create_manual_promotions(payload: ManualPromotionCreate):
    metrics_lookup = _metrics_by_sku(_metrics_or_empty())
    manual_lookup: dict[str, dict[str, Any]] = {}
    for sku in payload.skus:
        metric = metrics_lookup.get(sku) or {}
        manual_lookup[sku] = {
            "asin": metric.get("asin") or "",
            "developer": metric.get("developer") or "",
            "discount_percent": payload.discount_percent,
            "rule_key": "manual",
        }
    return _persist_promotions(payload, manual_lookup, replace_current=True)


def _persist_promotions(
    payload: PromotionCreate,
    promotion_lookup: dict[str, dict[str, Any]],
    replace_current: bool = False,
) -> dict[str, Any]:

    timestamp = now_iso()
    start_text = payload.start_date.isoformat()
    end_text = payload.end_date.isoformat() if payload.end_date else None
    placeholders = ",".join("?" for _ in payload.skus)
    created_ids: list[str] = []
    replaced_count = 0
    try:
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current_rows = conn.execute(
                f"""SELECT id, sku FROM sku_promotions
                WHERE sku IN ({placeholders}) AND (end_date IS NULL OR end_date >= ?)
                ORDER BY updated_at DESC, start_date DESC, id DESC""",
                [*payload.skus, today().isoformat()],
            ).fetchall()
            current_by_sku: dict[str, Any] = {}
            for row in current_rows:
                current_by_sku.setdefault(str(row["sku"]), row)
            if current_by_sku and not replace_current:
                raise _conflict("所选 SKU 已存在正在促销或待开始的记录", sorted(current_by_sku))

            overlap_rows = conn.execute(
                f"""SELECT id, sku FROM sku_promotions
                WHERE sku IN ({placeholders})
                  AND start_date <= ?
                  AND COALESCE(end_date, '9999-12-31') >= ?""",
                [*payload.skus, end_text or "9999-12-31", start_text],
            ).fetchall()
            replace_ids = {str(row["id"]) for row in current_by_sku.values()} if replace_current else set()
            overlap_skus = sorted(
                {str(row["sku"]) for row in overlap_rows if str(row["id"]) not in replace_ids}
            )
            if overlap_skus:
                raise _conflict("所选 SKU 的促销日期与已有记录重叠", overlap_skus)

            for sku in payload.skus:
                candidate = promotion_lookup[sku]
                current = current_by_sku.get(sku) if replace_current else None
                if current is not None:
                    promotion_id = str(current["id"])
                    conn.execute(
                        """UPDATE sku_promotions
                        SET promotion_name = ?, asin_snapshot = ?, developer_snapshot = ?, discount_percent = ?,
                            rule_key = ?, start_date = ?, end_date = ?, updated_at = ?
                        WHERE id = ?""",
                        (
                            payload.promotion_name,
                            candidate.get("asin") or "",
                            candidate.get("developer") or "",
                            int(candidate["discount_percent"]),
                            str(candidate["rule_key"]),
                            start_text,
                            end_text,
                            timestamp,
                            promotion_id,
                        ),
                    )
                    replaced_count += 1
                else:
                    promotion_id = str(uuid.uuid4())
                    conn.execute(
                        """INSERT INTO sku_promotions
                        (id, sku, promotion_name, asin_snapshot, developer_snapshot, discount_percent, rule_key,
                         start_date, end_date, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            promotion_id,
                            sku,
                            payload.promotion_name,
                            candidate.get("asin") or "",
                            candidate.get("developer") or "",
                            int(candidate["discount_percent"]),
                            str(candidate["rule_key"]),
                            start_text,
                            end_text,
                            timestamp,
                            timestamp,
                        ),
                    )
                _upsert_last_promotion(
                    conn,
                    promotion_id=promotion_id,
                    sku=sku,
                    promotion_name=payload.promotion_name,
                    discount_percent=int(candidate["discount_percent"]),
                    start_date=start_text,
                    end_date=end_text,
                    updated_at=timestamp,
                )
                created_ids.append(promotion_id)
    except HTTPException:
        raise
    except sqlite3.IntegrityError as exc:
        raise _conflict("促销记录保存失败，请检查日期与折扣", payload.skus) from exc

    clear_promotion_caches()
    metrics_lookup = _metrics_by_sku(_metrics_or_empty())
    placeholders = ",".join("?" for _ in created_ids)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM sku_promotions WHERE id IN ({placeholders}) ORDER BY id",
            created_ids,
        ).fetchall()
    return {
        "created": [_serialize_promotion(row, metrics_lookup) for row in rows],
        "replaced": replaced_count,
    }


def _get_promotion(promotion_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM sku_promotions WHERE id = ?", (promotion_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "促销记录不存在")
    return row


@router.delete("/activities", status_code=200)
def delete_promotion_activity(payload: PromotionActivityDelete):
    """Delete every SKU record belonging to one named promotion activity."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        deleted = conn.execute(
            "DELETE FROM sku_promotions WHERE promotion_name = ?",
            (payload.promotion_name,),
        ).rowcount
    if not deleted:
        raise HTTPException(404, "促销活动不存在或已删除")
    clear_promotion_caches()
    return {"deleted": deleted, "promotion_name": payload.promotion_name}


@router.put("/{promotion_id}")
def update_promotion(promotion_id: str, payload: PromotionUpdate):
    old = _get_promotion(promotion_id)
    start_text = payload.start_date.isoformat()
    end_text = payload.end_date.isoformat() if payload.end_date else None
    timestamp = now_iso()
    try:
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            overlap = conn.execute(
                """SELECT id FROM sku_promotions
                WHERE sku = ? AND id != ?
                  AND start_date <= ?
                  AND COALESCE(end_date, '9999-12-31') >= ?
                LIMIT 1""",
                (old["sku"], promotion_id, end_text or "9999-12-31", start_text),
            ).fetchone()
            if overlap is not None:
                raise _conflict("修改后的促销日期与已有记录重叠", [old["sku"]])
            conn.execute(
                """UPDATE sku_promotions
                SET promotion_name = ?, start_date = ?, end_date = ?, updated_at = ?
                WHERE id = ?""",
                (payload.promotion_name, start_text, end_text, timestamp, promotion_id),
            )
            conn.execute(
                """UPDATE sku_last_promotions
                SET promotion_name = ?, start_date = ?, end_date = ?, updated_at = ?
                WHERE sku = ? AND promotion_id = ?""",
                (payload.promotion_name, start_text, end_text, timestamp, old["sku"], promotion_id),
            )
    except HTTPException:
        raise
    except sqlite3.IntegrityError as exc:
        raise _conflict("促销记录更新失败，请检查日期", [old["sku"]]) from exc
    clear_promotion_caches()
    return _serialize_promotion(_get_promotion(promotion_id), _metrics_by_sku(_metrics_or_empty()))


@router.delete("/{promotion_id}", status_code=204)
def delete_promotion(promotion_id: str):
    _get_promotion(promotion_id)
    with connect() as conn:
        conn.execute("DELETE FROM sku_promotions WHERE id = ?", (promotion_id,))
    clear_promotion_caches()
    return Response(status_code=204)
