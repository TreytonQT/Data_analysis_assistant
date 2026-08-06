from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from backend.db import LOCAL_TIMEZONE, ROOT, connect, initialize_database
from backend.upload_safety import read_upload_limited
from dashboard.data_processing import read_csv_bytes, read_local_table
from dashboard.parquet_cache import load_or_build_parquet, revision_digest
from dashboard.report_store import get_latest_source_path


router = APIRouter(prefix="/api/batch-monitor", tags=["batch-monitor"])

BATCH_UPLOAD_DIR = ROOT / "data" / "batch_monitor" / "uploads"
MAX_BATCH_FILE_BYTES = 20 * 1024 * 1024
REQUIRED_BATCH_COLUMNS = ("SKU", "DE_PRICE", "FR_PRICE", "ES_PRICE", "IT_PRICE")
REQUIRED_SHIPMENT_COLUMNS = ("货件单号", "MSKU", "ASIN")
REQUIRED_LAUNCH_PRICE_COLUMNS = ("SKU", "DE开售价格", "FR开售价格", "ES开售价格", "IT开售价格")
LAUNCH_PRICE_DB_COLUMNS = {
    "DE开售价格": "de_price",
    "FR开售价格": "fr_price",
    "ES开售价格": "es_price",
    "IT开售价格": "it_price",
}
IDENTIFIER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{2,63}$")
BATCH_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,31}$")
ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")


class ArtworkUpdate(BaseModel):
    completed: bool


class ArrivalUpdate(BaseModel):
    arrived: bool = True
    arrival_date: date | None = None


class ShipmentArrivalUpdate(BaseModel):
    arrival_date: date


def _now() -> datetime:
    return datetime.now(LOCAL_TIMEZONE).replace(microsecond=0)


def _now_iso() -> str:
    return _now().isoformat()


def _today_iso() -> str:
    return _now().date().isoformat()


def _normalize_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().upper()


def _operational_developer_maps() -> tuple[dict[str, str], dict[str, str]]:
    """Return all current SKU developers and the creation-eligible Chen subset."""

    path = get_latest_source_path("operational_sales")
    if not path:
        raise ValueError("请先到上传中心上传运营原始表，再新建批次")
    frame = load_or_build_parquet(
        "batch-monitor-operational-scope",
        [path],
        lambda: read_local_table(path),
    )
    missing = [column for column in ("MSKU", "开发员") if column not in frame.columns]
    if missing:
        raise ValueError("运营原始表缺少列：" + "、".join(missing))

    developer_sets: dict[str, set[str]] = {}
    for sku_value, developer_value in zip(frame["MSKU"], frame["开发员"]):
        sku = _normalize_text(sku_value)
        if not sku:
            continue
        developer = "" if developer_value is None or pd.isna(developer_value) else str(developer_value).strip()
        if developer:
            developer_sets.setdefault(sku, set()).add(developer)
        else:
            developer_sets.setdefault(sku, set())
    all_developers = {
        sku: "；".join(sorted(developers))
        for sku, developers in developer_sets.items()
    }
    eligible = {
        sku: developer_text
        for sku, developer_text in all_developers.items()
        if any("陈千潼" in developer for developer in developer_sets[sku])
    }
    return all_developers, eligible


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive_file(kind: str, name: str, data: bytes, digest: str) -> Path:
    BATCH_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(name).suffix.lower()
    path = BATCH_UPLOAD_DIR / f"{kind}-{digest[:20]}{suffix}"
    if not path.exists():
        path.write_bytes(data)
    return path


def _touch_revision(conn) -> str:
    timestamp = _now_iso()
    value = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO batch_monitor_meta (key, value, updated_at)
        VALUES ('revision', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (value, timestamp),
    )
    return value


def batch_monitor_revision() -> str:
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT value FROM batch_monitor_meta WHERE key = 'revision'"
            ).fetchone()
        database_revision = str(row["value"]) if row else "empty"
        operational_path = get_latest_source_path("operational_sales")
        orphan_scope_revision = (
            revision_digest("batch-monitor-orphan-scope", [operational_path])
            if operational_path
            else "missing-operational-source"
        )
        return f"{database_revision}:{orphan_scope_revision}"
    except Exception:
        return "empty"


def _write_import_record(
    conn,
    *,
    digest: str,
    import_type: str,
    file_name: str,
    stats: dict[str, Any],
    replace: bool = False,
) -> None:
    verb = "INSERT OR REPLACE" if replace else "INSERT"
    conn.execute(
        f"""{verb} INTO batch_monitor_imports
        (file_hash, import_type, file_name, stats_json, imported_at)
        VALUES (?, ?, ?, ?, ?)""",
        (
            digest,
            import_type,
            file_name,
            json.dumps(stats, ensure_ascii=False, separators=(",", ":")),
            _now_iso(),
        ),
    )


