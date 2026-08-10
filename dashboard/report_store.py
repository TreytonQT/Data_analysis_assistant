from __future__ import annotations

import os
import re
import tempfile
import calendar
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from dashboard.data_processing import normalize_report, read_csv_bytes, read_local_table
from app_paths import APP_ROOT, DATA_DIR

ROOT = APP_ROOT
REPORTS_DIR = DATA_DIR / "reports"
SOURCES_DIR = DATA_DIR / "sources"
INDEX_PATH = DATA_DIR / "upload_records.csv"
SALES_HISTORY_DIR = DATA_DIR / "sales_history"
SALES_HISTORY_INDEX_PATH = DATA_DIR / "sales_history_records.csv"
INDEX_COLUMNS = ["月份", "原始文件名", "保存文件名", "上传时间", "文件大小"]
OPERATIONAL_SALES_BASENAME = "operational_sales"
OPERATIONAL_SALES_INDEX_PATH = SOURCES_DIR / "operational_sales_source.csv"
SOURCE_INDEX_COLUMNS = ["数据源", "原始文件名", "保存文件名", "上传时间", "文件大小"]
LATEST_SOURCE_DISPLAY_NAMES = {
    "operational_sales": "运营原始表",
    "gross_profit": "毛利原始表",
    "rating": "Rating",
    "sales_volume_detail": "销量明细",
    "sales_amount_detail": "销售额明细",
    "sales_history_rolling": "往月销量原始表",
}
ALLOWED_SOURCE_SUFFIXES = (".xlsx", ".xls", ".csv")
STRICT_MONTH_PATTERN = re.compile(r"(?P<year>[1-9]\d{3})-(?P<month>0[1-9]|1[0-2])")
REPORT_MONTH_RANGE_PATTERN = re.compile(
    r"(?P<start>\d{4}-\d{2}-\d{2})\s*[~～]\s*(?P<end>\d{4}-\d{2}-\d{2})"
)


@dataclass(frozen=True)
class PersistResult:
    month: str
    original_name: str
    saved_name: str
    replaced: bool


@dataclass(frozen=True)
class PersistSalesHistoryResult:
    month: str
    original_name: str
    saved_name: str
    replaced: bool


def validate_report_month(value: object) -> str:
    """Return a canonical report month, accepting only a legal YYYY-MM value."""

    text = str(value).strip()
    if not STRICT_MONTH_PATTERN.fullmatch(text):
        raise ValueError(f"月份必须是合法的 YYYY-MM：{text or '空值'}")
    return text


def normalize_uploaded_report_month(value: object, *, today: date | None = None) -> str:
    """Normalize an upload cell while rejecting ambiguous or partial dates."""

    text = str(value).strip()
    if STRICT_MONTH_PATTERN.fullmatch(text):
        return validate_report_month(text)
    match = REPORT_MONTH_RANGE_PATTERN.fullmatch(text)
    if not match:
        raise ValueError(f"月份必须是合法的 YYYY-MM：{text or '空值'}")
    try:
        start = datetime.strptime(match.group("start"), "%Y-%m-%d").date()
        end = datetime.strptime(match.group("end"), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"月份日期范围不合法：{text}") from exc
    if (start.year, start.month) != (end.year, end.month) or start > end:
        raise ValueError(f"月份日期范围必须覆盖同一个完整自然月：{text}")
    current_day = today or date.today()
    is_current_month = (start.year, start.month) == (current_day.year, current_day.month)
    last_day = calendar.monthrange(start.year, start.month)[1]
    if not is_current_month and (start.day != 1 or end.day != last_day):
        raise ValueError(f"月份日期范围必须覆盖同一个完整自然月：{text}")
    return f"{start.year:04d}-{start.month:02d}"


def validate_source_key(source_key: str) -> str:
    key = str(source_key).strip()
    if key not in LATEST_SOURCE_DISPLAY_NAMES:
        raise ValueError(f"未知数据源：{key or '空值'}")
    return key


