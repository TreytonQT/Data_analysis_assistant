from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Callable

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.upload_safety import read_upload_limited, safe_upload_name
from dashboard.data_processing import (
    AGING_CAPITAL_COLUMNS,
    AGING_STOCK_COLUMNS,
    GROSS_PROFIT_AD_COLUMNS,
    GROSS_PROFIT_VOLUME_COLUMNS,
    OPERATIONAL_SALES_NUMERIC_COLUMNS,
    PRODUCT_OPERATIONAL_SUM_COLUMNS,
    REPLENISHMENT_GROSS_RATIO_COLUMNS,
    REPLENISHMENT_STOCK_COMPONENT_COLUMNS,
    build_replenishment_gross_summary,
    normalize_sales_history_month_source,
    duplicate_row_issues,
    normalize_config_number,
    normalize_gross_profit_source,
    normalize_operational_sales,
    normalize_product_operational,
    normalize_rating_source,
    normalize_replenishment_operational,
    normalize_sales_amount_detail,
    normalize_sales_volume_detail,
    read_csv_bytes,
    read_local_table,
    read_upload_table,
)
from dashboard.report_store import (
    DATA_DIR,
    delete_upload_record,
    delete_sales_history,
    get_latest_source_path,
    load_sales_history_records,
    latest_source_index_path,
    load_latest_source_record,
    load_upload_records,
    persist_latest_source,
    persist_uploaded_sales_history,
    persist_uploaded_reports,
    validate_report_month,
)


router = APIRouter(prefix="/api/reports", tags=["reports"])
ROOT = Path(__file__).resolve().parent.parent
MAX_PERFORMANCE_FILES = 24
MAX_PERFORMANCE_FILE_BYTES = 20 * 1024 * 1024
MAX_HISTORY_FILES = 24
MAX_HISTORY_FILE_BYTES = 20 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 50 * 1024 * 1024
MAX_BATCH_BYTES = 100 * 1024 * 1024
MAX_TABLE_ROWS = 500_000
MAX_TABLE_COLUMNS = 500


class MemoryUpload:
    def __init__(self, name: str, data: bytes):
        self.name, self._data = name, data

    def getvalue(self) -> bytes:
        return self._data


