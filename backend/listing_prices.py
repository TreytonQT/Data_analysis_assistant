"""Daily Listing price snapshots and derived observations."""
from __future__ import annotations
import hashlib, io, json, os, re, tempfile, unicodedata
from datetime import date, datetime, timedelta
from functools import lru_cache
from threading import RLock
from pathlib import Path
from typing import Any
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from app_paths import DATA_DIR
import backend.db as db
from backend.db import DB_PATH, connect
from dashboard.parquet_cache import revision_digest
from dashboard.derived_table_cache import load_or_build_frame_bundle

router = APIRouter(prefix="/api/pricing", tags=["listing-prices"])
LISTING_REQUIRED = ["MSKU", "ASIN", "国家", "币种", "售价(总价)", "运费", "积分", "价格", "优惠价"]
LISTING_NUMERIC = ["售价(总价)", "运费", "积分", "价格", "优惠价"]
COUNTRY_MAP = {"DE": "DE", "德国": "DE", "FR": "FR", "法国": "FR", "ES": "ES", "西班牙": "ES", "IT": "IT", "意大利": "IT"}
DATE_PATTERN = re.compile(r"Listing(?P<date>20\d{6})", re.IGNORECASE)
INDEX_COLUMNS = ["日期","原始文件名","保存文件名","标准化文件名","文件哈希","上传时间","行数","有效售价数","促销数","无可售价数","异常数","异常摘要"]
NORMALIZED_COLUMNS = ["日期","MSKU","ASIN","国家","币种","MSKU原值","ASIN原值","国家原值","售价(总价)","运费","积分","价格","优惠价","当前实际总价","Listing原价","Listing优惠价","可售","促销中","异常类型"]
LISTING_EVENT_COLUMNS = ["date", "previous_date", "gap_days", "observed_as", "sku", "asin", "country", "type", "old_base_price", "new_base_price", "old_effective_price", "new_effective_price", "old_promo", "new_promo", "anomaly"]
LISTING_EVENT_CODE_VERSION = "2"

def listing_root(data_dir: Path = DATA_DIR) -> Path:
    path = data_dir / "listing_prices"; path.mkdir(parents=True, exist_ok=True); return path

def listing_index_path(data_dir: Path = DATA_DIR) -> Path:
    return listing_root(data_dir) / "index.csv"

def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists(): temp.unlink()

def _atomic_frame(path: Path, frame: pd.DataFrame) -> None:
    _atomic_bytes(path, frame.to_csv(index=False).encode("utf-8-sig"))

def _normal_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip().upper()


def _display_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return ""
    return str(value).strip()

def listing_date_from_name(name: str) -> str:
    match = DATE_PATTERN.search(Path(name).name)
    if not match: raise ValueError("Listing 文件名必须包含 ListingYYYYMMDD 日期，例如 Listing20260916.xlsx")
    try: return datetime.strptime(match.group("date"), "%Y%m%d").date().isoformat()
    except ValueError as exc: raise ValueError("Listing 文件名中的日期不合法") from exc

def _matching_sheet(data: bytes) -> tuple[str, pd.DataFrame]:
    try: excel = pd.ExcelFile(io.BytesIO(data))
    except Exception as exc: raise ValueError(f"Listing 工作簿无法读取：{exc}") from exc
    matches = []
    for sheet in excel.sheet_names:
        try: frame = pd.read_excel(excel, sheet_name=sheet, dtype=object)
        except Exception: continue
        frame.columns = [str(column).strip() for column in frame.columns]
        if set(LISTING_REQUIRED).issubset(frame.columns): matches.append((str(sheet), frame))
    if len(matches) != 1: raise ValueError("Listing 工作簿必须恰好有一个包含完整字段的工作表")
    return matches[0]