def _contained_path(directory: Path, saved_name: object, allowed_names: set[str]) -> Path:
    name = str(saved_name).strip()
    if name not in allowed_names or Path(name).name != name:
        raise ValueError(f"非法保存文件名：{name or '空值'}")
    root = directory.resolve()
    candidate = directory / name
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError(f"保存文件超出指定目录：{name}") from exc
    return candidate


def _report_path(reports_dir: Path, month: str, saved_name: object | None = None) -> Path:
    valid_month = validate_report_month(month)
    expected_name = f"{valid_month}.csv"
    return _contained_path(reports_dir, expected_name if saved_name is None else saved_name, {expected_name})


def sales_history_index_path(data_dir: Path = DATA_DIR) -> Path:
    return data_dir / "sales_history_records.csv"


def _sales_history_path(history_dir: Path, month: str, saved_name: object | None = None) -> Path:
    valid_month = validate_report_month(month)
    expected_name = f"{valid_month}.csv"
    return _contained_path(history_dir, expected_name if saved_name is None else saved_name, {expected_name})


def _source_path(sources_dir: Path, source_key: str, saved_name: object) -> Path:
    key = validate_source_key(source_key)
    allowed_names = {f"{key}{suffix}" for suffix in ALLOWED_SOURCE_SUFFIXES}
    return _contained_path(sources_dir, saved_name, allowed_names)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def _atomic_write_frame(path: Path, frame: pd.DataFrame) -> None:
    _atomic_write_bytes(path, _csv_bytes(frame))