def _validate_operational(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_operational_sales(frame)
    normalize_product_operational(frame)
    normalize_replenishment_operational(frame)
    return normalized


def _validate_gross(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_gross_profit_source(frame)
    build_replenishment_gross_summary(frame)
    return normalized


SOURCE_DEFINITIONS: dict[str, tuple[str, Callable[[pd.DataFrame], pd.DataFrame]]] = {
    "operational_sales": ("运营原始表", _validate_operational),
    "gross_profit": ("毛利原始表", _validate_gross),
    "rating": ("Rating", normalize_rating_source),
    "sales_volume_detail": ("销量明细", normalize_sales_volume_detail),
    "sales_amount_detail": ("销售额明细", normalize_sales_amount_detail),
}


def frame_records(frame: pd.DataFrame) -> list[dict]:
    clean = frame.where(pd.notna(frame), None)
    return json.loads(clean.to_json(orient="records", date_format="iso", force_ascii=False))


def source_or_404(source_key: str):
    definition = SOURCE_DEFINITIONS.get(source_key)
    if not definition:
        raise HTTPException(404, "未知数据源")
    return definition


def _validate_table_limits(frame: pd.DataFrame, title: str) -> None:
    if frame.empty:
        raise ValueError(f"{title}没有数据行")
    if len(frame) > MAX_TABLE_ROWS:
        raise ValueError(f"{title}行数超过 {MAX_TABLE_ROWS} 限制")
    if len(frame.columns) > MAX_TABLE_COLUMNS:
        raise ValueError(f"{title}列数超过 {MAX_TABLE_COLUMNS} 限制")
    duplicate_columns = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicate_columns:
        raise ValueError(f"{title}包含重复列名：{', '.join(duplicate_columns[:10])}")


def _numeric_columns(source_key: str, frame: pd.DataFrame) -> list[str]:
    if source_key == "operational_sales":
        candidates = set(
            OPERATIONAL_SALES_NUMERIC_COLUMNS
            + AGING_STOCK_COLUMNS
            + AGING_CAPITAL_COLUMNS
            + REPLENISHMENT_STOCK_COMPONENT_COLUMNS
            + PRODUCT_OPERATIONAL_SUM_COLUMNS
            + ["日均销量", "单品重量(g)", "可售天数", "14天销量", "90天销量"]
        )
        candidates.update(
            column for column in frame.columns if re.fullmatch(r"\d+(?:-\d+)?天(?:以上)?占用资金", str(column).strip())
        )
        return [column for column in frame.columns if column in candidates]
    if source_key == "gross_profit":
        identifiers = {"ASIN", "MSKU", "SKU", "国家", "开发员", "开发人员", "销售专员", "销售"}
        required = set(GROSS_PROFIT_VOLUME_COLUMNS + GROSS_PROFIT_AD_COLUMNS + REPLENISHMENT_GROSS_RATIO_COLUMNS + ["毛利润"])
        return [
            column
            for column in frame.columns
            if column in required or (column not in identifiers and ("销售额" in str(column) or str(column) == "COD"))
        ]
    if source_key == "rating":
        return [column for column in ["Rating总数", "评分"] if column in frame.columns]
    suffix = "销量" if source_key == "sales_volume_detail" else "销售额"
    return [column for column in frame.columns if re.fullmatch(rf"\d{{2}}-\d{{2}}{suffix}", str(column).strip())]


def _bad_numeric_issues(frame: pd.DataFrame, columns: list[str], example_limit: int = 10) -> list[dict]:
    issues: list[dict] = []
    for column in columns:
        values = frame[column]
        non_empty = values.notna() & values.astype(str).str.strip().ne("")
        invalid = non_empty & normalize_config_number(values).isna()
        for index in frame.index[invalid]:
            issues.append({"row": int(index) + 2, "column": str(column), "value": str(values.loc[index])})
            if len(issues) >= example_limit:
                return issues
    return issues


def _raise_bad_numbers(issues: list[dict]) -> None:
    if issues:
        raise HTTPException(
            422,
            detail={
                "code": "invalid_numeric_values",
                "message": "文件包含无法识别的非空数值",
                "count": len(issues),
                "examples": issues,
            },
        )


def _duplicate_upload_warning(source_key: str, issues: list[dict]) -> tuple[int, str | None]:
    """Report exact duplicate exports without rejecting the authoritative raw file.

    The department dashboard removes only completely identical normalized rows
    before calculation. Keeping the CSV unchanged preserves the original export
    while preventing duplicated sales from being counted twice.
    """

    count = sum(int(item["duplicate_count"]) for item in issues)
    if not count:
        return 0, None
    metric_name = "销量" if source_key == "sales_volume_detail" else "销售额"
    return count, (
        f"检测到 {count} 条完全重复{metric_name}明细；原始 CSV 已保留，"
        "看板计算时会自动去重，不会重复计入"
    )


def _invalidate_dashboard_cache() -> None:
    from backend.dashboard_api import clear_dashboard_caches

    clear_dashboard_caches()


def _warm_source_cache(source_key: str) -> None:
    from backend.dashboard_api import warm_source_cache

    try:
        warm_source_cache(source_key)
    except (OSError, ValueError, TypeError):
        # Parquet is disposable. A later read will retry without invalidating the raw upload.
        return


@router.get("")
def reports():
    history_records = load_sales_history_records()
    return {
        "reports": frame_records(load_upload_records()),
        "sources": {
            key: {"title": title, "records": frame_records(load_latest_source_record(key))}
            for key, (title, _) in SOURCE_DEFINITIONS.items()
        } | {"sales_history_rolling": {"title": "往月销量原始表", "records": frame_records(history_records)}},
    }


@router.post("/performance")
async def upload_performance(files: Annotated[list[UploadFile], File(...)]):
    if not files:
        raise HTTPException(422, "没有上传业绩报表")
    if len(files) > MAX_PERFORMANCE_FILES:
        raise HTTPException(413, f"单次最多上传 {MAX_PERFORMANCE_FILES} 个业绩文件")
    uploads: list[MemoryUpload] = []
    total_bytes = 0
    try:
        for item in files:
            name, data = await read_upload_limited(
                item,
                fallback_name="report.csv",
                max_bytes=MAX_PERFORMANCE_FILE_BYTES,
                allowed={".csv"},
            )
            total_bytes += len(data)
            if total_bytes > MAX_BATCH_BYTES:
                raise HTTPException(413, "本批业绩文件总大小超过 100MB 限制")
            frame = read_csv_bytes(data)
            _validate_table_limits(frame, name)
            # Full schema/month/type validation is completed before any file is persisted.
            from dashboard.report_store import detect_report_month

            detect_report_month(data)
            identifier_columns = {"销售专员", "月份", "国家", "店铺", "店铺编码", "来源文件"}
            _raise_bad_numbers(_bad_numeric_issues(frame, [column for column in frame.columns if column not in identifier_columns]))
            uploads.append(MemoryUpload(name, data))
        results = persist_uploaded_reports(uploads)
        _invalidate_dashboard_cache()
        # Build the aggregate Parquet eagerly when possible; raw CSV remains authoritative.
        try:
            from backend.dashboard_api import load_home_data

            load_home_data()
        except (OSError, ValueError, TypeError, HTTPException):
            pass
        return {"results": [result.__dict__ for result in results]}
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/sales-history")
async def upload_sales_history(files: Annotated[list[UploadFile], File(...)]):
    if not files:
        raise HTTPException(422, "没有上传往月销量原始表")
    if len(files) > MAX_HISTORY_FILES:
        raise HTTPException(413, f"单次最多上传 {MAX_HISTORY_FILES} 个销量历史文件")
    uploads: list[MemoryUpload] = []
    total_bytes = 0
    try:
        for item in files:
            name, data = await read_upload_limited(
                item,
                fallback_name="sales-history.csv",
                max_bytes=MAX_HISTORY_FILE_BYTES,
                allowed={".csv"},
            )
            total_bytes += len(data)
            if total_bytes > MAX_BATCH_BYTES:
                raise HTTPException(413, "本批销量历史文件总大小超过 100MB 限制")
            frame = read_csv_bytes(data)
            _validate_table_limits(frame, name)
            # Filename/month/schema/numeric/subtotal validation completes before persistence.
            month_match = re.search(r"(\d{4}-\d{2})-\d{2}\s*[~～]\s*\d{4}-\d{2}-\d{2}", name)
            if not month_match:
                raise ValueError(f"往月销量原始表文件名必须包含完整日期范围：{name}")
            normalize_sales_history_month_source(frame, month_match.group(1))
            uploads.append(MemoryUpload(name, data))
        results, evicted = persist_uploaded_sales_history(uploads)
        _invalidate_dashboard_cache()
        return {
            "results": [result.__dict__ for result in results],
            "evicted_months": evicted,
            "records": frame_records(load_sales_history_records()),
        }
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/source/{source_key}")
async def upload_source(source_key: str, file: Annotated[UploadFile, File(...)]):
    title, validator = source_or_404(source_key)
    name, data = await read_upload_limited(
        file,
        fallback_name=f"{source_key}.xlsx",
        max_bytes=MAX_SOURCE_FILE_BYTES,
    )
    upload = MemoryUpload(name, data)
    try:
        raw = read_upload_table(upload)
        _validate_table_limits(raw, title)
        _raise_bad_numbers(_bad_numeric_issues(raw, _numeric_columns(source_key, raw)))
        normalized = validator(raw)
        duplicate_count = 0
        duplicate_warning = None
        if source_key in {"sales_volume_detail", "sales_amount_detail"}:
            duplicate_count, duplicate_warning = _duplicate_upload_warning(
                source_key, duplicate_row_issues(normalized)
            )
        path = persist_latest_source(upload, source_key, title)
        _invalidate_dashboard_cache()
        _warm_source_cache(source_key)
        return {
            "source": source_key,
            "file": path.name,
            "rows": len(raw),
            "effective_rows": len(normalized) - duplicate_count,
            "duplicate_rows_ignored": duplicate_count,
            "columns": len(raw.columns),
            "warnings": [duplicate_warning] if duplicate_warning else [],
        }
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/source/{source_key}/preview")
def preview_source(source_key: str, limit: int = 50):
    title, _ = source_or_404(source_key)
    path = get_latest_source_path(source_key)
    if not path:
        raise HTTPException(404, f"尚未上传{title}")
    try:
        from backend.dashboard_api import load_source_frame

        frame = load_source_frame(source_key, title)
        bounded_limit = min(max(limit, 1), 200)
        return {
            "title": title,
            "columns": list(frame.columns),
            "rows": frame_records(frame.head(bounded_limit)),
            "total": len(frame),
            "updated_at": path.stat().st_mtime,
        }
    except Exception as exc:
        raise HTTPException(422, f"{title}读取失败：{exc}") from exc


@router.get("/source/{source_key}/download")
def download_source(source_key: str):
    title, _ = source_or_404(source_key)
    path = get_latest_source_path(source_key)
    if not path:
        raise HTTPException(404, f"尚未上传{title}")
    return FileResponse(path, filename=path.name)


@router.delete("/source/{source_key}")
def delete_source(source_key: str):
    source_or_404(source_key)
    path = get_latest_source_path(source_key)
    index = latest_source_index_path(source_key)
    if path and path.exists():
        path.unlink()
    if index.exists():
        index.unlink()
    _invalidate_dashboard_cache()
    return {"ok": True}


@router.get("/sales-history/{month}/download")
def download_sales_history(month: str):
    try:
        valid_month = validate_report_month(month)
        records = load_sales_history_records()
        match = records[records["月份"].eq(valid_month)]
        if match.empty:
            raise HTTPException(404, "销量历史月份不存在")
        history_dir = (DATA_DIR / "sales_history").resolve()
        path = (history_dir / f"{valid_month}.csv").resolve()
        if path.parent != history_dir or not path.exists():
            raise HTTPException(404, "销量历史文件不存在")
        download_name = safe_upload_name(str(match.iloc[0]["原始文件名"]), f"{valid_month}.csv", {".csv"})
        return FileResponse(path, filename=download_name, media_type="text/csv")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/sales-history")
def clear_sales_history():
    try:
        deleted = delete_sales_history()
        _invalidate_dashboard_cache()
        return {"ok": True, "deleted": deleted}
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/performance/{month}")
def remove_report(month: str):
    try:
        valid_month = validate_report_month(month)
        if not delete_upload_record(valid_month):
            raise HTTPException(404, "报表不存在")
        _invalidate_dashboard_cache()
        return {"ok": True}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/performance/{month}/download")
def download_report(month: str):
    try:
        valid_month = validate_report_month(month)
        records = load_upload_records()
        match = records[records["月份"].eq(valid_month)]
        if match.empty:
            raise HTTPException(404, "报表不存在")
        # report_store guarantees the only accepted basename is <validated month>.csv.
        path = (DATA_DIR / "reports" / f"{valid_month}.csv").resolve()
        reports_dir = (DATA_DIR / "reports").resolve()
        if path.parent != reports_dir or not path.exists():
            raise HTTPException(404, "报表文件不存在")
        download_name = safe_upload_name(str(match.iloc[0]["原始文件名"]), f"{valid_month}.csv", {".csv"})
        return FileResponse(path, filename=download_name, media_type="text/csv")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