def _matching_batch_sheet(data: bytes) -> tuple[str, pd.DataFrame]:
    try:
        workbook = pd.ExcelFile(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"Excel无法读取：{exc}") from exc

    matches: list[tuple[str, pd.DataFrame]] = []
    for sheet_name in workbook.sheet_names:
        frame = workbook.parse(sheet_name=sheet_name, dtype=object)
        normalized_columns = [str(column).strip().upper() for column in frame.columns]
        if len(normalized_columns) != len(set(normalized_columns)):
            raise ValueError(f"sheet“{sheet_name}”包含重复列名")
        frame.columns = normalized_columns
        if set(REQUIRED_BATCH_COLUMNS).issubset(frame.columns):
            matches.append((sheet_name, frame))
    if not matches:
        raise ValueError(
            "找不到同时包含SKU、DE_PRICE、FR_PRICE、ES_PRICE、IT_PRICE的sheet"
        )
    if len(matches) > 1:
        raise ValueError(
            "存在多个符合批次格式的sheet：" + "、".join(name for name, _ in matches)
        )
    return matches[0]


def _is_template_metadata(values: list[Any]) -> bool:
    if len(values) != len(REQUIRED_BATCH_COLUMNS):
        return False
    parsed = pd.to_numeric(pd.Series(values), errors="coerce")
    return bool(parsed.notna().all() and parsed.eq(137).all())


def _parse_batch_workbook_source(data: bytes) -> tuple[str, list[dict[str, Any]]]:
    sheet_name, frame = _matching_batch_sheet(data)
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    for index, source in frame.iterrows():
        excel_row = int(index) + 2
        values = [source.get(column) for column in REQUIRED_BATCH_COLUMNS]
        if all(value is None or pd.isna(value) or str(value).strip() == "" for value in values):
            continue
        if _is_template_metadata(values):
            continue
        sku = _normalize_text(source.get("SKU"))
        if (
            not sku
            or not IDENTIFIER_PATTERN.fullmatch(sku)
            or not any(character.isalpha() for character in sku)
        ):
            issues.append(f"第{excel_row}行SKU无效：{source.get('SKU')}")
            continue
        rows.append(
            {
                "sku": sku,
                "row": excel_row,
                **{
                    column: source.get(column)
                    for column in REQUIRED_BATCH_COLUMNS[1:]
                },
            }
        )
    if issues:
        raise ValueError("批次文件校验失败：" + "；".join(issues[:10]))
    if not rows:
        raise ValueError("批次文件没有有效SKU")
    duplicates = pd.Series([row["sku"] for row in rows]).value_counts()
    duplicate_skus = duplicates[duplicates.gt(1)].index.tolist()
    if duplicate_skus:
        raise ValueError("批次文件包含重复SKU：" + "、".join(duplicate_skus[:10]))
    return sheet_name, rows


def _validate_batch_prices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    issues: list[str] = []
    for row in rows:
        prices: dict[str, float] = {}
        for column in REQUIRED_BATCH_COLUMNS[1:]:
            parsed = pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
            if pd.isna(parsed) or float(parsed) <= 0:
                issues.append(f"第{row['row']}行{column}必须为正数")
                break
            prices[column] = float(parsed)
        else:
            validated.append({**row, **prices})
    if issues:
        raise ValueError("批次文件校验失败：" + "；".join(issues[:10]))
    return validated


def parse_batch_workbook(data: bytes) -> tuple[str, list[dict[str, Any]]]:
    """Strict workbook parser retained for standalone validation and tests."""

    sheet_name, rows = _parse_batch_workbook_source(data)
    return sheet_name, _validate_batch_prices(rows)


