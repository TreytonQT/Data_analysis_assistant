from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from dashboard.data_processing import normalize_month, normalize_report, read_csv_bytes, read_local_table


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"
INDEX_PATH = DATA_DIR / "upload_records.csv"
INDEX_COLUMNS = ["月份", "原始文件名", "保存文件名", "上传时间", "文件大小"]


@dataclass(frozen=True)
class PersistResult:
    month: str
    original_name: str
    saved_name: str
    replaced: bool


def ensure_storage(data_dir: Path = DATA_DIR) -> tuple[Path, Path]:
    reports_dir = data_dir / "reports"
    index_path = data_dir / "upload_records.csv"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir, index_path


def load_upload_records(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    _, index_path = ensure_storage(data_dir)
    if not index_path.exists():
        return pd.DataFrame(columns=INDEX_COLUMNS)
    records = pd.read_csv(index_path, encoding="utf-8-sig", dtype=str).fillna("")
    for col in INDEX_COLUMNS:
        if col not in records.columns:
            records[col] = ""
    return records[INDEX_COLUMNS].sort_values("月份").reset_index(drop=True)


def save_upload_records(records: pd.DataFrame, data_dir: Path = DATA_DIR) -> None:
    _, index_path = ensure_storage(data_dir)
    clean = records.copy()
    for col in INDEX_COLUMNS:
        if col not in clean.columns:
            clean[col] = ""
    clean = clean[INDEX_COLUMNS].sort_values("月份").reset_index(drop=True)
    clean.to_csv(index_path, index=False, encoding="utf-8-sig")


def detect_report_month(data: bytes) -> str:
    frame = read_csv_bytes(data)
    if "月份" not in frame.columns:
        raise ValueError("业绩报表缺少月份列")
    months = sorted({normalize_month(value) for value in frame["月份"].dropna().unique() if normalize_month(value)})
    if not months:
        raise ValueError("业绩报表月份为空")
    if len(months) > 1:
        raise ValueError(f"单个报表只能包含一个月份，当前包含：{', '.join(months)}")
    return months[0]


def persist_uploaded_reports(uploaded_files: Iterable, data_dir: Path = DATA_DIR) -> list[PersistResult]:
    reports_dir, _ = ensure_storage(data_dir)
    records = load_upload_records(data_dir)
    results: list[PersistResult] = []

    for uploaded_file in uploaded_files:
        data = uploaded_file.getvalue()
        month = detect_report_month(data)
        saved_name = f"{month}.csv"
        saved_path = reports_dir / saved_name

        existing = records[records["月份"].eq(month)]
        replaced = not existing.empty
        if replaced:
            for old_name in existing["保存文件名"].dropna().unique():
                old_path = reports_dir / str(old_name)
                if old_path.exists() and old_path.name != saved_name:
                    old_path.unlink()
            records = records[~records["月份"].eq(month)]

        saved_path.write_bytes(data)
        records = pd.concat(
            [
                records,
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

    save_upload_records(records, data_dir)
    return results


def delete_upload_record(month: str, data_dir: Path = DATA_DIR) -> bool:
    reports_dir, _ = ensure_storage(data_dir)
    records = load_upload_records(data_dir)
    existing = records[records["月份"].eq(month)]
    if existing.empty:
        return False
    for saved_name in existing["保存文件名"].dropna().unique():
        path = reports_dir / str(saved_name)
        if path.exists():
            path.unlink()
    records = records[~records["月份"].eq(month)]
    save_upload_records(records, data_dir)
    return True


def load_reports_from_records(records: pd.DataFrame, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    reports_dir, _ = ensure_storage(data_dir)
    frames = []
    for _, record in records.iterrows():
        path = reports_dir / str(record["保存文件名"])
        if not path.exists():
            continue
        frame = read_local_table(path).copy()
        frame["来源文件"] = record["原始文件名"] or path.name
        frames.append(frame)
    if not frames:
        raise ValueError("没有可读取的历史业绩报表")
    return normalize_report(pd.concat(frames, ignore_index=True))