def normalize_listing_workbook(data: bytes, listing_date: str | None = None) -> tuple[str, pd.DataFrame, dict[str, Any]]:
    sheet, frame = _matching_sheet(data)
    frame = frame[LISTING_REQUIRED].copy()
    frame["MSKU原值"] = frame["MSKU"].map(lambda value: _display_text(value))
    frame["ASIN原值"] = frame["ASIN"].map(lambda value: _display_text(value))
    frame["国家原值"] = frame["国家"].map(lambda value: _display_text(value))
    frame["MSKU"] = frame["MSKU"].map(_normal_text); frame["ASIN"] = frame["ASIN"].map(_normal_text)
    frame["国家"] = frame["国家"].map(lambda value: COUNTRY_MAP.get(_normal_text(value), _normal_text(value)))
    frame["币种"] = frame["币种"].map(_normal_text)
    if frame[["MSKU","ASIN","国家"]].eq("").any(axis=None): raise ValueError("Listing 的 MSKU、ASIN、国家不能为空")
    unknown = sorted(set(frame["国家"]) - set(COUNTRY_MAP.values()))
    if unknown: raise ValueError("Listing 国家必须是 DE/FR/ES/IT：" + "、".join(unknown[:10]))
    for column in LISTING_NUMERIC:
        raw = frame[column]; converted = pd.to_numeric(raw, errors="coerce")
        invalid = raw.notna() & raw.astype(str).str.strip().ne("") & converted.isna()
        if invalid.any(): raise ValueError(f"Listing 第 {int(invalid.to_numpy().nonzero()[0][0]) + 2} 行{column}不是有效数值")
        frame[column] = converted.astype(float)
        if (frame[column].dropna() < 0).any(): raise ValueError(f"Listing {column}不能为负数")
    if frame.duplicated(["MSKU","ASIN","国家"], keep=False).any(): raise ValueError("Listing 存在重复的 MSKU+ASIN+国家")
    total = frame["售价(总价)"]; freight = frame["运费"].fillna(0); promo = frame["优惠价"]; base = frame["价格"]
    mismatch = total.notna() & (total - promo.fillna(0) - freight).abs().gt(0.01)
    anomalies = pd.Series("", index=frame.index, dtype="string"); anomalies.loc[mismatch] = "总价与优惠价加运费不一致"
    high_promo = promo.notna() & base.notna() & promo.gt(base); anomalies.loc[high_promo & anomalies.eq("")] = "优惠价高于原价"
    zero_base_sale = base.fillna(0).le(0) & total.fillna(0).gt(0); anomalies.loc[zero_base_sale & anomalies.eq("")] = "原价为0但存在售价"
    frame["当前实际总价"] = total.where(total.gt(0)); frame["Listing原价"] = base.where(base.gt(0)); frame["Listing优惠价"] = promo.where(promo.gt(0))
    frame["可售"] = frame["当前实际总价"].notna(); frame["促销中"] = frame["Listing优惠价"].notna() & frame["Listing原价"].notna() & frame["Listing优惠价"].lt(frame["Listing原价"])
    frame["日期"] = listing_date or date.today().isoformat(); frame["异常类型"] = anomalies.replace("", pd.NA)
    normalized = frame[NORMALIZED_COLUMNS].copy()
    stats = {"sheet": sheet, "rows": len(normalized), "effective_price_count": int(normalized["当前实际总价"].notna().sum()), "promotion_count": int(normalized["促销中"].sum()), "unavailable_count": int(normalized["当前实际总价"].isna().sum()), "anomaly_count": int(normalized["异常类型"].notna().sum()), "anomaly_examples": normalized.loc[normalized["异常类型"].notna(), ["MSKU","ASIN","国家","异常类型"]].head(10).to_dict("records")}
    return sheet, normalized, stats