def _parse_shipment_rows(data: bytes) -> list[dict[str, str]]:
    try:
        frame = read_csv_bytes(data)
    except Exception as exc:
        raise ValueError(f"货件CSV无法读取：{exc}") from exc
    normalized_columns = [str(column).strip() for column in frame.columns]
    if len(normalized_columns) != len(set(normalized_columns)):
        raise ValueError("货件CSV包含重复列名")
    frame.columns = normalized_columns
    missing = [column for column in REQUIRED_SHIPMENT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError("货件CSV缺少列：" + "、".join(missing))

    rows: list[dict[str, str]] = []
    issues: list[str] = []
    by_sku: dict[str, dict[str, str]] = {}
    for index, source in frame.iterrows():
        excel_row = int(index) + 2
        values = [source.get(column) for column in REQUIRED_SHIPMENT_COLUMNS]
        if all(value is None or pd.isna(value) or str(value).strip() == "" for value in values):
            continue
        shipment_no = _normalize_text(source.get("货件单号"))
        sku = _normalize_text(source.get("MSKU"))
        asin = _normalize_text(source.get("ASIN"))
        if not shipment_no or len(shipment_no) > 64:
            issues.append(f"第{excel_row}行货件单号无效")
            continue
        if not sku or not IDENTIFIER_PATTERN.fullmatch(sku):
            issues.append(f"第{excel_row}行MSKU无效：{source.get('MSKU')}")
            continue
        if not ASIN_PATTERN.fullmatch(asin):
            issues.append(f"第{excel_row}行ASIN无效：{source.get('ASIN')}")
            continue
        candidate = {"shipment_no": shipment_no, "sku": sku, "asin": asin}
        previous = by_sku.get(sku)
        if previous and previous != candidate:
            issues.append(
                f"SKU {sku}在同一文件中对应多个货件或ASIN"
            )
            continue
        if not previous:
            by_sku[sku] = candidate
            rows.append(candidate)
    if issues:
        raise ValueError("货件CSV校验失败：" + "；".join(issues[:10]))
    if not rows:
        raise ValueError("货件CSV没有有效数据")
    return rows


def _validate_batch_no(value: str) -> str:
    batch_no = _normalize_text(value)
    if not BATCH_PATTERN.fullmatch(batch_no):
        raise ValueError("批次号只能使用3至32位大写字母、数字、下划线或短横线")
    return batch_no


def create_batch_from_upload(
    batch_no: str,
    file_name: str,
    data: bytes,
) -> dict[str, Any]:
    normalized_batch = _validate_batch_no(batch_no)
    sheet_name, source_rows = _parse_batch_workbook_source(data)
    all_developers, eligible_developers = _operational_developer_maps()
    ignored_examples: list[dict[str, str]] = []
    included_source_rows: list[dict[str, Any]] = []
    for row in source_rows:
        sku = str(row["sku"])
        if sku in eligible_developers:
            included_source_rows.append(row)
            continue
        developer = all_developers.get(sku)
        ignored_examples.append(
            {
                "sku": sku,
                "reason": (
                    f"开发员不包含陈千潼（{developer or '开发员为空'}）"
                    if developer is not None
                    else "运营原始表无记录"
                ),
            }
        )
    if not included_source_rows:
        raise ValueError("批次文件没有开发员包含“陈千潼”的SKU，批次未创建")
    rows = _validate_batch_prices(included_source_rows)
    digest = _file_hash(data)
    timestamp = _now_iso()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute(
            "SELECT 1 FROM batch_monitor_batches WHERE batch_no = ?",
            (normalized_batch,),
        ).fetchone():
            raise ValueError(f"批次{normalized_batch}已存在")
        sku_values = [row["sku"] for row in rows]
        placeholders = ",".join("?" for _ in sku_values)
        conflicts = conn.execute(
            f"""SELECT sku, batch_no FROM batch_monitor_skus
            WHERE sku IN ({placeholders}) ORDER BY sku""",
            sku_values,
        ).fetchall()
        if conflicts:
            examples = "、".join(
                f"{row['sku']}（{row['batch_no']}）" for row in conflicts[:10]
            )
            raise ValueError(f"SKU已属于其他批次：{examples}")
        conn.execute(
            """INSERT INTO batch_monitor_batches
            (batch_no, artwork_completed_date, source_file_name, source_file_hash, created_at, updated_at)
            VALUES (?, NULL, ?, ?, ?, ?)""",
            (normalized_batch, file_name, digest, timestamp, timestamp),
        )
        conn.executemany(
            """INSERT INTO batch_monitor_skus
            (sku, batch_no, de_price, fr_price, es_price, it_price,
             developer_snapshot, monitor_basis, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'creation_match', ?)""",
            [
                (
                    row["sku"],
                    normalized_batch,
                    row["DE_PRICE"],
                    row["FR_PRICE"],
                    row["ES_PRICE"],
                    row["IT_PRICE"],
                    eligible_developers[row["sku"]],
                    timestamp,
                )
                for row in rows
            ],
        )
        stats = {
            "batch_no": normalized_batch,
            "sheet": sheet_name,
            "source_sku_count": len(source_rows),
            "imported_sku_count": len(rows),
            "ignored_sku_count": len(ignored_examples),
            "ignored_examples": ignored_examples[:20],
            "sku_count": len(rows),
        }
        _write_import_record(
            conn,
            digest=digest,
            import_type="batch",
            file_name=file_name,
            stats=stats,
        )
        _touch_revision(conn)
    _archive_file("batch", file_name, data, digest)
    return stats


def import_shipment_upload(file_name: str, data: bytes) -> dict[str, Any]:
    rows = _parse_shipment_rows(data)
    digest = _file_hash(data)
    timestamp = _now_iso()
    inserted = 0
    ignored = 0
    preserved_conflicts: list[dict[str, str]] = []
    unassigned = 0
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for row in rows:
            existing = conn.execute(
                """SELECT shipment_no, asin FROM sku_first_shipments
                WHERE sku = ?""",
                (row["sku"],),
            ).fetchone()
            if existing:
                ignored += 1
                if (
                    str(existing["shipment_no"]) != row["shipment_no"]
                    or str(existing["asin"]) != row["asin"]
                ):
                    preserved_conflicts.append(
                        {
                            "sku": row["sku"],
                            "kept_shipment_no": str(existing["shipment_no"]),
                            "ignored_shipment_no": row["shipment_no"],
                        }
                    )
                continue
            conn.execute(
                """INSERT INTO sku_first_shipments
                (sku, shipment_no, asin, arrival_date, updated_at)
                VALUES (?, ?, ?, NULL, ?)""",
                (
                    row["sku"],
                    row["shipment_no"],
                    row["asin"],
                    timestamp,
                ),
            )
            inserted += 1
            if not conn.execute(
                "SELECT 1 FROM batch_monitor_skus WHERE sku = ?",
                (row["sku"],),
            ).fetchone():
                unassigned += 1
        stats = {
            "rows": len(rows),
            "inserted": inserted,
            "ignored": ignored,
            "unassigned": unassigned,
            "conflicts": len(preserved_conflicts),
            "conflict_examples": preserved_conflicts[:10],
        }
        _write_import_record(
            conn,
            digest=digest,
            import_type="shipments",
            file_name=file_name,
            stats=stats,
            replace=True,
        )
        if inserted:
            _touch_revision(conn)
    _archive_file("shipments", file_name, data, digest)
    return stats


def _parse_date_cell(value: Any, *, context: str) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str) and value.strip() in {"", "无", "未到货"}:
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed = pd.Timestamp("1899-12-30") + pd.to_timedelta(float(value), unit="D")
        else:
            parsed = pd.to_datetime(value, errors="raise")
        return parsed.date().isoformat()
    except Exception as exc:
        raise ValueError(f"{context}日期无效：{value}") from exc