def _snapshot(paths: Iterable[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore_snapshot(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            if path.exists():
                path.unlink()
        else:
            _atomic_write_bytes(path, content)


def ensure_storage(data_dir: Path = DATA_DIR) -> tuple[Path, Path]:
    reports_dir = data_dir / "reports"
    index_path = data_dir / "upload_records.csv"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir, index_path


def ensure_sales_history_storage(data_dir: Path = DATA_DIR) -> tuple[Path, Path]:
    history_dir = data_dir / "sales_history"
    index_path = sales_history_index_path(data_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir, index_path


def ensure_sources_storage(data_dir: Path = DATA_DIR) -> tuple[Path, Path]:
    sources_dir = data_dir / "sources"
    index_path = sources_dir / "operational_sales_source.csv"
    sources_dir.mkdir(parents=True, exist_ok=True)
    return sources_dir, index_path


def latest_source_index_path(source_key: str, data_dir: Path = DATA_DIR) -> Path:
    source_key = validate_source_key(source_key)
    sources_dir = data_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    return sources_dir / f"{source_key}_source.csv"


def load_upload_records(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    _, index_path = ensure_storage(data_dir)
    if not index_path.exists():
        return pd.DataFrame(columns=INDEX_COLUMNS)
    records = pd.read_csv(index_path, encoding="utf-8-sig", dtype=str).fillna("")
    for col in INDEX_COLUMNS:
        if col not in records.columns:
            records[col] = ""
    records = records[INDEX_COLUMNS]
    for _, record in records.iterrows():
        month = validate_report_month(record["月份"])
        _report_path(data_dir / "reports", month, record["保存文件名"])
    return records.sort_values("月份").reset_index(drop=True)


def save_upload_records(records: pd.DataFrame, data_dir: Path = DATA_DIR) -> None:
    _, index_path = ensure_storage(data_dir)
    clean = records.copy()
    for col in INDEX_COLUMNS:
        if col not in clean.columns:
            clean[col] = ""
    clean = clean[INDEX_COLUMNS].sort_values("月份").reset_index(drop=True)
    for _, record in clean.iterrows():
        month = validate_report_month(record["月份"])
        _report_path(data_dir / "reports", month, record["保存文件名"])
    _atomic_write_frame(index_path, clean)


def load_sales_history_records(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    history_dir, index_path = ensure_sales_history_storage(data_dir)
    if not index_path.exists():
        return pd.DataFrame(columns=INDEX_COLUMNS)
    records = pd.read_csv(index_path, encoding="utf-8-sig", dtype=str).fillna("")
    for col in INDEX_COLUMNS:
        if col not in records.columns:
            records[col] = ""
    records = records[INDEX_COLUMNS].copy()
    for _, record in records.iterrows():
        _sales_history_path(history_dir, record["月份"], record["保存文件名"])
    if records["月份"].duplicated().any():
        raise ValueError("往月销量原始表索引包含重复月份")
    return records.sort_values("月份").reset_index(drop=True)


def save_sales_history_records(records: pd.DataFrame, data_dir: Path = DATA_DIR) -> None:
    history_dir, index_path = ensure_sales_history_storage(data_dir)
    clean = records.copy()
    for col in INDEX_COLUMNS:
        if col not in clean.columns:
            clean[col] = ""
    clean = clean[INDEX_COLUMNS].copy()
    if clean["月份"].duplicated().any():
        raise ValueError("往月销量原始表索引包含重复月份")
    clean = clean.sort_values("月份").reset_index(drop=True)
    for _, record in clean.iterrows():
        _sales_history_path(history_dir, record["月份"], record["保存文件名"])
    _atomic_write_frame(index_path, clean)


def get_sales_history_paths(data_dir: Path = DATA_DIR) -> list[Path]:
    history_dir, _ = ensure_sales_history_storage(data_dir)
    records = load_sales_history_records(data_dir)
    paths: list[Path] = []
    for _, record in records.iterrows():
        path = _sales_history_path(history_dir, record["月份"], record["保存文件名"])
        if path.exists():
            paths.append(path)
    return paths


def _month_distance(start: str, end: str) -> int:
    start_year, start_month = (int(part) for part in start.split("-"))
    end_year, end_month = (int(part) for part in end.split("-"))
    return (end_year - start_year) * 12 + end_month - start_month


def _require_contiguous_months(months: Iterable[str], *, title: str = "往月销量原始表") -> list[str]:
    ordered = sorted({validate_report_month(month) for month in months})
    if not ordered:
        return []
    if any(_month_distance(previous, current) != 1 for previous, current in zip(ordered, ordered[1:])):
        raise ValueError(f"{title}必须保留连续月份")
    return ordered


def _sales_history_month_from_filename(name: str, *, today: date | None = None) -> str:
    match = REPORT_MONTH_RANGE_PATTERN.search(str(name))
    if not match:
        raise ValueError(f"往月销量原始表文件名必须包含完整日期范围：{name}")
    try:
        start = datetime.strptime(match.group("start"), "%Y-%m-%d").date()
        end = datetime.strptime(match.group("end"), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"往月销量原始表日期范围不合法：{name}") from exc
    if (start.year, start.month) != (end.year, end.month) or start > end:
        raise ValueError(f"往月销量原始表必须覆盖同一个完整自然月：{name}")
    last_day = calendar.monthrange(start.year, start.month)[1]
    if start.day != 1 or end.day != last_day:
        raise ValueError(f"往月销量原始表必须覆盖完整自然月：{name}")
    current = today or pd.Timestamp.now(tz="Asia/Shanghai").date()
    if (start.year, start.month) >= (current.year, current.month):
        raise ValueError(f"往月销量原始表不能上传当前月或未来月份：{start:%Y-%m}")
    return f"{start.year:04d}-{start.month:02d}"


def persist_uploaded_sales_history(
    uploaded_files: Iterable,
    data_dir: Path = DATA_DIR,
    *,
    today: date | None = None,
) -> tuple[list[PersistSalesHistoryResult], list[str]]:
    """Validate and atomically persist the rolling twelve-month CSV window."""

    from dashboard.data_processing import normalize_sales_history_month_source, read_csv_bytes

    history_dir, index_path = ensure_sales_history_storage(data_dir)
    existing = load_sales_history_records(data_dir)
    uploads = list(uploaded_files)
    if not uploads:
        raise ValueError("没有上传往月销量原始表")

    prepared: list[tuple[object, bytes, str, str]] = []
    batch_months: set[str] = set()
    for uploaded_file in uploads:
        suffix = Path(str(uploaded_file.name)).suffix.lower()
        if suffix != ".csv":
            raise ValueError(f"往月销量原始表只支持 CSV：{uploaded_file.name}")
        data = uploaded_file.getvalue()
        if not isinstance(data, bytes) or not data:
            raise ValueError(f"往月销量原始表文件为空：{uploaded_file.name}")
        month = _sales_history_month_from_filename(uploaded_file.name, today=today)
        if month in batch_months:
            raise ValueError(f"同一批次包含重复月份：{month}")
        frame = read_csv_bytes(data)
        normalize_sales_history_month_source(frame, month)
        batch_months.add(month)
        prepared.append((uploaded_file, data, month, f"{month}.csv"))

    existing_months = set(existing["月份"].astype(str))
    candidate_months = existing_months | batch_months
    if not existing_months:
        if len(batch_months) != 12:
            raise ValueError("首次上传必须一次提供连续12个完整自然月")
    else:
        for month in batch_months:
            if month not in existing_months and month < min(existing_months):
                raise ValueError(f"月份 {month} 已超出当前滚动窗口")
    ordered = _require_contiguous_months(candidate_months)
    if len(ordered) < 12:
        raise ValueError("往月销量原始表必须保留连续12个月")
    retained = ordered[-12:]
    _require_contiguous_months(retained)
    retained_set = set(retained)
    evicted = sorted(candidate_months - retained_set)

    next_records = existing[~existing["月份"].isin(set(evicted) | batch_months)].copy()
    rows = []
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results: list[PersistSalesHistoryResult] = []
    for uploaded_file, data, month, saved_name in prepared:
        if month not in retained_set:
            raise ValueError(f"月份 {month} 不在最新12个月窗口内")
        replaced = month in existing_months
        rows.append(
            {
                "月份": month,
                "原始文件名": uploaded_file.name,
                "保存文件名": saved_name,
                "上传时间": now_text,
                "文件大小": str(len(data)),
            }
        )
        results.append(PersistSalesHistoryResult(month, uploaded_file.name, saved_name, replaced))
    next_records = pd.concat([next_records, pd.DataFrame(rows, columns=INDEX_COLUMNS)], ignore_index=True)
    next_records = next_records[next_records["月份"].isin(retained_set)].sort_values("月份").reset_index(drop=True)

    upload_paths = [_sales_history_path(history_dir, month, saved_name) for _, _, month, saved_name in prepared]
    evicted_paths = [
        _sales_history_path(history_dir, month, str(existing.loc[existing["月份"].eq(month), "保存文件名"].iloc[0]))
        for month in evicted
        if not existing.loc[existing["月份"].eq(month)].empty
    ]
    snapshot = _snapshot([*upload_paths, *evicted_paths, index_path])
    try:
        for (_, data, _, _), path in zip(prepared, upload_paths):
            _atomic_write_bytes(path, data)
        for path in evicted_paths:
            if path.exists():
                path.unlink()
        save_sales_history_records(next_records, data_dir)
    except Exception:
        _restore_snapshot(snapshot)
        raise
    return results, evicted


def delete_sales_history(data_dir: Path = DATA_DIR) -> bool:
    history_dir, index_path = ensure_sales_history_storage(data_dir)
    records = load_sales_history_records(data_dir)
    paths = [_sales_history_path(history_dir, row["月份"], row["保存文件名"]) for _, row in records.iterrows()]
    snapshot = _snapshot([*paths, index_path])
    try:
        for path in paths:
            if path.exists():
                path.unlink()
        if index_path.exists():
            index_path.unlink()
    except Exception:
        _restore_snapshot(snapshot)
        raise
    return bool(paths)


def load_operational_sales_source_record(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    return load_latest_source_record("operational_sales", data_dir)


def load_latest_source_record(source_key: str, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    source_key = validate_source_key(source_key)
    index_path = latest_source_index_path(source_key, data_dir)
    if not index_path.exists():
        return pd.DataFrame(columns=SOURCE_INDEX_COLUMNS)
    records = pd.read_csv(index_path, encoding="utf-8-sig", dtype=str).fillna("")
    for col in SOURCE_INDEX_COLUMNS:
        if col not in records.columns:
            records[col] = ""
    records = records[SOURCE_INDEX_COLUMNS].reset_index(drop=True)
    for saved_name in records["保存文件名"]:
        _source_path(data_dir / "sources", source_key, saved_name)
    return records


def get_operational_sales_source_path(data_dir: Path = DATA_DIR) -> Path | None:
    return get_latest_source_path("operational_sales", data_dir)


def get_latest_source_path(source_key: str, data_dir: Path = DATA_DIR) -> Path | None:
    source_key = validate_source_key(source_key)
    sources_dir = data_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    records = load_latest_source_record(source_key, data_dir)
    if not records.empty:
        saved_name = str(records.iloc[-1]["保存文件名"])
        path = _source_path(sources_dir, source_key, saved_name)
        if path.exists():
            return path
    for suffix in ALLOWED_SOURCE_SUFFIXES:
        path = _source_path(sources_dir, source_key, f"{source_key}{suffix}")
        if path.exists():
            return path
    return None


def persist_operational_sales_source(uploaded_file, data_dir: Path = DATA_DIR) -> Path:
    return persist_latest_source(uploaded_file, "operational_sales", LATEST_SOURCE_DISPLAY_NAMES["operational_sales"], data_dir)


def persist_latest_source(uploaded_file, source_key: str, display_name: str | None = None, data_dir: Path = DATA_DIR) -> Path:
    source_key = validate_source_key(source_key)
    sources_dir = data_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    index_path = latest_source_index_path(source_key, data_dir)
    data = uploaded_file.getvalue()
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in ALLOWED_SOURCE_SUFFIXES:
        raise ValueError(f"不支持的数据源文件类型：{suffix or '无扩展名'}")
    if not isinstance(data, bytes) or not data:
        raise ValueError("数据源文件为空")
    saved_name = f"{source_key}{suffix}"
    saved_path = _source_path(sources_dir, source_key, saved_name)
    records = pd.DataFrame(
        [
            {
                "数据源": display_name or LATEST_SOURCE_DISPLAY_NAMES.get(source_key, source_key),
                "原始文件名": uploaded_file.name,
                "保存文件名": saved_name,
                "上传时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "文件大小": str(len(data)),
            }
        ],
        columns=SOURCE_INDEX_COLUMNS,
    )
    source_paths = [
        _source_path(sources_dir, source_key, f"{source_key}{candidate_suffix}")
        for candidate_suffix in ALLOWED_SOURCE_SUFFIXES
    ]
    snapshot = _snapshot([*source_paths, index_path])
    try:
        _atomic_write_bytes(saved_path, data)
        _atomic_write_frame(index_path, records)
        for old_path in source_paths:
            if old_path != saved_path and old_path.exists():
                old_path.unlink()
    except Exception:
        _restore_snapshot(snapshot)
        raise
    return saved_path


def detect_report_month(data: bytes) -> str:
    frame = read_csv_bytes(data)
    required = ["销售专员", "月份", "店铺"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"业绩报表缺少基础列：{', '.join(missing)}")
    if frame.empty:
        raise ValueError("业绩报表没有数据行")
    for column in ["销售专员", "店铺"]:
        blank = frame[column].isna() | frame[column].astype(str).str.strip().eq("")
        if blank.any():
            row_number = int(blank.to_numpy().nonzero()[0][0]) + 2
            raise ValueError(f"业绩报表第 {row_number} 行{column}为空")
    months = []
    for row_number, value in enumerate(frame["月份"], start=2):
        try:
            months.append(normalize_uploaded_report_month(value))
        except ValueError as exc:
            raise ValueError(f"业绩报表第 {row_number} 行{exc}") from exc
    months = sorted(set(months))
    if len(months) > 1:
        raise ValueError(f"单个报表只能包含一个月份，当前包含：{', '.join(months)}")
    normalize_report(frame)
    return months[0]


def persist_uploaded_reports(uploaded_files: Iterable, data_dir: Path = DATA_DIR) -> list[PersistResult]:
    reports_dir, _ = ensure_storage(data_dir)
    records = load_upload_records(data_dir)
    uploads = list(uploaded_files)
    if not uploads:
        raise ValueError("没有上传业绩报表")

    prepared: list[tuple[object, bytes, str, str]] = []
    batch_months: set[str] = set()
    for uploaded_file in uploads:
        suffix = Path(str(uploaded_file.name)).suffix.lower()
        if suffix != ".csv":
            raise ValueError(f"业绩报表只支持 CSV：{uploaded_file.name}")
        data = uploaded_file.getvalue()
        if not isinstance(data, bytes) or not data:
            raise ValueError(f"业绩报表文件为空：{uploaded_file.name}")
        month = detect_report_month(data)
        if month in batch_months:
            raise ValueError(f"同一批次包含重复月份：{month}")
        batch_months.add(month)
        prepared.append((uploaded_file, data, month, f"{month}.csv"))

    next_records = records.copy()
    results: list[PersistResult] = []
    for uploaded_file, data, month, saved_name in prepared:
        existing = next_records[next_records["月份"].eq(month)]
        replaced = not existing.empty
        next_records = next_records[~next_records["月份"].eq(month)]
        next_records = pd.concat(
            [
                next_records,
                pd.DataFrame(
                    [
                        {
                            "月份": month,
                            "原始文件名": uploaded_file.name,
                            "保存文件名": saved_name,
                            "上传时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "文件大小": str(len(data)),
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        results.append(PersistResult(month, uploaded_file.name, saved_name, replaced))

    _, index_path = ensure_storage(data_dir)
    report_paths = [_report_path(reports_dir, month, saved_name) for _, _, month, saved_name in prepared]
    snapshot = _snapshot([*report_paths, index_path])
    try:
        for (_, data, _, _), saved_path in zip(prepared, report_paths):
            _atomic_write_bytes(saved_path, data)
        save_upload_records(next_records, data_dir)
    except Exception:
        _restore_snapshot(snapshot)
        raise
    return results


def delete_upload_record(month: str, data_dir: Path = DATA_DIR) -> bool:
    month = validate_report_month(month)
    reports_dir, _ = ensure_storage(data_dir)
    records = load_upload_records(data_dir)
    existing = records[records["月份"].eq(month)]
    if existing.empty:
        return False
    paths = []
    for saved_name in existing["保存文件名"].dropna().unique():
        paths.append(_report_path(reports_dir, month, saved_name))
    records = records[~records["月份"].eq(month)]
    save_upload_records(records, data_dir)
    for path in paths:
        if path.exists():
            path.unlink()
    return True


def load_reports_from_records(records: pd.DataFrame, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    reports_dir, _ = ensure_storage(data_dir)
    frames = []
    for _, record in records.iterrows():
        month = validate_report_month(record["月份"])
        path = _report_path(reports_dir, month, record["保存文件名"])
        if not path.exists():
            continue
        frame = read_local_table(path).copy()
        frame["来源文件"] = record["原始文件名"] or path.name
        frames.append(frame)
    if not frames:
        raise ValueError("没有可读取的历史业绩报表")
    return normalize_report(pd.concat(frames, ignore_index=True))