def load_listing_index(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    path = listing_index_path(data_dir)
    if not path.exists(): return pd.DataFrame(columns=INDEX_COLUMNS)
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    for column in INDEX_COLUMNS:
        if column not in frame.columns: frame[column] = ""
    return frame[INDEX_COLUMNS].sort_values("日期").reset_index(drop=True)

def _paths_for_date(day: str, data_dir: Path = DATA_DIR) -> tuple[Path, Path]:
    root = listing_root(data_dir); return root / f"{day}.xlsx", root / f"{day}.csv"

def persist_listing_snapshot(name: str, data: bytes, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    day = listing_date_from_name(name); digest = hashlib.sha256(data).hexdigest()
    _, normalized, stats = normalize_listing_workbook(data, day)
    index = load_listing_index(data_dir); existing = index[index["日期"].eq(day)]
    if not existing.empty and str(existing.iloc[-1]["文件哈希"]) == digest:
        result = existing.iloc[-1].to_dict(); result.update({"date": day, "idempotent": True, "replaced": False, "warnings": [f"检测到 {result.get("异常数", "0")} 条数据异常"] if int(result.get("异常数", 0) or 0) else []}); return result
    raw_path, csv_path = _paths_for_date(day, data_dir); index_path = listing_index_path(data_dir)
    record = {"日期": day, "原始文件名": name, "保存文件名": raw_path.name, "标准化文件名": csv_path.name, "文件哈希": digest, "上传时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "行数": str(stats["rows"]), "有效售价数": str(stats["effective_price_count"]), "促销数": str(stats["promotion_count"]), "无可售价数": str(stats["unavailable_count"]), "异常数": str(stats["anomaly_count"]), "异常摘要": json.dumps(stats["anomaly_examples"], ensure_ascii=False)}
    next_index = pd.concat([index[~index["日期"].eq(day)], pd.DataFrame([record])], ignore_index=True)[INDEX_COLUMNS].sort_values("日期").reset_index(drop=True)
    previous = {path: path.read_bytes() if path.exists() else None for path in (raw_path, csv_path, index_path)}
    try:
        _atomic_bytes(raw_path, data); _atomic_frame(csv_path, normalized); _atomic_frame(index_path, next_index)
    except Exception:
        for path, old in previous.items():
            if old is None:
                if path.exists(): path.unlink()
            else: _atomic_bytes(path, old)
        raise
    cutoff = pd.Timestamp(next_index["日期"].max()).date() - timedelta(days=30); retained = []; cleanup_warning = None
    for _, row in next_index.iterrows():
        if pd.Timestamp(row["日期"]).date() >= cutoff: retained.append(row.to_dict()); continue
        old_raw, old_csv = _paths_for_date(str(row["日期"]), data_dir)
        try:
            for path in (old_raw, old_csv):
                if path.exists(): path.unlink()
        except OSError as exc:
            cleanup_warning = f"过期快照清理失败：{exc}"; retained.append(row.to_dict())
    _atomic_frame(index_path, pd.DataFrame(retained, columns=INDEX_COLUMNS))
    warning_text = [f"检测到 {stats["anomaly_count"]} 条数据异常" if stats["anomaly_count"] else ""]
    result = record | {"date": day, "idempotent": False, "replaced": not existing.empty, "warnings": [item for item in warning_text if item]}
    if cleanup_warning: result["cleanup_warning"] = cleanup_warning
    return result

def load_snapshot(day: str, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    _, path = _paths_for_date(day, data_dir)
    if not path.exists(): return pd.DataFrame(columns=NORMALIZED_COLUMNS)
    frame = pd.read_csv(path, encoding="utf-8-sig")
    for column in NORMALIZED_COLUMNS:
        if column not in frame.columns: frame[column] = pd.NA
    return frame[NORMALIZED_COLUMNS]


def listing_history(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Load the retained Listing snapshots in chronological order."""
    index = load_listing_index(data_dir)
    if index.empty:
        return pd.DataFrame(columns=NORMALIZED_COLUMNS)
    frames = [load_snapshot(str(day), data_dir) for day in index["日期"].tolist()]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=NORMALIZED_COLUMNS)
    history = pd.concat(frames, ignore_index=True, sort=False)
    for column in NORMALIZED_COLUMNS:
        if column not in history.columns:
            history[column] = pd.NA
    return history[NORMALIZED_COLUMNS].sort_values(
        ["日期", "MSKU", "ASIN", "国家"],
        kind="stable",
    ).reset_index(drop=True)

def _sqlite_file_signature() -> tuple[tuple[str, int, int], ...]:
    result = []
    db_path = db.DB_PATH
    for path in (db_path, db_path.with_name(db_path.name + "-wal")):
        try:
            stat = path.stat()
            result.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
        except OSError:
            result.append((str(path.resolve()), -1, -1))
    return tuple(result)


def _launch_prices() -> pd.DataFrame:
    columns = ["MSKU","DE","FR","ES","IT"]
    try:
        with connect() as conn:
            rows = conn.execute("""SELECT keys.sku AS MSKU, COALESCE(batch.de_price, legacy.de_price) AS DE, COALESCE(batch.fr_price, legacy.fr_price) AS FR, COALESCE(batch.es_price, legacy.es_price) AS ES, COALESCE(batch.it_price, legacy.it_price) AS IT FROM (SELECT sku FROM batch_monitor_skus UNION SELECT sku FROM sku_launch_prices) keys LEFT JOIN batch_monitor_skus batch ON batch.sku = keys.sku LEFT JOIN sku_launch_prices legacy ON legacy.sku = keys.sku""").fetchall()
        result = pd.DataFrame([dict(row) for row in rows]) if rows else pd.DataFrame(columns=columns)
    except Exception: result = pd.DataFrame(columns=columns)
    for column in columns:
        if column not in result: result[column] = pd.NA
    result["MSKU"] = result["MSKU"].map(_normal_text); return result[columns]

@lru_cache(maxsize=4)
def _cached_launch_price_lookup(signature: tuple[tuple[str, int, int], ...]) -> dict[str, dict[str, Any]]:
    del signature
    frame = _launch_prices()
    return frame.set_index("MSKU").to_dict("index") if not frame.empty else {}


def _launch_price_lookup() -> dict[str, dict[str, Any]]:
    return _cached_launch_price_lookup(_sqlite_file_signature())


def latest_listing_wide(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    index = load_listing_index(data_dir)
    if index.empty: return pd.DataFrame(columns=["MSKU","ASIN"])
    frame = load_snapshot(str(index.iloc[-1]["日期"]), data_dir)
    if frame.empty: return frame
    return _listing_wide_from_snapshot(frame, _launch_prices())


def _listing_wide_from_snapshot(frame: pd.DataFrame, launch: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["MSKU", "ASIN"])
    price = frame.pivot_table(index=["MSKU","ASIN"], columns="国家", values=["当前实际总价","Listing原价","Listing优惠价"], aggfunc="first")
    price.columns = [f"{country}_{kind}" for kind, country in price.columns]; price = price.reset_index()
    launch_map = launch.set_index("MSKU").to_dict("index") if not launch.empty else {}
    for code in ("DE","FR","ES","IT"):
        price[f"{code}_开售价"] = price["MSKU"].map(lambda sku: launch_map.get(sku, {}).get(code))
        price[f"{code}_较开售价变化"] = price.apply(lambda row: (float(row.get(f"{code}_当前实际总价")) / float(row.get(f"{code}_开售价")) - 1) if pd.notna(row.get(f"{code}_当前实际总价")) and pd.notna(row.get(f"{code}_开售价")) and float(row.get(f"{code}_开售价")) > 0 else pd.NA, axis=1)
    return price

def _promo_flags(values: pd.Series) -> pd.Series:
    return values.fillna(False).astype(str).str.strip().str.lower().isin({"true", "1", "yes", "是"})


def _events_between(previous: pd.DataFrame, current: pd.DataFrame, previous_day: str, current_day: str) -> pd.DataFrame:
    keys = ["MSKU", "ASIN", "国家"]
    fields = ["当前实际总价", "Listing原价", "促销中", "异常类型"]
    before = previous[[*keys, *fields]].rename(columns={column: f"{column}_old" for column in fields})
    after = current[[*keys, *fields]].rename(columns={column: f"{column}_new" for column in fields})
    merged = before.merge(after, on=keys, how="outer", sort=False, indicator=True)
    old_effective = pd.to_numeric(merged["当前实际总价_old"], errors="coerce")
    new_effective = pd.to_numeric(merged["当前实际总价_new"], errors="coerce")
    old_base = pd.to_numeric(merged["Listing原价_old"], errors="coerce")
    new_base = pd.to_numeric(merged["Listing原价_new"], errors="coerce")
    old_promo = _promo_flags(merged["促销中_old"])
    new_promo = _promo_flags(merged["促销中_new"])
    masks = [
        ("恢复可售", old_effective.isna() & new_effective.notna()),
        ("失去可售", old_effective.notna() & new_effective.isna()),
        ("Listing原价涨跌", old_base.notna() & new_base.notna() & (new_base - old_base).abs().gt(0.01)),
        ("实际总价涨跌", old_effective.notna() & new_effective.notna() & (new_effective - old_effective).abs().gt(0.01)),
        ("促销开始", ~old_promo & new_promo),
        ("促销结束", old_promo & ~new_promo),
    ]
    gap = (pd.Timestamp(current_day).date() - pd.Timestamp(previous_day).date()).days
    events: list[dict[str, Any]] = []
    for kind, mask in masks:
        if not mask.any():
            continue
        selected = merged.loc[mask, [*keys, "当前实际总价_old", "当前实际总价_new", "Listing原价_old", "Listing原价_new", "促销中_old", "促销中_new", "异常类型_new"]]
        for sku, asin, country, old_eff, new_eff, old_price, new_price, old_flag, new_flag, anomaly in selected.itertuples(index=False, name=None):
            events.append(
                {
                    "date": current_day,
                    "previous_date": previous_day,
                    "gap_days": gap,
                    "observed_as": "首次观察到" if gap > 1 else current_day,
                    "sku": sku,
                    "asin": asin,
                    "country": country,
                    "type": kind,
                    "old_base_price": float(old_price) if pd.notna(old_price) else None,
                    "new_base_price": float(new_price) if pd.notna(new_price) else None,
                    "old_effective_price": float(old_eff) if pd.notna(old_eff) else None,
                    "new_effective_price": float(new_eff) if pd.notna(new_eff) else None,
                    "old_promo": bool(_promo_flags(pd.Series([old_flag])).iloc[0]),
                    "new_promo": bool(_promo_flags(pd.Series([new_flag])).iloc[0]),
                    "anomaly": str(anomaly) if pd.notna(anomaly) else None,
                }
            )
    return pd.DataFrame(events, columns=LISTING_EVENT_COLUMNS)


def _sort_listing_events(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=LISTING_EVENT_COLUMNS)
    return events.sort_values(["date", "sku", "country"], ascending=[False, False, False], kind="stable").reset_index(drop=True)


def _snapshot_events_from_frames(index: pd.DataFrame, frames: dict[str, pd.DataFrame], data_dir: Path) -> pd.DataFrame:
    if len(index) < 2:
        return pd.DataFrame(columns=LISTING_EVENT_COLUMNS)
    pair_frames: list[pd.DataFrame] = []
    days = index["日期"].astype(str).tolist()
    for previous_day, current_day in zip(days, days[1:]):
        _, previous_path = _paths_for_date(previous_day, data_dir)
        _, current_path = _paths_for_date(current_day, data_dir)
        pair_paths = [path for path in (previous_path, current_path) if path.is_file()]
        pair_revision = revision_digest(
            f"listing-event-pair-v{LISTING_EVENT_CODE_VERSION}:{previous_day}:{current_day}",
            pair_paths,
        ) + f":missing-{int(not previous_path.is_file())}-{int(not current_path.is_file())}"

        def build_pair(previous_day=previous_day, current_day=current_day):
            return (
                {"events": _events_between(frames[previous_day], frames[current_day], previous_day, current_day)},
                {},
            )

        pair, _ = load_or_build_frame_bundle("listing-event-pair", pair_revision, build_pair)
        pair_frames.append(pair["events"])
    if not pair_frames:
        return pd.DataFrame(columns=LISTING_EVENT_COLUMNS)
    return _sort_listing_events(pd.concat(pair_frames, ignore_index=True, sort=False))


def _listing_event_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    # A freshly built numeric event column can contain NaN where a previous
    # snapshot had no price. JSON nulls must be identical on cache misses and
    # after Parquet reloads, including raw recent_event payloads.
    return json.loads(frame.to_json(orient="records", force_ascii=False, double_precision=15))


def _snapshot_events(data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    index = load_listing_index(data_dir)
    days = index["日期"].astype(str).tolist()
    frames = {day: load_snapshot(day, data_dir) for day in days}
    return _listing_event_records(_snapshot_events_from_frames(index, frames, data_dir))

def listing_source_revision(data_dir: Path = DATA_DIR) -> str:
    root = listing_root(data_dir)
    paths = [listing_index_path(data_dir), *root.glob("*.csv"), *root.glob("*.xlsx")]
    digest = hashlib.sha256(b"listing-source-stat-v3")
    found = False
    for path in sorted({path for path in paths if path.is_file()}, key=str):
        found = True
        try:
            stat = path.stat()
            digest.update(f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8"))
        except OSError:
            digest.update(f"{path}:unavailable".encode("utf-8"))
    return digest.hexdigest() if found else "empty"


def launch_price_revision() -> str:
    digest = hashlib.sha256(str(DB_PATH.resolve()).encode("utf-8"))
    try:
        with connect() as conn:
            for table in ("batch_monitor_skus", "sku_launch_prices"):
                rows = conn.execute(
                    f"SELECT sku, de_price, fr_price, es_price, it_price "
                    f"FROM {table} ORDER BY sku"
                ).fetchall()
                digest.update(table.encode("ascii"))
                digest.update(json.dumps(
                    [tuple(row) for row in rows],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8"))
    except Exception:
        digest.update(b"unavailable")
    return digest.hexdigest()


def listing_revision(data_dir: Path = DATA_DIR) -> str:
    """Return a revision for Listing source files and launch-price values only."""
    digest = hashlib.sha256()
    digest.update(listing_source_revision(data_dir).encode("ascii"))
    digest.update(launch_price_revision().encode("ascii"))
    return digest.hexdigest()


@lru_cache(maxsize=8)
def _cached_listing_source_tables(source_revision: str, data_dir_text: str) -> dict[str, pd.DataFrame]:
    data_dir = Path(data_dir_text)

    def build() -> tuple[dict[str, pd.DataFrame], dict]:
        index = load_listing_index(data_dir)
        days = index["日期"].astype(str).tolist()
        snapshots = {day: load_snapshot(day, data_dir) for day in days}
        frames = [snapshots[day] for day in days if not snapshots[day].empty]
        if frames:
            history = pd.concat(frames, ignore_index=True, sort=False)
            history = history[NORMALIZED_COLUMNS].sort_values(
                ["日期", "MSKU", "ASIN", "国家"], kind="stable"
            ).reset_index(drop=True)
            latest = snapshots[days[-1]].copy()
        else:
            history = pd.DataFrame(columns=NORMALIZED_COLUMNS)
            latest = pd.DataFrame(columns=NORMALIZED_COLUMNS)
        events = _snapshot_events_from_frames(index, snapshots, data_dir)
        return {"history": history, "latest_snapshot": latest, "events": events}, {"days": days}

    frames, _ = load_or_build_frame_bundle("listing-source-tables", source_revision, build)
    return frames


@lru_cache(maxsize=8)
def _cached_listing_bundle_views(
    source_revision: str, prices_revision: str, data_dir_text: str
) -> tuple[pd.DataFrame, pd.DataFrame, tuple[dict[str, Any], ...]]:
    del prices_revision
    tables = _cached_listing_source_tables(source_revision, data_dir_text)
    latest = _listing_wide_from_snapshot(tables["latest_snapshot"], _launch_prices())
    events = tuple(_listing_event_records(tables["events"]))
    return latest, tables["history"], events


_LISTING_CACHE_LOCK = RLock()


def cached_listing_bundle(data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, pd.DataFrame, tuple[dict[str, Any], ...]]:
    """Load source-only history/events separately from launch-price-derived views."""
    data_dir_text = str(data_dir.resolve())
    source_revision = listing_source_revision(data_dir)
    prices_revision = launch_price_revision()
    with _LISTING_CACHE_LOCK:
        return _cached_listing_bundle_views(source_revision, prices_revision, data_dir_text)


def clear_listing_cache() -> None:
    with _LISTING_CACHE_LOCK:
        _cached_listing_source_tables.cache_clear()
        _cached_listing_bundle_views.cache_clear()
    _cached_launch_price_lookup.cache_clear()
    _cached_verification_statuses.cache_clear()


def _listing_event_frame(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    data_dir_text = str(data_dir.resolve())
    source_revision = listing_source_revision(data_dir)
    with _LISTING_CACHE_LOCK:
        tables = _cached_listing_source_tables(source_revision, data_dir_text)
        return tables["events"]


def cached_listing_events(data_dir: Path = DATA_DIR) -> tuple[dict[str, Any], ...]:
    return tuple(_listing_event_records(_listing_event_frame(data_dir)))


def _verification_status(row: dict[str, Any]) -> str:
    try:
        with connect() as conn:
            adjustment = conn.execute("SELECT discount_percent, effective_date FROM price_adjustments WHERE UPPER(sku)=UPPER(?) AND effective_date BETWEEN date(?, '-3 day') AND date(?) ORDER BY effective_date LIMIT 1", (row["sku"], row["date"], row["date"])).fetchone()
            if adjustment and row["old_base_price"] and row["new_base_price"]:
                actual = (row["new_base_price"] / row["old_base_price"] - 1) * 100
                return "已观察到生效" if abs(actual + float(adjustment["discount_percent"])) <= 2 else "幅度不一致"
            promotion = conn.execute("SELECT discount_percent, start_date FROM sku_promotions WHERE UPPER(sku)=UPPER(?) AND start_date BETWEEN date(?, '-3 day') AND date(?) ORDER BY start_date LIMIT 1", (row["sku"], row["date"], row["date"])).fetchone()
            if promotion and row["old_base_price"] and row["new_effective_price"]:
                return "已观察到生效" if row["new_effective_price"] < row["old_base_price"] else "部分站点生效"
    except Exception:
        return "无法核验"
    if row["type"] in {"Listing原价涨跌", "实际总价涨跌", "促销开始", "促销结束"}:
        return "未登记变价"
    return "观察中"


def _verification_status_for_event(
    row: dict[str, Any],
    adjustments: dict[str, list[dict[str, Any]]],
    promotions: dict[str, list[dict[str, Any]]],
) -> str:
    sku = _normal_text(row.get("sku"))
    try:
        event_day = date.fromisoformat(str(row["date"]))
    except (KeyError, ValueError):
        return "无法核验"
    earliest = (event_day - timedelta(days=3)).isoformat()
    event_text = event_day.isoformat()
    adjustment = next(
        (item for item in adjustments.get(sku, []) if earliest <= str(item.get("effective_date") or "") <= event_text),
        None,
    )
    if adjustment and row.get("old_base_price") and row.get("new_base_price"):
        actual = (row["new_base_price"] / row["old_base_price"] - 1) * 100
        return "已观察到生效" if abs(actual + float(adjustment["discount_percent"])) <= 2 else "幅度不一致"
    promotion = next(
        (item for item in promotions.get(sku, []) if earliest <= str(item.get("start_date") or "") <= event_text),
        None,
    )
    if promotion and row.get("old_base_price") and row.get("new_effective_price"):
        return "已观察到生效" if row["new_effective_price"] < row["old_base_price"] else "部分站点生效"
    if row.get("type") in {"Listing原价涨跌", "实际总价涨跌", "促销开始", "促销结束"}:
        return "未登记变价"
    return "观察中"


def _bulk_verification_status(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    skus = sorted({_normal_text(row.get("sku")) for row in rows if _normal_text(row.get("sku"))})
    adjustments: dict[str, list[dict[str, Any]]] = {}
    promotions: dict[str, list[dict[str, Any]]] = {}
    try:
        if skus:
            placeholders = ",".join("?" for _ in skus)
            days = [date.fromisoformat(str(row["date"])) for row in rows]
            lower = min(days).isoformat()
            upper = max(days).isoformat()
            with connect() as conn:
                adjustment_rows = conn.execute(
                    f"SELECT UPPER(sku) AS sku, discount_percent, effective_date FROM price_adjustments "
                    f"WHERE UPPER(sku) IN ({placeholders}) AND effective_date BETWEEN date(?, '-3 day') AND ? "
                    "ORDER BY effective_date",
                    (*skus, lower, upper),
                ).fetchall()
                promotion_rows = conn.execute(
                    f"SELECT UPPER(sku) AS sku, discount_percent, start_date FROM sku_promotions "
                    f"WHERE UPPER(sku) IN ({placeholders}) AND start_date BETWEEN date(?, '-3 day') AND ? "
                    "ORDER BY start_date",
                    (*skus, lower, upper),
                ).fetchall()
            for item in adjustment_rows:
                adjustments.setdefault(str(item["sku"]), []).append(dict(item))
            for item in promotion_rows:
                promotions.setdefault(str(item["sku"]), []).append(dict(item))
    except Exception:
        return ["无法核验"] * len(rows)
    return [_verification_status_for_event(row, adjustments, promotions) for row in rows]


_VERIFICATION_EVENT_FIELDS = (
    "sku", "date", "type", "old_base_price", "new_base_price", "new_effective_price",
)


@lru_cache(maxsize=256)
def _cached_verification_statuses(
    database_signature: tuple[tuple[str, int, int], ...],
    event_keys: tuple[tuple[Any, ...], ...],
) -> tuple[str, ...]:
    del database_signature
    rows = [dict(zip(_VERIFICATION_EVENT_FIELDS, values)) for values in event_keys]
    return tuple(_bulk_verification_status(rows))


def _cached_bulk_verification_status(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    event_keys = tuple(
        (
            _normal_text(row.get("sku")),
            str(row.get("date") or ""),
            str(row.get("type") or ""),
            row.get("old_base_price"),
            row.get("new_base_price"),
            row.get("new_effective_price"),
        )
        for row in rows
    )
    return list(_cached_verification_statuses(_sqlite_file_signature(), event_keys))


def _sales_response_source_signature() -> tuple[tuple[str, int, int], ...]:
    from dashboard.report_store import get_latest_source_path, get_sales_history_paths

    latest = get_latest_source_path("sales_volume_detail")
    paths = [path for path in [latest, DATA_DIR / "sources" / "sales_volume_detail_source.csv", DATA_DIR / "sales_history_records.csv", *get_sales_history_paths()] if path is not None]
    result = []
    for path in paths:
        try:
            stat = path.stat()
            result.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
        except OSError:
            result.append((str(path.resolve()), -1, -1))
    return tuple(result)


@lru_cache(maxsize=4)
def _cached_sales_response_source(
    signature: tuple[tuple[str, int, int], ...], latest_path_text: str
) -> tuple[pd.DataFrame, tuple[tuple[str, str, str], ...]]:
    del signature
    try:
        from backend.dashboard_api import load_source_frame
        from dashboard.report_store import get_sales_history_paths, read_local_table

        latest_path = Path(latest_path_text) if latest_path_text else None
        if latest_path is None or not latest_path.is_file():
            return pd.DataFrame(columns=["_sku", "_asin", "_country"]), ()
        frames = []
        for history_path in get_sales_history_paths():
            try:
                frames.append(read_local_table(history_path))
            except Exception:
                continue
        frames.append(load_source_frame("sales_volume_detail", "销量明细").copy())
        source = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    except Exception:
        return pd.DataFrame(columns=["_sku", "_asin", "_country"]), ()

    aliases = {str(column).strip().casefold(): column for column in source.columns}
    sku_column = aliases.get("msku") or aliases.get("sku")
    asin_column = aliases.get("asin")
    country_column = aliases.get("国家") or aliases.get("country")
    if not sku_column or not asin_column or not country_column:
        return pd.DataFrame(columns=["_sku", "_asin", "_country"]), ()
    day_columns = []
    day_specs = []
    for column in source.columns:
        match = re.fullmatch(r"(\d{2})-(\d{2})销量", str(column).strip())
        if match:
            day_columns.append(column)
            day_specs.append((str(column), match.group(1), match.group(2)))
    if not day_columns:
        return pd.DataFrame(columns=["_sku", "_asin", "_country"]), ()

    working = pd.DataFrame(
        {
            "_sku": source[sku_column].map(_normal_text),
            "_asin": source[asin_column].map(_normal_text),
            "_country": source[country_column].map(
                lambda value: COUNTRY_MAP.get(_normal_text(value), _normal_text(value))
            ),
        },
        index=source.index,
    )
    # Normalize daily units once when building the cached response index rather
    # than repeating string-to-number conversion for every event on each page.
    daily_sales = source[day_columns].apply(pd.to_numeric, errors="coerce")
    working = pd.concat([working, daily_sales], axis=1)
    grouped = working.groupby(["_sku", "_asin", "_country"], as_index=False, sort=False)[day_columns].last()
    return grouped, tuple(day_specs)


_SALES_RESPONSE_CACHE_LOCK = RLock()


def _sales_response_source() -> tuple[pd.DataFrame, tuple[tuple[str, str, str], ...]]:
    from dashboard.report_store import get_latest_source_path

    latest = get_latest_source_path("sales_volume_detail")
    latest_text = str(latest.resolve()) if latest else ""
    signature = _sales_response_source_signature()
    with _SALES_RESPONSE_CACHE_LOCK:
        return _cached_sales_response_source(signature, latest_text)


def _filtered_observation_event_frame(
    *,
    day: str | None = None,
    country: str | None = None,
    kind: str | None = None,
    search: str = "",
    data_dir: Path = DATA_DIR,
) -> pd.DataFrame:
    events = _listing_event_frame(data_dir)
    if events.empty:
        return events
    mask = pd.Series(True, index=events.index)
    if day:
        mask &= events["date"].astype(str).eq(day)
    normalized_country = COUNTRY_MAP.get(_normal_text(country), _normal_text(country)) if country else None
    if normalized_country:
        mask &= events["country"].astype(str).eq(normalized_country)
    if kind:
        mask &= events["type"].astype(str).eq(kind)
    needle = _normal_text(search)
    if needle:
        sku_match = events["sku"].fillna("").astype(str).str.upper().str.contains(needle, regex=False)
        asin_match = events["asin"].fillna("").astype(str).str.upper().str.contains(needle, regex=False)
        mask &= sku_match | asin_match
    return events.loc[mask].copy()


def _attach_observation_verification(rows: list[dict[str, Any]], statuses: list[str] | None = None) -> None:
    if not rows:
        return
    if statuses is None:
        statuses = _bulk_verification_status(rows)
    launch_map = _launch_price_lookup()
    for item, verification_status in zip(rows, statuses):
        item["launch_price"] = launch_map.get(item["sku"], {}).get(item["country"])
        item["launch_change"] = (
            item["new_effective_price"] / item["launch_price"] - 1
            if item["new_effective_price"] and item["launch_price"]
            else None
        )
        item["verification_status"] = verification_status


def observation_rows(*, day: str | None = None, country: str | None = None, kind: str | None = None, search: str = "", data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    rows = _listing_event_records(_filtered_observation_event_frame(
        day=day, country=country, kind=kind, search=search, data_dir=data_dir,
    ))
    _attach_observation_verification(rows)
    return rows


def _sales_response(
    event: dict[str, Any],
    source_context: tuple[pd.DataFrame, tuple[tuple[str, str, str], ...]] | None = None,
) -> dict[str, Any]:
    source, day_columns = source_context or _sales_response_source()
    level = "SKU级"
    if source.empty or not day_columns:
        return {"status": "数据不足", "match_level": None}
    mask = (
        source["_sku"].eq(_normal_text(event.get("sku")))
        & source["_asin"].eq(_normal_text(event.get("asin")))
        & source["_country"].eq(COUNTRY_MAP.get(_normal_text(event.get("country")), _normal_text(event.get("country"))))
    )
    selected = source.loc[mask]
    if selected.empty:
        selected = source.loc[
            source["_asin"].eq(_normal_text(event.get("asin")))
            & source["_country"].eq(COUNTRY_MAP.get(_normal_text(event.get("country")), _normal_text(event.get("country"))))
        ]
        level = "ASIN级参考"
    if selected.empty:
        return {"status": "数据不足", "match_level": level}

    columns = [column for column, _, _ in day_columns]
    totals = selected[columns].sum(axis=0, skipna=True)
    event_day = pd.Timestamp(event["date"]).date()
    pre = post = 0.0
    post_dates = set()
    for column, month, day_value in day_columns:
        try:
            parsed = date(event_day.year, int(month), int(day_value))
            if parsed > event_day + timedelta(days=3) and int(month) > event_day.month:
                parsed = date(event_day.year - 1, int(month), int(day_value))
            elif parsed < event_day - timedelta(days=7) and int(month) < event_day.month:
                parsed = date(event_day.year + 1, int(month), int(day_value))
        except ValueError:
            continue
        amount = float(totals.get(column, 0) or 0)
        if event_day < parsed <= event_day + timedelta(days=3):
            post_dates.add(parsed)
            post += amount
        elif event_day - timedelta(days=7) <= parsed < event_day:
            pre += amount
    if len(post_dates) < 3:
        return {"status": "观察中", "match_level": level, "baseline_units": pre, "post_units": post}
    if pre < 5:
        return {"status": "数据不足", "match_level": level, "baseline_units": pre, "post_units": post}
    change = (post / 3) / (pre / 7) - 1
    if abs(change) < 0.2:
        status = "暂无明显响应"
    elif event.get("new_effective_price") is not None and event.get("old_effective_price") is not None and event["new_effective_price"] < event["old_effective_price"]:
        status = "与降价同向" if change > 0 else "方向相反"
    else:
        status = "与涨价同向" if change < 0 else "方向相反"
    return {"status": status, "match_level": level, "baseline_units": pre, "post_units": post, "daily_change": change}


@router.get("/observations")
def observations(day: str | None = None, country: str | None = None, kind: str | None = None, status: str | None = None, search: str = "", page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=200)):
    events = _filtered_observation_event_frame(day=day, country=country, kind=kind, search=search)
    start = (page - 1) * page_size
    if status:
        candidates = _listing_event_records(events)
        candidate_statuses = _bulk_verification_status(candidates)
        matching = [(row, value) for row, value in zip(candidates, candidate_statuses) if value == status]
        total = len(matching)
        page_matches = matching[start:start + page_size]
        page_rows = [row for row, _ in page_matches]
        page_statuses = [value for _, value in page_matches]
    else:
        total = len(events)
        page_rows = _listing_event_records(events.iloc[start:start + page_size])
        page_statuses = _cached_bulk_verification_status(page_rows)
    _attach_observation_verification(page_rows, page_statuses)
    if page_rows:
        source_context = _sales_response_source()
        for row in page_rows:
            row["sales_response"] = _sales_response(row, source_context)
    return {"rows": page_rows, "page": page, "page_size": page_size, "total": total, "retention_days": 31}


def reports_listing_index(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    return {"records": load_listing_index(data_dir).to_dict("records"), "retention_days": 31}

def upload_listing_file(name: str, data: bytes, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    return persist_listing_snapshot(name, data, data_dir)

def listing_preview(day: str, limit: int = 50, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    frame = load_snapshot(day, data_dir)
    if frame.empty: raise HTTPException(404, "该日期没有 Listing 快照")
    bounded = min(max(limit, 1), 200)
    return {"title": f"Listing价格 {day}", "columns": list(frame.columns), "rows": json.loads(frame.head(bounded).to_json(orient="records", force_ascii=False)), "total": len(frame)}

def listing_download(day: str, data_dir: Path = DATA_DIR) -> Path:
    raw, _ = _paths_for_date(day, data_dir)
    if not raw.exists(): raise HTTPException(404, "该日期没有 Listing 快照")
    return raw
