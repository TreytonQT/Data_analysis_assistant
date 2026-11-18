"""Marketplace-specific observed price changes and current sales trends."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from functools import lru_cache
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app_paths import DATA_DIR
from backend.listing_prices import (
    COUNTRY_MAP, LISTING_RETENTION_DAYS, _normal_text,
    _paths_for_date, load_listing_index, load_snapshot,
)
from dashboard.data_processing import _sales_detail_date_mapping
from dashboard.derived_table_cache import load_or_build_frame_bundle
from dashboard.report_store import (
    get_latest_source_path, get_sales_history_paths, load_latest_source_record, read_local_table,
)

router = APIRouter(prefix="/api/pricing/monitor", tags=["price-monitor"])
KEYS = ["sku", "asin", "country"]
LOCK = RLock()


def _revision(namespace: str, paths: list[Path]) -> str:
    digest = hashlib.sha256(namespace.encode("utf-8"))
    for path in sorted(set(paths), key=str):
        if path.is_file():
            stat = path.stat()
            digest.update(f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8"))
    return digest.hexdigest()


def business_day() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def _records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", force_ascii=False, double_precision=15))


def price_band(old: float, new: float) -> int:
    # Decimal keeps an exact 5% boundary out of the preceding bucket.
    change = abs((Decimal(str(new)) / Decimal(str(old)) - 1) * 100)
    return int((change / 5).to_integral_value(rounding=ROUND_FLOOR)) * 5


def _price_snapshot(day: str, data_dir: Path) -> pd.DataFrame:
    # Price events do not need the old workbook's recovered variant columns.
    _, source = _paths_for_date(day, data_dir)
    columns = {"MSKU", "ASIN", "国家", "币种", "当前实际总价", "Listing原价", "促销中", "异常类型"}
    if source.is_file():
        frame = pd.read_csv(source, encoding="utf-8-sig", dtype=object, usecols=lambda column: column in columns)
        if columns.issubset(frame.columns):
            return frame
    return load_snapshot(day, data_dir)


def _event_frame(data_dir: Path) -> pd.DataFrame:
    index = load_listing_index(data_dir)
    days = index["日期"].astype(str).tolist()
    pairs = []
    for previous, current in zip(days, days[1:]):
        paths = [*_paths_for_date(previous, data_dir), *_paths_for_date(current, data_dir)]
        revision = _revision(f"price-monitor-pair-v3:{previous}:{current}", paths)

        def build(previous=previous, current=current):
            before, after = _price_snapshot(previous, data_dir), _price_snapshot(current, data_dir)
            merged = before.merge(after, on=["MSKU", "ASIN", "国家"], suffixes=("_old", "_new"), validate="one_to_one")
            old = pd.to_numeric(merged["当前实际总价_old"], errors="coerce")
            new = pd.to_numeric(merged["当前实际总价_new"], errors="coerce")
            valid = old.gt(0) & new.gt(0) & new.sub(old).abs().gt(.01)
            valid &= merged["币种_old"].notna() & merged["币种_old"].ne("") & merged["币种_old"].eq(merged["币种_new"])
            selected = merged.loc[valid]
            events = selected[["MSKU", "ASIN", "国家", "币种_new"]].rename(columns={"MSKU": "sku", "ASIN": "asin", "国家": "country", "币种_new": "currency"}).copy()
            events["old_effective_price"] = old.loc[valid]
            events["new_effective_price"] = new.loc[valid]
            events["old_base_price"] = pd.to_numeric(selected["Listing原价_old"], errors="coerce")
            events["new_base_price"] = pd.to_numeric(selected["Listing原价_new"], errors="coerce")
            events["old_promo"] = selected["促销中_old"].map(lambda value: str(value).lower() in {"true", "1", "yes", "是"})
            events["new_promo"] = selected["促销中_new"].map(lambda value: str(value).lower() in {"true", "1", "yes", "是"})
            events["date"] = current
            events["previous_date"] = previous
            events["gap_days"] = (date.fromisoformat(current) - date.fromisoformat(previous)).days
            events["observed_as"] = "首次观察到" if events["gap_days"].gt(1).any() else current
            events["type"] = "实际总价涨跌"
            events["anomaly"] = selected["异常类型_new"]
            return {"events": events}, {}

        frames, _ = load_or_build_frame_bundle("price-monitor-pair", revision, build)
        pairs.append(frames["events"])
    return pd.concat(pairs, ignore_index=True) if pairs else pd.DataFrame(columns=[*KEYS, "date", "old_effective_price", "new_effective_price", "currency"])


def _dated_sales(frame: pd.DataFrame, reference: date) -> pd.DataFrame:
    frame = frame.drop_duplicates().copy()
    aliases = {str(c).strip().casefold(): c for c in frame.columns}
    identifiers = [aliases.get("msku"), aliases.get("asin"), aliases.get("国家") or aliases.get("country")]
    if not all(identifiers):
        return pd.DataFrame(columns=KEYS)
    mapping = _sales_detail_date_mapping(frame, "销量", reference)
    result = pd.DataFrame({key: frame[column].map(_normal_text) for key, column in zip(KEYS, identifiers)})
    result["country"] = result["country"].map(lambda v: COUNTRY_MAP.get(v, v))
    for column, day in mapping.items():
        values = pd.to_numeric(frame[column], errors="coerce")
        result[day.date().isoformat()] = values.where(values.ge(0) & values.lt(float("inf")))
    grouped = result.groupby(KEYS, sort=False, dropna=False)
    numeric = [c for c in result.columns if c not in KEYS]
    if not numeric:
        return pd.DataFrame(columns=KEYS)
    totals = grouped[numeric].sum(min_count=1)
    totals = totals.where(grouped[numeric].count().eq(grouped.size(), axis=0))
    return totals.reset_index()


def sales_trends(data_dir: Path, today: date) -> tuple[pd.DataFrame, str | None, list[str]]:
    latest = get_latest_source_path("sales_volume_detail", data_dir)
    columns = [*KEYS, "units_7", "units_30", "t_value", "units_7_source", "units_30_source"]
    record = load_latest_source_record("sales_volume_detail", data_dir)
    name = str(record.iloc[-1].get("原始文件名", "")) if not record.empty else ""
    dates = re.findall(r"20\d{2}-\d{2}-\d{2}", name)
    uploaded = str(record.iloc[-1].get("上传时间", ""))[:10] if not record.empty else ""
    reference = date.fromisoformat(dates[-1] if dates else uploaded) if dates or uploaded else today
    latest_frame = _dated_sales(read_local_table(latest), reference) if latest else pd.DataFrame(columns=KEYS)
    latest_dates = [c for c in latest_frame.columns if c not in KEYS]
    history_paths = get_sales_history_paths(data_dir)
    if not latest_dates:
        eligible = [path for path in history_paths if path.stem <= today.strftime("%Y-%m")]
        if not eligible:
            return pd.DataFrame(columns=columns), None, ["未找到含MSKU、ASIN、国家及日销量的明细或往月销量"]
        last_day = (pd.Timestamp(max(path.stem for path in eligible)) + pd.offsets.MonthEnd()).date()
    else:
        last_day = date.fromisoformat(max(latest_dates))
    end = min(last_day, today - timedelta(days=1))
    start = end - timedelta(days=29)
    required = [(start + timedelta(days=i)).isoformat() for i in range(30)]
    parts = []
    for source in history_paths:
        month = source.stem
        if start.strftime("%Y-%m") <= month <= end.strftime("%Y-%m"):
            month_end = (pd.Timestamp(month) + pd.offsets.MonthEnd()).date()
            historical = _dated_sales(read_local_table(source), month_end)
            parts.append(historical.set_index(KEYS))
    historical = pd.concat(parts, axis=1) if parts else pd.DataFrame(index=latest_frame.set_index(KEYS).index)
    historical = historical.reindex(columns=required)
    # Prefer known latest cells, including zero; fill only missing identities/dates from history.
    latest_values = latest_frame.set_index(KEYS).reindex(columns=required)
    combined = latest_values.combine_first(historical).reindex(columns=required)
    if combined.empty:
        return pd.DataFrame(columns=columns), None, ["未找到可关联的站点日销量"]
    latest_known = latest_values.reindex(index=combined.index).notna()
    origin = pd.DataFrame("往月销量", index=combined.index, columns=required).where(combined.notna(), "")
    origin = origin.mask(latest_known, "销量明细")
    result = combined.index.to_frame(index=False)
    result["units_7"] = combined[required[-7:]].sum(axis=1, min_count=7).to_numpy()
    result["units_30"] = combined[required].sum(axis=1, min_count=30).to_numpy()
    result["t_value"] = result["units_7"] / 7 - result["units_30"] / 30
    for window in (7, 30):
        result[f"units_{window}_source"] = origin[required[-window:]].apply(lambda row: "＋".join(value for value in ("销量明细", "往月销量") if value in set(row)), axis=1).to_numpy()
    return result, end.isoformat(), []


def _signature(data_dir: Path) -> str:
    paths = list((data_dir / "listing_prices").glob("*"))
    for key in ("operational_sales", "sales_volume_detail", "sku_image_map"):
        paths.extend((data_dir / "sources").glob(key + ".*"))
        paths.append(data_dir / "sources" / (key + "_source.csv"))
    paths += get_sales_history_paths(data_dir)
    paths += [data_dir / "sales_history_records.csv"]
    return _revision("price-monitor-v4", paths)


@lru_cache(maxsize=2)
def _base(revision: str, data_dir_text: str, today_text: str) -> dict:
    del revision
    data_dir = Path(data_dir_text)
    events = _event_frame(data_dir)
    trends, as_of, warnings = sales_trends(data_dir, date.fromisoformat(today_text))
    latest = events.sort_values("date", kind="stable").drop_duplicates(KEYS, keep="last").copy()
    latest = latest.merge(trends, on=KEYS, how="left")
    latest["developer"] = ""
    latest["image"] = None
    operational_path = get_latest_source_path("operational_sales", data_dir)
    if operational_path:
        from backend.dashboard_api import _sku_image_lookup, _rows_with_sku_images
        operational = read_local_table(operational_path)
        if "MSKU" in operational and "ASIN" in operational and "开发员" in operational:
            meta = operational[["MSKU", "ASIN", "开发员"]].copy()
            meta["sku"] = meta["MSKU"].map(_normal_text)
            meta["asin"] = meta["ASIN"].map(_normal_text)
            developers = meta.groupby(["sku", "asin"])["开发员"].agg(lambda values: "；".join(sorted(set(str(v).strip() for v in values if pd.notna(v)))))
            latest["developer"] = [developers.get((s, a), "") for s, a in latest[["sku", "asin"]].itertuples(index=False, name=None)]
            image_path = get_latest_source_path("sku_image_map", data_dir)
            if image_path and not latest.empty:
                image_lookup = _sku_image_lookup(operational, read_local_table(image_path))
                images = _rows_with_sku_images(image_lookup)(latest.rename(columns={"sku": "SKU", "asin": "ASIN"}))
                latest["image"] = [row.get("image") for row in images]
    latest["change"] = latest["new_effective_price"] / latest["old_effective_price"] - 1
    latest["band"] = [price_band(old, new) for old, new in latest[["old_effective_price", "new_effective_price"]].itertuples(index=False, name=None)]
    latest["direction"] = latest["change"].map(lambda value: "up" if value > 0 else "down")
    latest["abs_t"] = latest["t_value"].abs()
    latest["trend"] = latest["t_value"].map(lambda value: "missing" if pd.isna(value) else "up" if value > 0 else "down" if value < 0 else "flat")
    latest["observation"] = "当前趋势"
    if as_of:
        pending = latest["date"].gt(as_of)
        latest.loc[pending, ["t_value", "abs_t", "units_7", "units_30"]] = None
        latest.loc[pending, "trend"] = "missing"
        latest.loc[pending, "observation"] = "销量待更新"
        recent = ~pending & (pd.Timestamp(as_of) - pd.to_datetime(latest["date"])).dt.days.lt(7)
        latest.loc[recent, "observation"] = "变价未满7天"
    index = load_listing_index(data_dir)
    days = index["日期"].astype(str).tolist()
    return {"frame": latest, "events": events, "as_of": as_of, "warnings": warnings,
            "coverage": {"start": days[0] if days else None, "end": days[-1] if days else None},
            "developers": sorted({v for text in latest["developer"] for v in text.split("；") if v})}


def base_data(data_dir: Path = DATA_DIR) -> dict:
    with LOCK:
        return _base(_signature(data_dir), str(data_dir.resolve()), business_day().isoformat())


def filtered(base: dict, direction: str, developers: str = "", country: str = "", band: int | None = None,
             date_start: str | None = None, date_end: str | None = None, search: str = "", trend: str = "all",
             sort_by: str = "abs_t", sort_order: str = "desc") -> pd.DataFrame:
    frame = base["frame"]
    end = base["coverage"]["end"]
    try:
        first = date.fromisoformat(date_start) if date_start else date.fromisoformat(end) - timedelta(days=29) if end else None
        last = date.fromisoformat(date_end) if date_end else date.fromisoformat(end) if end else None
    except ValueError as exc:
        raise HTTPException(422, "日期格式必须为YYYY-MM-DD") from exc
    if first and last and first > last:
        raise HTTPException(422, "开始日期不能晚于结束日期")
    frame = frame.loc[frame["direction"].eq(direction)].copy()
    if first:
        frame = frame.loc[frame["date"].ge(first.isoformat())]
    if last:
        frame = frame.loc[frame["date"].le(last.isoformat())]
    if country:
        frame = frame.loc[frame["country"].eq(country)]
    if developers:
        chosen = set(developers.split(","))
        frame = frame.loc[frame["developer"].map(lambda text: bool(chosen.intersection(text.split("；"))))]
    if band is not None:
        frame = frame.loc[frame["band"].eq(band)]
    if trend != "all":
        frame = frame.loc[frame["trend"].eq(trend)]
    if search.strip():
        needle = search.strip().upper()
        frame = frame.loc[frame["sku"].str.contains(needle, regex=False) | frame["asin"].str.contains(needle, regex=False)]
    allowed_sort = {"abs_t", "t_value", "date", "change", "units_7", "units_30", "sku"}
    if sort_by not in allowed_sort:
        raise HTTPException(422, "未知排序字段")
    return frame.sort_values([sort_by, *[key for key in KEYS if key != sort_by]], ascending=[sort_order == "asc", *[True for key in KEYS if key != sort_by]], na_position="last", kind="stable")


@router.get("")
def monitor(direction: str = Query("up", pattern="^(up|down)$"), developers: str = "", country: str = Query("", pattern="^(|DE|FR|ES|IT)$"),
            band: int | None = Query(None, ge=0), date_start: str | None = None, date_end: str | None = None,
            search: str = Query("", max_length=200), trend: str = Query("all", pattern="^(all|up|down|flat|missing)$"),
            sort_by: str = "abs_t", sort_order: str = Query("desc", pattern="^(asc|desc)$"),
            page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=200)):
    base = base_data()
    frame = filtered(base, direction, developers, country, band, date_start, date_end, search, trend, sort_by, sort_order)
    buckets = []
    for lower, group in frame.groupby("band", sort=True):
        valid = group["t_value"].dropna()
        buckets.append({"band": int(lower), "label": f"{lower}–{lower + 5}%", "count": len(group),
                        "valid_count": len(valid), "mean_t": float(valid.mean()) if len(valid) else None,
                        "up_ratio": float(valid.gt(0).mean()) if len(valid) else None})
    counts = frame["trend"].value_counts()
    return {"rows": _records(frame.iloc[(page - 1) * page_size:page * page_size]), "total": len(frame), "page": page, "page_size": page_size,
            "buckets": buckets, "metrics": {"total": len(frame), "up": int(counts.get("up", 0)), "down": int(counts.get("down", 0)),
            "valid": int(frame["t_value"].notna().sum()), "missing": int(counts.get("missing", 0))},
            "as_of": base["as_of"], "coverage": base["coverage"], "developers": base["developers"],
            "warnings": base["warnings"], "retention_days": LISTING_RETENTION_DAYS}


@router.get("/history")
def history(sku: str, asin: str, country: str):
    frame = base_data()["events"]
    for key, value in zip(KEYS, (sku, asin, country)):
        frame = frame.loc[frame[key].eq(_normal_text(value))]
    return {"rows": _records(frame.sort_values("date", ascending=False))}


@router.get("/export.csv")
def export_monitor(direction: str = Query("up", pattern="^(up|down)$"), developers: str = "", country: str = Query("", pattern="^(|DE|FR|ES|IT)$"),
                   band: int | None = Query(None, ge=0), date_start: str | None = None, date_end: str | None = None,
                   search: str = Query("", max_length=200), trend: str = Query("all", pattern="^(all|up|down|flat|missing)$"),
                   sort_by: str = "abs_t", sort_order: str = Query("desc", pattern="^(asc|desc)$")):
    base = base_data()
    frame = filtered(base, direction, developers, country, band, date_start, date_end, search, trend, sort_by, sort_order)
    names = {"sku": "SKU", "asin": "ASIN", "country": "国家", "developer": "开发员", "date": "观察日期", "previous_date": "前次快照日期",
             "old_effective_price": "变价前实际总价", "new_effective_price": "变价后实际总价", "currency": "币种", "change": "涨跌幅（比例）",
             "units_7": "近7天销量", "units_30": "近30天销量", "t_value": "T值", "observation": "观察提示"}
    output = frame.reindex(columns=list(names)).rename(columns=names)
    output["销量截止日"] = base["as_of"]
    return Response(output.to_csv(index=False).encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="price-{direction}.csv"'})