def _parse_launch_price_cell(value: Any, *, context: str) -> float | None:
    if value is None or pd.isna(value) or (isinstance(value, str) and not value.strip()):
        return None
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed) or not math.isfinite(float(parsed)):
        raise ValueError(f"{context}价格无效：{value}")
    number = float(parsed)
    if number == 0:
        return None
    if number < 0:
        raise ValueError(f"{context}价格不能为负数：{value}")
    return number


def _parse_launch_price_workbook(data: bytes) -> list[dict[str, Any]]:
    try:
        frame = pd.read_excel(io.BytesIO(data), dtype=object)
    except Exception as exc:
        raise ValueError(f"开售价文件无法读取：{exc}") from exc

    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [column for column in REQUIRED_LAUNCH_PRICE_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError("开售价文件缺少列：" + "、".join(missing))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, source in frame.iterrows():
        values = [source.get(column) for column in REQUIRED_LAUNCH_PRICE_COLUMNS]
        if all(value is None or pd.isna(value) or (isinstance(value, str) and not value.strip()) for value in values):
            continue
        sku = _normalize_text(source.get("SKU"))
        if not sku:
            raise ValueError(f"开售价文件第{int(index) + 2}行 SKU 不能为空")
        if sku in seen:
            raise ValueError(f"开售价文件 SKU 重复：{sku}")
        seen.add(sku)
        prices = {
            db_column: _parse_launch_price_cell(
                source.get(source_column),
                context=f"开售价文件第{int(index) + 2}行 {source_column}",
            )
            for source_column, db_column in LAUNCH_PRICE_DB_COLUMNS.items()
        }
        rows.append({"sku": sku, **prices})
    return rows


def import_launch_price_file(path: Path) -> dict[str, Any]:
    """Persist a price-only historical workbook without creating fake batches."""

    initialize_database()
    data = path.read_bytes()
    digest = _file_hash(data)
    with connect() as conn:
        existing = conn.execute(
            """SELECT stats_json FROM batch_monitor_imports
            WHERE file_hash = ? AND import_type = 'launch_prices'""",
            (digest,),
        ).fetchone()
        if existing:
            return json.loads(str(existing["stats_json"]))

    rows = _parse_launch_price_workbook(data)
    timestamp = _now_iso()
    inserted = 0
    updated = 0
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for row in rows:
            current = conn.execute(
                "SELECT 1 FROM sku_launch_prices WHERE sku = ?",
                (row["sku"],),
            ).fetchone()
            conn.execute(
                """INSERT INTO sku_launch_prices
                (sku, de_price, fr_price, es_price, it_price, source_file_hash, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sku) DO UPDATE SET
                    de_price = excluded.de_price,
                    fr_price = excluded.fr_price,
                    es_price = excluded.es_price,
                    it_price = excluded.it_price,
                    source_file_hash = excluded.source_file_hash,
                    updated_at = excluded.updated_at""",
                (
                    row["sku"],
                    row["de_price"],
                    row["fr_price"],
                    row["es_price"],
                    row["it_price"],
                    digest,
                    timestamp,
                ),
            )
            if current:
                updated += 1
            else:
                inserted += 1
        stats = {
            "rows": len(rows),
            "inserted": inserted,
            "updated": updated,
        }
        _write_import_record(
            conn,
            digest=digest,
            import_type="launch_prices",
            file_name=path.name,
            stats=stats,
        )
        if rows:
            _touch_revision(conn)
    _archive_file("launch-prices", path.name, data, digest)
    return stats


def _parse_history_workbook(data: bytes) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    try:
        sheets = pd.read_excel(
            io.BytesIO(data),
            sheet_name=["货件", "美工图和开售价"],
            dtype=object,
        )
    except Exception as exc:
        raise ValueError(f"历史批次工作簿无法读取：{exc}") from exc
    if set(sheets) != {"货件", "美工图和开售价"}:
        raise ValueError("历史批次工作簿必须包含“货件”和“美工图和开售价”sheet")

    shipment_frame = sheets["货件"].copy()
    shipment_frame.columns = [str(column).strip() for column in shipment_frame.columns]
    missing_shipments = [
        column for column in ("货件单号", "MSKU", "ASIN", "到货时间")
        if column not in shipment_frame.columns
    ]
    if missing_shipments:
        raise ValueError("历史货件sheet缺少列：" + "、".join(missing_shipments))
    shipments: list[dict[str, Any]] = []
    seen_shipments: dict[str, dict[str, Any]] = {}
    for index, source in shipment_frame.iterrows():
        sku = _normalize_text(source.get("MSKU"))
        if not sku:
            continue
        candidate = {
            "sku": sku,
            "shipment_no": _normalize_text(source.get("货件单号")),
            "asin": _normalize_text(source.get("ASIN")),
            "arrival_date": _parse_date_cell(
                source.get("到货时间"),
                context=f"货件sheet第{int(index) + 2}行到货时间",
            ),
        }
        if not candidate["shipment_no"] or not ASIN_PATTERN.fullmatch(candidate["asin"]):
            raise ValueError(f"货件sheet第{int(index) + 2}行货件号或ASIN无效")
        previous = seen_shipments.get(sku)
        if previous and previous != candidate:
            raise ValueError(f"历史货件SKU重复且内容冲突：{sku}")
        if not previous:
            seen_shipments[sku] = candidate
            shipments.append(candidate)

    batch_frame = sheets["美工图和开售价"].copy()
    batch_frame.columns = [str(column).strip() for column in batch_frame.columns]
    required = (
        "SKU",
        "所属批次",
        "美工图时间",
        "DE开售价格",
        "FR开售价格",
        "ES开售价格",
        "IT开售价格",
    )
    missing_batches = [column for column in required if column not in batch_frame.columns]
    if missing_batches:
        raise ValueError("历史批次sheet缺少列：" + "、".join(missing_batches))
    batch_rows: list[dict[str, Any]] = []
    seen_batch_skus: set[str] = set()
    for index, source in batch_frame.iterrows():
        sku = _normalize_text(source.get("SKU"))
        if not sku:
            continue
        if sku in seen_batch_skus:
            raise ValueError(f"历史批次SKU重复：{sku}")
        seen_batch_skus.add(sku)
        batch_no = _validate_batch_no(str(source.get("所属批次") or ""))
        prices = {}
        for code, column in (
            ("de_price", "DE开售价格"),
            ("fr_price", "FR开售价格"),
            ("es_price", "ES开售价格"),
            ("it_price", "IT开售价格"),
        ):
            parsed = pd.to_numeric(pd.Series([source.get(column)]), errors="coerce").iloc[0]
            # Historical workbooks use zero as "price not maintained". Keep it
            # empty in the database instead of inventing a selling price.
            prices[code] = (
                float(parsed)
                if not pd.isna(parsed) and float(parsed) > 0
                else None
            )
        batch_rows.append(
            {
                "sku": sku,
                "batch_no": batch_no,
                "artwork_date": _parse_date_cell(
                    source.get("美工图时间"),
                    context=f"历史批次sheet第{int(index) + 2}行美工图时间",
                ),
                **prices,
            }
        )
    return shipments, batch_rows


def import_history_file(path: Path) -> dict[str, Any]:
    initialize_database()
    data = path.read_bytes()
    digest = _file_hash(data)
    with connect() as conn:
        existing = conn.execute(
            """SELECT stats_json FROM batch_monitor_imports
            WHERE file_hash = ? AND import_type = 'history'""",
            (digest,),
        ).fetchone()
        if existing:
            return json.loads(str(existing["stats_json"]))

    shipments, batch_rows = _parse_history_workbook(data)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in batch_rows:
        grouped.setdefault(row["batch_no"], []).append(row)
    completed_dates: dict[str, str | None] = {}
    for batch_no, rows in grouped.items():
        dates = [row["artwork_date"] for row in rows]
        completed_dates[batch_no] = max(dates) if dates and all(dates) else None
    timestamp = _now_iso()
    shipment_map = {row["sku"]: row for row in shipments}
    batch_skus = {row["sku"] for row in batch_rows}
    batch_shipped = sum(1 for sku in batch_skus if sku in shipment_map)
    batch_arrived = sum(
        1
        for sku in batch_skus
        if sku in shipment_map and shipment_map[sku]["arrival_date"]
    )
    stats = {
        "batches": len(grouped),
        "batch_skus": len(batch_rows),
        "shipments": len(shipments),
        "arrived_shipments": sum(1 for row in shipments if row["arrival_date"]),
        "pending_shipments": sum(1 for row in shipments if not row["arrival_date"]),
        "batch_shipped": batch_shipped,
        "batch_arrived": batch_arrived,
        "artwork_completed_batches": sum(
            1 for value in completed_dates.values() if value
        ),
        "artwork_pending_batches": sum(
            1 for value in completed_dates.values() if not value
        ),
        "orphan_shipments": sum(1 for row in shipments if row["sku"] not in batch_skus),
        "missing_price_skus": sum(
            1
            for row in batch_rows
            if any(
                row[column] is None
                for column in ("de_price", "fr_price", "es_price", "it_price")
            )
        ),
    }
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        table_counts = [
            conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
            for table in (
                "batch_monitor_batches",
                "batch_monitor_skus",
                "sku_first_shipments",
            )
        ]
        if any(int(value) for value in table_counts):
            raise ValueError("批次监控数据库已有数据，历史迁移已停止以避免覆盖")
        conn.executemany(
            """INSERT INTO batch_monitor_batches
            (batch_no, artwork_completed_date, source_file_name, source_file_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    batch_no,
                    completed_dates[batch_no],
                    path.name,
                    digest,
                    timestamp,
                    timestamp,
                )
                for batch_no in sorted(grouped)
            ],
        )
        conn.executemany(
            """INSERT INTO batch_monitor_skus
            (sku, batch_no, de_price, fr_price, es_price, it_price,
             developer_snapshot, monitor_basis, created_at)
            VALUES (?, ?, ?, ?, ?, ?, '', 'historical_confirmed', ?)""",
            [
                (
                    row["sku"],
                    row["batch_no"],
                    row["de_price"],
                    row["fr_price"],
                    row["es_price"],
                    row["it_price"],
                    timestamp,
                )
                for row in batch_rows
            ],
        )
        conn.executemany(
            """INSERT INTO sku_first_shipments
            (sku, shipment_no, asin, arrival_date, updated_at)
            VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    row["sku"],
                    row["shipment_no"],
                    row["asin"],
                    row["arrival_date"],
                    timestamp,
                )
                for row in shipments
            ],
        )
        _write_import_record(
            conn,
            digest=digest,
            import_type="history",
            file_name=path.name,
            stats=stats,
        )
        _touch_revision(conn)
    _archive_file("history", path.name, data, digest)
    return stats


def _batch_period_key(batch_no: str) -> tuple[int, int, str]:
    match = re.search(r"(\d{6})$", batch_no)
    if not match:
        return (0, 0, batch_no)
    digits = match.group(1)
    return (int(digits[:4]), int(digits[4:]), batch_no)


def _all_batch_rows(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT
            b.batch_no,
            b.artwork_completed_date,
            b.source_file_name,
            b.created_at,
            b.updated_at,
            COUNT(s.sku) AS sku_count,
            SUM(CASE WHEN f.sku IS NOT NULL THEN 1 ELSE 0 END) AS shipped_count,
            SUM(CASE WHEN f.arrival_date IS NOT NULL THEN 1 ELSE 0 END) AS arrived_count,
            COUNT(DISTINCT f.shipment_no) AS shipment_count
        FROM batch_monitor_batches b
        JOIN batch_monitor_skus s ON s.batch_no = b.batch_no
        LEFT JOIN sku_first_shipments f ON f.sku = s.sku
        GROUP BY b.batch_no
        ORDER BY b.batch_no"""
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["sku_count"] = int(item["sku_count"] or 0)
        item["shipped_count"] = int(item["shipped_count"] or 0)
        item["arrived_count"] = int(item["arrived_count"] or 0)
        item["shipment_count"] = int(item["shipment_count"] or 0)
        item["is_complete"] = bool(
            item["artwork_completed_date"]
            and item["shipped_count"] == item["sku_count"]
            and item["arrived_count"] == item["sku_count"]
        )
        result.append(item)
    return result


def _matching_batch_numbers(conn, search: str) -> set[str]:
    term = search.strip().upper()
    if not term:
        return set()
    like = f"%{term}%"
    rows = conn.execute(
        """SELECT DISTINCT s.batch_no
        FROM batch_monitor_skus s
        LEFT JOIN sku_first_shipments f ON f.sku = s.sku
        WHERE UPPER(s.batch_no) LIKE ?
           OR UPPER(s.sku) LIKE ?
           OR UPPER(COALESCE(f.asin, '')) LIKE ?
           OR UPPER(COALESCE(f.shipment_no, '')) LIKE ?""",
        (like, like, like, like),
    ).fetchall()
    return {str(row["batch_no"]) for row in rows}


@router.get("/batches")
def list_batches(
    view: str = Query("incomplete", pattern="^(incomplete|all|completed)$"),
    search: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    with connect() as conn:
        all_rows = _all_batch_rows(conn)
        matching = _matching_batch_numbers(conn, search) if search.strip() else None
        orphan_skus = {
            str(row["sku"])
            for row in conn.execute(
                """SELECT f.sku FROM sku_first_shipments f
                LEFT JOIN batch_monitor_skus s ON s.sku = f.sku
                WHERE s.sku IS NULL"""
            ).fetchall()
        }
    try:
        _, eligible_developers = _operational_developer_maps()
        orphan_count = sum(1 for sku in orphan_skus if sku in eligible_developers)
        orphan_scope_available = True
        orphan_scope_message = ""
    except ValueError as exc:
        orphan_count = 0
        orphan_scope_available = False
        orphan_scope_message = str(exc)
    metrics = {
        "incomplete_batches": sum(1 for row in all_rows if not row["is_complete"]),
        "pending_artwork_batches": sum(
            1 for row in all_rows if not row["artwork_completed_date"]
        ),
        "pending_shipment_skus": sum(
            row["sku_count"] - row["shipped_count"] for row in all_rows
        ),
        "pending_arrival_skus": sum(
            row["shipped_count"] - row["arrived_count"] for row in all_rows
        ),
    }
    visible = [
        row
        for row in all_rows
        if (
            view == "all"
            or (view == "completed" and row["is_complete"])
            or (view == "incomplete" and not row["is_complete"])
        )
        and (matching is None or row["batch_no"] in matching)
    ]
    visible.sort(key=lambda row: _batch_period_key(str(row["batch_no"])), reverse=True)
    total = len(visible)
    start = (page - 1) * page_size
    return {
        "metrics": metrics,
        "rows": visible[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "view": view,
        "orphan_count": orphan_count,
        "orphan_scope_available": orphan_scope_available,
        "orphan_scope_message": orphan_scope_message,
        "updated_at": batch_monitor_revision(),
    }


def _batch_detail(conn, batch_no: str) -> dict[str, Any]:
    normalized = _validate_batch_no(batch_no)
    summary = next(
        (row for row in _all_batch_rows(conn) if row["batch_no"] == normalized),
        None,
    )
    if not summary:
        raise HTTPException(404, "批次不存在")
    sku_rows = [
        dict(row)
        for row in conn.execute(
            """SELECT
                s.sku,
                s.de_price,
                s.fr_price,
                s.es_price,
                s.it_price,
                f.asin,
                f.shipment_no,
                f.arrival_date
            FROM batch_monitor_skus s
            LEFT JOIN sku_first_shipments f ON f.sku = s.sku
            WHERE s.batch_no = ?
            ORDER BY s.sku""",
            (normalized,),
        ).fetchall()
    ]
    return {"batch": summary, "skus": sku_rows}


@router.get("/batches/{batch_no}")
def batch_details(batch_no: str):
    with connect() as conn:
        return _batch_detail(conn, batch_no)


@router.get("/orphans")
def orphan_shipments(
    search: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    try:
        _, eligible_developers = _operational_developer_maps()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    term = search.strip().upper()
    with connect() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """SELECT f.sku, f.asin, f.shipment_no, f.arrival_date
                FROM sku_first_shipments f
                LEFT JOIN batch_monitor_skus s ON s.sku = f.sku
                WHERE s.sku IS NULL
                ORDER BY f.sku"""
            ).fetchall()
        ]
    filtered = [
        row
        for row in rows
        if row["sku"] in eligible_developers
        and (
            not term
            or term in str(row["sku"]).upper()
            or term in str(row["asin"]).upper()
            or term in str(row["shipment_no"]).upper()
        )
    ]
    total = len(filtered)
    start = (page - 1) * page_size
    return {
        "rows": filtered[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/copy-lists")
def batch_monitor_copy_lists():
    """Return compact newline-friendly decision lists without loading batch pages."""
    with connect() as conn:
        unbound_shipment_skus = [
            str(row["sku"])
            for row in conn.execute(
                """SELECT s.sku
                FROM batch_monitor_skus s
                LEFT JOIN sku_first_shipments f ON f.sku = s.sku
                WHERE f.sku IS NULL
                ORDER BY s.sku"""
            ).fetchall()
        ]
        pending_shipment_nos = [
            str(row["shipment_no"])
            for row in conn.execute(
                """SELECT DISTINCT f.shipment_no
                FROM batch_monitor_skus s
                JOIN sku_first_shipments f ON f.sku = s.sku
                WHERE f.arrival_date IS NULL
                  AND TRIM(f.shipment_no) <> ''
                ORDER BY f.shipment_no"""
            ).fetchall()
        ]

    return {
        "unbound_shipment_skus": unbound_shipment_skus,
        "pending_shipment_nos": pending_shipment_nos,
        "unbound_shipment_count": len(unbound_shipment_skus),
        "pending_shipment_count": len(pending_shipment_nos),
        "updated_at": batch_monitor_revision(),
    }


@router.post("/batches")
async def create_batch(
    batch_no: Annotated[str, Form(...)],
    file: Annotated[UploadFile, File(...)],
):
    name, data = await read_upload_limited(
        file,
        fallback_name="batch.xlsx",
        max_bytes=MAX_BATCH_FILE_BYTES,
        allowed={".xlsx"},
    )
    try:
        return create_batch_from_upload(batch_no, name, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/shipments")
async def upload_shipments(file: Annotated[UploadFile, File(...)]):
    name, data = await read_upload_limited(
        file,
        fallback_name="shipments.csv",
        max_bytes=MAX_BATCH_FILE_BYTES,
        allowed={".csv"},
    )
    try:
        return import_shipment_upload(name, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.put("/batches/{batch_no}/artwork")
def update_artwork(batch_no: str, payload: ArtworkUpdate):
    normalized = _validate_batch_no(batch_no)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT artwork_completed_date FROM batch_monitor_batches
            WHERE batch_no = ?""",
            (normalized,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "批次不存在")
        current = row["artwork_completed_date"]
        completed_date = (current or _today_iso()) if payload.completed else None
        conn.execute(
            """UPDATE batch_monitor_batches
            SET artwork_completed_date = ?, updated_at = ?
            WHERE batch_no = ?""",
            (completed_date, _now_iso(), normalized),
        )
        _touch_revision(conn)
    return {
        "batch_no": normalized,
        "completed": bool(completed_date),
        "artwork_completed_date": completed_date,
    }


@router.put("/shipments/{shipment_no}/arrival")
def update_shipment_arrival(shipment_no: str, payload: ShipmentArrivalUpdate):
    normalized = _normalize_text(shipment_no)
    if not normalized:
        raise HTTPException(422, "货件单号不能为空")
    if payload.arrival_date > _now().date():
        raise HTTPException(422, "到货日期不能晚于今天")
    arrival_date = payload.arrival_date.isoformat()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        total = int(
            conn.execute(
                """SELECT COUNT(*) AS count FROM sku_first_shipments
                WHERE shipment_no = ?""",
                (normalized,),
            ).fetchone()["count"]
        )
        if not total:
            raise HTTPException(404, "货件不存在")
        pending_rows = conn.execute(
            """SELECT f.sku, s.batch_no
            FROM sku_first_shipments f
            LEFT JOIN batch_monitor_skus s ON s.sku = f.sku
            WHERE f.shipment_no = ? AND f.arrival_date IS NULL""",
            (normalized,),
        ).fetchall()
        affected_counts: dict[str, int] = {}
        for row in pending_rows:
            if row["batch_no"]:
                batch_no = str(row["batch_no"])
                affected_counts[batch_no] = affected_counts.get(batch_no, 0) + 1
        cursor = conn.execute(
            """UPDATE sku_first_shipments
            SET arrival_date = ?, updated_at = ?
            WHERE shipment_no = ? AND arrival_date IS NULL""",
            (arrival_date, _now_iso(), normalized),
        )
        updated = int(cursor.rowcount)
        if updated:
            _touch_revision(conn)
        affected_summaries = {
            row["batch_no"]: row
            for row in _all_batch_rows(conn)
            if row["batch_no"] in affected_counts
        }
    return {
        "shipment_no": normalized,
        "arrival_date": arrival_date,
        "updated": updated,
        "total": total,
        "already_arrived": total - updated,
        "affected_batches": [
            {
                "batch_no": batch_no,
                "updated_skus": count,
                "arrived_count": affected_summaries[batch_no]["arrived_count"],
                "sku_count": affected_summaries[batch_no]["sku_count"],
                "is_complete": affected_summaries[batch_no]["is_complete"],
            }
            for batch_no, count in sorted(affected_counts.items())
        ],
    }


@router.put("/skus/{sku}/arrival")
def update_sku_arrival(sku: str, payload: ArrivalUpdate):
    normalized = _normalize_text(sku)
    if not normalized:
        raise HTTPException(422, "SKU不能为空")
    arrival_date = (
        (payload.arrival_date.isoformat() if payload.arrival_date else _today_iso())
        if payload.arrived
        else None
    )
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT arrival_date FROM sku_first_shipments WHERE sku = ?",
            (normalized,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "SKU尚未绑定首次货件")
        conn.execute(
            """UPDATE sku_first_shipments
            SET arrival_date = ?, updated_at = ?
            WHERE sku = ?""",
            (arrival_date, _now_iso(), normalized),
        )
        _touch_revision(conn)
    return {
        "sku": normalized,
        "arrived": bool(arrival_date),
        "arrival_date": arrival_date,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="批次监控历史数据迁移")
    parser.add_argument("command", choices=["import-history", "import-launch-prices"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "import-history":
        print(json.dumps(import_history_file(args.path), ensure_ascii=False, indent=2))
    elif args.command == "import-launch-prices":
        print(json.dumps(import_launch_price_file(args.path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
