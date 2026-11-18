"""SKU-centred operating diagnosis, independent of dashboard page serializers."""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app_paths import DATA_DIR, CONFIG_DIR
from backend import price_monitor as prices
from backend.listing_prices import load_listing_index, COUNTRY_MAP
from backend.product_filters import filter_margin
from dashboard.data_processing import (
    AGING_STOCK_COLUMNS, AGING_CAPITAL_COLUMNS, AVAILABLE_INVENTORY_STOCK_COLUMNS,
    normalize_config_number, normalize_gross_profit_source, normalize_sku_image_map,
    attach_sku_image_map, exclude_stopped_store_operational_rows,
    normalize_replenishment_listing_dates, replenishment_calibrated_daily_sales,
    replenishment_total_stock,
)
from dashboard.report_store import get_latest_source_path, load_latest_source_record, read_local_table, get_sales_history_paths

router = APIRouter(prefix="/api/product-operations", tags=["product-operations"])
COUNTRIES = ["DE", "FR", "ES", "IT"]
AGE_LABELS = ["91–180天", "181–330天", "331–365天", "366–455天", "456天以上"]
AGE_START = {"90": 0, "180": 1, "365": 3}
LOCK = RLock()


def joined(values) -> str:
    return "；".join(dict.fromkeys(str(v).strip() for v in values if pd.notna(v) and str(v).strip()))


def source_info(key: str, data_dir: Path) -> dict:
    frame = load_latest_source_record(key, data_dir)
    if frame.empty:
        return {"available": False, "uploaded_at": None, "start": None, "end": None}
    row = frame.iloc[-1]
    dates = re.findall(r"20\d{2}-\d{2}-\d{2}", str(row.get("原始文件名", "")))
    return {"available": True, "uploaded_at": str(row.get("上传时间", "")), "start": dates[0] if dates else None,
            "end": dates[-1] if dates else None}


def read_source(key: str, data_dir: Path) -> pd.DataFrame:
    path = get_latest_source_path(key, data_dir)
    return read_local_table(path) if path else pd.DataFrame()


def db_rows(data_dir: Path, sql: str, parameters=()) -> list[dict]:
    path = data_dir / "app.db"
    if not path.is_file():
        return []
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(sql, parameters)]
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return []
        raise
    finally:
        conn.close()


def build_catalog(operational: pd.DataFrame, gross: pd.DataFrame, listing: pd.DataFrame,
                  launch: pd.DataFrame, images: pd.DataFrame, stores: pd.DataFrame, today: date) -> dict:
    """Keep stock at SKU grain and marketplace facts in a separate table."""
    source = operational.copy().reset_index(drop=True)
    for column in ("MSKU", "ASIN", "开发员", "本地SKU名称"):
        if column not in source:
            source[column] = ""
    source["sku"] = source["MSKU"].map(prices._normal_text)
    source["asin"] = source["ASIN"].map(prices._normal_text)
    source = source.loc[source["sku"].ne("")].copy()
    names = source.groupby("sku", sort=False)["本地SKU名称"].agg(joined).to_dict()
    developers = source.groupby("sku", sort=False)["开发员"].agg(joined).to_dict()
    asins = source.groupby("sku", sort=False)["asin"].agg(lambda values: sorted({v for v in values if v})).to_dict()
    numeric = [*AGING_STOCK_COLUMNS, *AGING_CAPITAL_COLUMNS, *AVAILABLE_INVENTORY_STOCK_COLUMNS,
               "日均销量", "7天销量", "30天销量", "90天销量"]
    numeric = list(dict.fromkeys(numeric))
    for column in numeric:
        source[column] = normalize_config_number(source[column]) if column in source else float("nan")
        if column in {"日均销量", "7天销量", "30天销量", "90天销量"}:
            source[column] = source[column].where(source[column].ge(0) & source[column].lt(float("inf")))
    # Personnel/name metadata must not replicate the same physical source record.
    identity = [c for c in ("sku", "asin", "店铺名称", "本地SKU", *numeric) if c in source]
    stock = source.drop_duplicates(subset=identity)
    # Reuse the selected physical rows, but read raw sales before other views' cleaning.
    metric_raw = operational.reset_index(drop=True).iloc[stock.index]
    metric_numeric = metric_raw.reindex(columns=["7天销量", "14天销量", "30天销量", *AVAILABLE_INVENTORY_STOCK_COLUMNS]).apply(normalize_config_number)
    metric_numeric = metric_numeric.where(metric_numeric.gt(-float("inf")) & metric_numeric.lt(float("inf")))
    listing_dates = normalize_replenishment_listing_dates(metric_raw.reindex(columns=["上架时间"])["上架时间"])
    age_days = (pd.Timestamp(today) - listing_dates).dt.days
    metric_rows = pd.DataFrame({"sku": stock["sku"],
        "clearance_daily_units": replenishment_calibrated_daily_sales(metric_numeric["7天销量"], metric_numeric["14天销量"], metric_numeric["30天销量"], age_days),
        "clearance_total_stock": replenishment_total_stock(metric_numeric)})
    metric_groups = metric_rows.groupby("sku", sort=False)
    metric_fields = ["clearance_daily_units", "clearance_total_stock"]
    metric_totals = metric_groups[metric_fields].sum(min_count=1).where(metric_groups[metric_fields].count().eq(metric_groups.size(), axis=0))

    def aggregate(frame: pd.DataFrame) -> pd.DataFrame:
        group = frame.groupby("sku", sort=False)
        values = group[numeric].sum(min_count=1)
        return values.where(group[numeric].count().eq(group.size(), axis=0))

    totals = aggregate(stock)
    actionable = exclude_stopped_store_operational_rows(stock, stores if not stores.empty else None)
    eligible = aggregate(actionable)
    known_skus = set(totals.index)
    for frame in (gross, listing):
        if "MSKU" in frame:
            known_skus.update(frame["MSKU"].map(prices._normal_text))
        if {"MSKU", "开发员"}.issubset(frame.columns):
            for sku, rows in frame.groupby(frame["MSKU"].map(prices._normal_text)):
                developers[sku] = joined([*developers.get(sku, "").split("；"), *rows["开发员"].dropna()])
    facts = pd.DataFrame({"sku": pd.Series(sorted(known_skus - {""}), dtype="str")})
    facts["product_name"] = facts["sku"].map(names).fillna("")
    facts["developer"] = facts["sku"].map(developers).fillna("")
    facts["asins"] = facts["sku"].map(lambda sku: asins.get(sku, []))
    fields = {"stock": "可售", "daily_units": "日均销量", "units_7": "7天销量", "units_30": "30天销量", "units_90": "90天销量"}
    for field, column in fields.items():
        facts[field] = facts["sku"].map(totals[column])
    facts["coverage_days"] = facts["stock"] / facts["daily_units"].where(facts["daily_units"].gt(0))
    for field in metric_fields:
        facts[field] = facts["sku"].map(metric_totals[field])
    facts["clearance_available_days"] = facts["clearance_total_stock"] / facts["clearance_daily_units"].where(facts["clearance_daily_units"].gt(0))
    for index in range(5):
        facts[f"age_stock_{index}"] = facts["sku"].map(totals[AGING_STOCK_COLUMNS[index]])
        facts[f"age_capital_{index}"] = facts["sku"].map(totals[AGING_CAPITAL_COLUMNS[index]])
    for scope, start in AGE_START.items():
        facts[f"capital_{scope}"] = facts["sku"].map(totals[AGING_CAPITAL_COLUMNS[start:]].sum(axis=1, min_count=5-start))
        facts[f"aged_stock_{scope}"] = facts["sku"].map(totals[AGING_STOCK_COLUMNS[start:]].sum(axis=1, min_count=5-start))
        facts[f"action_capital_{scope}"] = facts["sku"].map(eligible[AGING_CAPITAL_COLUMNS[start:]].sum(axis=1, min_count=5-start))
        facts[f"action_stock_{scope}"] = facts["sku"].map(eligible[AGING_STOCK_COLUMNS[start:]].sum(axis=1, min_count=5-start))
    launch_map = {}
    for row in launch.to_dict("records"):
        key = prices._normal_text(row.get("sku", row.get("SKU")))
        if key:
            value = row.get("arrival_date", row.get("开售时间"))
            if pd.notna(pd.to_datetime(value, errors="coerce")):
                launch_map[key] = min(str(value)[:10], launch_map.get(key, str(value)[:10]))
    dates = pd.to_datetime(facts["sku"].map(launch_map), errors="coerce")
    facts["launch_date"] = dates.dt.strftime("%Y-%m-%d")
    facts["launch_days"] = (pd.Timestamp(today) - dates.dt.normalize()).dt.days
    facts["is_new"] = facts["launch_days"].between(0, 99)
    facts["is_low_sales_new"] = facts["is_new"] & facts["stock"].gt(0) & facts["units_90"].lt(5)
    facts["is_aged"] = facts["aged_stock_90"].gt(0)
    facts["image"] = None
    image_lookup = {}
    if not images.empty and not source.empty:
        mapping = normalize_sku_image_map(images)
        required = {"MSKU", "ASIN"} if {"MSKU", "ASIN", "图片链接"}.issubset(mapping.columns) else {"本地SKU", "MSKU"}
        if required.issubset(source.columns):
            matched = attach_sku_image_map(source, mapping)
            for row in matched.loc[matched["库存图片链接"].notna()].to_dict("records"):
                key = prices._normal_text(row["MSKU"])
                image_lookup.setdefault(key, {"url": row["库存图片链接"], "inventory_sku": str(row.get("库存SKU", "")), "virtual_sku": str(row.get("虚拟SKU", ""))})
    facts["image"] = facts["sku"].map(image_lookup)

    market_columns = ["sku", "asin", "country", "units", "sales", "profit", "margin", "ad_ratio", "current_price", "base_price", "currency", "rating_count", "rating"]
    financial = pd.DataFrame(columns=market_columns[:8])
    if not gross.empty:
        gross = gross.drop_duplicates(subset=[c for c in gross if c not in {"开发员", "开发专员", "产品名称", "本地SKU名称"}])
        normalized = normalize_gross_profit_source(gross)
        normalized["sku"] = normalized["MSKU"].map(prices._normal_text)
        normalized["asin"] = normalized["ASIN"].map(prices._normal_text)
        normalized["country"] = normalized["国家"].map(lambda value: COUNTRY_MAP.get(prices._normal_text(value), prices._normal_text(value)))
        strict_sum = lambda values: values.sum(min_count=len(values))
        financial = normalized.groupby(["sku", "asin", "country"], as_index=False).agg(units=("销量", strict_sum), sales=("销售额", strict_sum), profit=("毛利润", strict_sum), ads=("广告支出净额", strict_sum))
        financial["margin"] = financial["profit"] / financial["sales"].where(financial["sales"].ne(0))
        financial["ad_ratio"] = financial["ads"].abs() / financial["sales"].where(financial["sales"].ne(0))
    current = pd.DataFrame(columns=["sku", "asin", "country", "current_price", "base_price", "currency", "rating_count", "rating"])
    if not listing.empty:
        current = listing.rename(columns={"MSKU": "sku", "ASIN": "asin", "国家": "country", "当前实际总价": "current_price", "Listing原价": "base_price", "币种": "currency", "Rating总数": "rating_count", "评分": "rating"}).copy()
        for column in ("sku", "asin", "country"):
            current[column] = current[column].map(prices._normal_text)
        current = current.reindex(columns=["sku", "asin", "country", "current_price", "base_price", "currency", "rating_count", "rating"]).drop_duplicates(["sku", "asin", "country"], keep="last")
        for column in ("current_price", "base_price", "rating_count", "rating"):
            current[column] = pd.to_numeric(current[column], errors="coerce")
    markets = financial.merge(current, on=["sku", "asin", "country"], how="outer").reindex(columns=market_columns)
    worst = markets.groupby("sku")["margin"].min()
    facts["worst_margin"] = facts["sku"].map(worst)
    facts["is_low_margin"] = facts["worst_margin"].lt(.2)
    for sku, group in markets.groupby("sku"):
        asins[sku] = sorted(set(asins.get(sku, [])) | set(group["asin"].dropna()) - {""})
    facts["asins"] = facts["sku"].map(lambda sku: asins.get(sku, []))
    return {"facts": facts, "markets": markets, "excluded_clearance_rows": len(stock) - len(actionable)}


def catalog_revision(data_dir: Path, config_dir: Path) -> str:
    paths = []
    for key in ("operational_sales", "gross_profit", "sku_image_map", "sales_volume_detail"):
        paths.extend((data_dir / "sources").glob(key + ".*"))
        paths.append(data_dir / "sources" / (key + "_source.csv"))
    index = load_listing_index(data_dir)
    paths.append(data_dir / "listing_prices" / "index.csv")
    if not index.empty:
        paths.extend(prices._paths_for_date(str(index.iloc[-1]["日期"]), data_dir))
    paths += [data_dir / "app.db", data_dir / "app.db-wal", config_dir / "store_config.csv"]
    return prices._revision("product-catalog-v2", paths)


@lru_cache(maxsize=2)
def _catalog(revision: str, data_dir_text: str, config_dir_text: str, day: str) -> dict:
    data_dir, config_dir = Path(data_dir_text), Path(config_dir_text)
    listing_index = load_listing_index(data_dir)
    listing = pd.DataFrame()
    if not listing_index.empty:
        # Read normalized fields without reparsing legacy variant workbooks.
        path = prices._paths_for_date(str(listing_index.iloc[-1]["日期"]), data_dir)[1]
        listing = pd.read_csv(path, encoding="utf-8-sig") if path.is_file() else pd.DataFrame()
    store_path = config_dir / "store_config.csv"
    result = build_catalog(read_source("operational_sales", data_dir), read_source("gross_profit", data_dir), listing,
                           pd.DataFrame(db_rows(data_dir, "SELECT sku, arrival_date FROM sku_first_shipments")),
                           read_source("sku_image_map", data_dir), read_local_table(store_path) if store_path.is_file() else pd.DataFrame(), date.fromisoformat(day))
    result["sources"] = {key: source_info(key, data_dir) for key in ("operational_sales", "gross_profit", "sales_volume_detail")}
    result["sources"]["listing"] = {"available": not listing_index.empty, "start": str(listing_index.iloc[0]["日期"]) if not listing_index.empty else None,
                                    "end": str(listing_index.iloc[-1]["日期"]) if not listing_index.empty else None}
    for key, columns, table in (("operational_sales", ["stock", "units_90", "capital_90", "launch_days"], result["facts"]), ("gross_profit", ["margin", "units", "sales", "profit", "ad_ratio"], result["markets"])):
        result["sources"][key]["missing_fields"] = {column: int(table[column].isna().sum()) for column in columns}
        result["sources"][key]["status"] = "missing" if not result["sources"][key]["available"] else "partial" if any(result["sources"][key]["missing_fields"].values()) else "complete"
    result["revision"] = revision
    return result


def catalog_data(data_dir: Path = DATA_DIR, config_dir: Path = CONFIG_DIR) -> dict:
    with LOCK:
        for _attempt in range(2):
            revision = catalog_revision(data_dir, config_dir)
            result = _catalog(revision, str(data_dir.resolve()), str(config_dir.resolve()), prices.business_day().isoformat())
            if catalog_revision(data_dir, config_dir) == revision:
                return result
        raise HTTPException(409, "数据源正在更新，请稍后刷新")


def queue_frame(base: dict, scene="clearance", developers="", search="", age_scope="90",
                margin_bands="negative,0-5,5-12,12-20", country="", min_sales=0,
                new_mode="low", sales_min=None, sales_max=None, sort_by="", sort_order="desc") -> pd.DataFrame:
    facts = base["facts"].copy()
    if developers:
        selected = set(developers.split(","))
        facts = facts.loc[facts["developer"].map(lambda text: bool(selected.intersection(text.split("；"))))]
    if search.strip():
        needle = search.strip().casefold()
        facts = facts.loc[facts.apply(lambda row: needle in (str(row["sku"]) + " " + str(row["product_name"]) + " " + " ".join(row["asins"])).casefold(), axis=1)]
    if scene == "clearance":
        if age_scope not in AGE_START:
            raise HTTPException(422, "未知库龄范围")
        facts = facts.loc[facts[f"action_stock_{age_scope}"].gt(0)].copy()
        facts["scope_stock"] = facts[f"action_stock_{age_scope}"]
        facts["scope_capital"] = facts[f"action_capital_{age_scope}"]
        default_keys, ascending = ["scope_capital", "sku"], [False, True]
    elif scene == "margin":
        markets = base["markets"]
        if country:
            markets = markets.loc[markets["country"].eq(country)]
        elif "missing" in margin_bands.split(",") or margin_bands == "all":
            missing = facts.loc[~facts["sku"].isin(markets["sku"]), ["sku"]].copy()
            markets = pd.concat([markets, missing.reindex(columns=markets.columns)], ignore_index=True)
        chinese = markets.rename(columns={"margin": "毛利率", "units": "销量"})
        chinese = chinese.assign(销量=chinese["销量"].fillna(0) if min_sales == 0 else chinese["销量"])
        try:
            matched = filter_margin(chinese, margin_bands, min_sales).rename(columns={"毛利率": "margin", "销量": "units"})
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        stats = matched.groupby("sku").agg(matched_markets=("country", "size"), matched_countries=("country", joined),
                    matched_margin=("margin", "min"), matched_sales=("sales", "sum"), matched_profit=("profit", "sum"), matched_units=("units", "sum"))
        for field, original in (("matched_sales", "sales"), ("matched_profit", "profit"), ("matched_units", "units")):
            values = markets.loc[matched.index].groupby("sku")[original].agg(lambda series: series.sum(min_count=len(series)))
            stats[field] = values
        stats["matched_markets"] = matched.groupby("sku")["country"].count()
        stats["small_sample_markets"] = matched.assign(small=markets.loc[matched.index, "units"].lt(5)).groupby("sku")["small"].sum()
        stats.index.name = None
        facts = facts.merge(stats, left_on="sku", right_index=True, how="inner")
        default_keys, ascending = ["matched_margin", "matched_profit", "sku"], [True, True, True]
    elif scene == "new":
        if new_mode not in {"low", "all"}:
            raise HTTPException(422, "未知新品视角")
        facts = facts.loc[facts["is_new"]].copy()
        if new_mode == "low":
            facts = facts.loc[facts["stock"].gt(0)]
        lower = sales_min
        upper = sales_max if sales_max is not None else (5 if new_mode == "low" and sales_min is None else None)
        if lower is not None and lower < 0 or upper is not None and upper < 0 or lower is not None and upper is not None and lower >= upper:
            raise HTTPException(422, "销量范围须非负且上限大于下限")
        if lower is not None:
            facts = facts.loc[facts["units_90"].ge(lower)]
        if upper is not None:
            facts = facts.loc[facts["units_90"].lt(upper)]
        default_keys, ascending = ["units_90", "launch_days", "sku"], [True, False, True]
    else:
        raise HTTPException(422, "未知诊断视角")
    if sort_by:
        allowed = {"sku", "stock", "capital_90", "units_90", "launch_days", "worst_margin", "scope_capital", "scope_stock", "matched_margin", "matched_profit"}
        if scene == "clearance":
            allowed.update({"clearance_daily_units", "clearance_available_days"})
        if sort_by not in allowed or sort_by not in facts:
            raise HTTPException(422, "未知排序字段")
        default_keys, ascending = [sort_by, *([] if sort_by == "sku" else ["sku"])], [sort_order == "asc", *([] if sort_by == "sku" else [True])]
    return facts.sort_values(default_keys, ascending=ascending, na_position="last", kind="stable")


def workbench_payload(base: dict, frame: pd.DataFrame, scene: str, page: int, page_size: int) -> dict:
    def total(column):
        if column not in frame:
            return None
        value = pd.to_numeric(frame[column], errors="coerce").sum(min_count=len(frame)) if len(frame) else 0
        return None if pd.isna(value) else float(value)
    return {"rows": prices._records(frame.iloc[(page-1)*page_size:page*page_size]), "total": len(frame), "page": page, "page_size": page_size,
            "scene": scene, "summary": {"sku_count": len(frame), "scope_stock": total("scope_stock"), "scope_capital": total("scope_capital"),
              "matched_profit": total("matched_profit"), "market_count": total("matched_markets"), "zero_sales": int(frame["units_90"].eq(0).sum()), "stock": total("stock")},
            "developers": sorted({name for names in base["facts"]["developer"] for name in names.split("；") if name}),
            "sources": base["sources"], "revision": base["revision"], "excluded_clearance_rows": base["excluded_clearance_rows"],
            "missing_launch_count": int(base["facts"]["launch_days"].isna().sum())}


@router.get("/workbench")
def workbench(scene: str = Query("clearance", pattern="^(clearance|margin|new)$"), developers: str = "", search: str = Query("", max_length=200),
              age_scope: str = Query("90", pattern="^(90|180|365)$"), margin_bands: str = "negative,0-5,5-12,12-20", country: str = Query("", pattern="^(|DE|FR|ES|IT)$"),
              min_sales: float = Query(0, ge=0), new_mode: str = Query("low", pattern="^(low|all)$"), sales_min: int | None = Query(None, ge=0), sales_max: int | None = Query(None, ge=0),
              sort_by: str = "", sort_order: str = Query("desc", pattern="^(asc|desc)$"), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    base = catalog_data()
    frame = queue_frame(base, scene, developers, search, age_scope, margin_bands, country, min_sales, new_mode, sales_min, sales_max, sort_by, sort_order)
    return workbench_payload(base, frame, scene, page, page_size)


class QueueFilters(BaseModel):
    revision: str | None = None
    scene: Literal["clearance", "margin", "new"] = "clearance"
    developers: str = ""
    search: str = Field("", max_length=200)
    age_scope: Literal["90", "180", "365"] = "90"
    margin_bands: str = "negative,0-5,5-12,12-20"
    country: Literal["", "DE", "FR", "ES", "IT"] = ""
    min_sales: float = Field(0, ge=0, allow_inf_nan=False)
    new_mode: Literal["low", "all"] = "low"
    sales_min: int | None = Field(None, ge=0)
    sales_max: int | None = Field(None, ge=0)
    sort_by: str = ""
    sort_order: Literal["asc", "desc"] = "desc"


class QueueExport(BaseModel):
    filters: QueueFilters = Field(default_factory=QueueFilters)
    selected_skus: list[str] | None = Field(None, max_length=5000)


@router.post("/export.csv")
def export_queue(payload: QueueExport):
    filters = payload.filters.model_dump()
    base = catalog_data()
    expected_revision = filters.pop("revision")
    if expected_revision is not None and expected_revision != base["revision"]:
        raise HTTPException(409, "数据已更新，请刷新并重新确认处理清单")
    frame = queue_frame(base, **filters)
    if payload.selected_skus is not None:
        frame = frame.loc[frame["sku"].isin({prices._normal_text(v) for v in payload.selected_skus})]
    columns = {"sku": "SKU", "product_name": "中文品名", "asins": "ASIN", "developer": "开发员", "stock": "可售库存", "capital_90": "90天以上占用资金（元）",
               "aged_stock_90": "90天以上库存", "units_90": "90天销量", "launch_days": "开售天数", "worst_margin": "最差站点毛利率（比例）",
               "scope_stock": "所选库龄库存", "scope_capital": "所选库龄占用资金（元）", "matched_markets": "命中站点数", "matched_countries": "命中国家", "matched_margin": "命中最差毛利率（比例）",
               "matched_sales": "命中销售额（元）", "matched_profit": "命中毛利润（元）", "small_sample_markets": "小样本站点数", "is_aged": "有积压库存", "is_low_margin": "有低毛利站点", "is_new": "是否新品", "is_low_sales_new": "新品低销"}
    if filters.get("scene", "clearance") == "clearance":
        columns.update({"clearance_daily_units": "日均销量（补货口径，单/天）", "clearance_available_days": "可售天数（补货口径，天）", "clearance_total_stock": "补货口径总库存（件）"})
    output = frame.reindex(columns=[c for c in columns if c in frame]).copy()
    output["asins"] = output["asins"].map(lambda values: "；".join(values))
    markets = base["markets"].loc[base["markets"]["sku"].isin(frame["sku"])]
    for country_code in COUNTRIES:
        scoped = markets.loc[markets["country"].eq(country_code)]
        for key, label in (("margin", "毛利率（比例）"), ("units", "销量"), ("sales", "销售额（元）"), ("profit", "毛利润（元）"), ("ad_ratio", "广告费占比（比例）"), ("current_price", "实际价格"), ("currency", "币种"), ("rating", "评分")):
            # Multiple ASIN identities remain explicit, never averaged into a fictitious price.
            known = scoped.loc[scoped[key].notna()]
            labels = known["asin"].astype(str) + ":" + known[key].astype(str)
            values = labels.groupby(known["sku"], sort=False).agg("；".join).to_dict()
            output[country_code + label] = output["sku"].map(values)
    output = output.rename(columns=columns)
    for key, label in (("operational_sales", "库存快照"), ("gross_profit", "毛利周期"), ("listing", "价格快照")):
        source = base["sources"].get(key, {})
        output[label] = "～".join(str(source.get(field) or "") for field in ("start", "end")) if source.get("end") else source.get("uploaded_at")
    return Response(output.to_csv(index=False).encode("utf-8-sig"), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="sku-diagnosis.csv"'})


@router.get("/skus/{sku}")
def sku_detail(sku: str):
    key = prices._normal_text(sku)
    base = catalog_data()
    matched = base["facts"].loc[base["facts"]["sku"].eq(key)]
    markets = base["markets"].loc[base["markets"]["sku"].eq(key)].copy()
    events = prices._event_frame(DATA_DIR)
    events = events.loc[events["sku"].eq(key)]
    if matched.empty and markets.empty and events.empty:
        raise HTTPException(404, "当前数据中未找到此SKU")
    identity = prices._records(matched)[0] if not matched.empty else {**dict.fromkeys(base["facts"].columns), "sku": key, "product_name": "", "asins": [], "developer": "", "image": None,
                                                                 "is_aged": False, "is_low_margin": False, "is_new": False, "is_low_sales_new": False}
    identity["asins"] = sorted(set(identity["asins"]) | set(markets["asin"]) | set(events["asin"]))
    known_markets = set(zip(markets["asin"], markets["country"]))
    markets["historical_only"] = False
    archived = []
    for row in events.sort_values("date").drop_duplicates(["asin", "country"], keep="last").to_dict("records"):
        if (row["asin"], row["country"]) not in known_markets:
            archived.append({**dict.fromkeys(markets.columns), "sku": key, "asin": row["asin"], "country": row["country"], "currency": row.get("currency"), "historical_only": True})
    if archived:
        markets = pd.concat([markets, pd.DataFrame(archived)], ignore_index=True)
    history = []
    for table, kind in (("price_adjustments", "长期调价"), ("sku_promotions", "限时促销"), ("sku_last_promotions", "最近登记快照")):
        for row in db_rows(DATA_DIR, f"SELECT * FROM {table}"):
            if prices._normal_text(row.get("sku")) == key:
                history.append({**row, "kind": kind})
    history.sort(key=lambda r: str(r.get("created_at", r.get("updated_at", ""))), reverse=True)
    segments = [{"label": label, "stock": identity.get(f"age_stock_{i}"), "capital": identity.get(f"age_capital_{i}")} for i, label in enumerate(AGE_LABELS)]
    capital = [identity.get(f"age_capital_{i}") for i in range(5)]
    provision = None if any(v is None for v in capital) else capital[0]*.05 + (capital[1]+capital[2])*.08 + (capital[3]+capital[4])*.12
    discard = None if identity.get("aged_stock_90") is None or identity.get("capital_90") is None else identity["aged_stock_90"]*6 + identity["capital_90"]*1.5
    discard_reference = {}
    for scope in AGE_START:
        stock, funds = identity.get(f"action_stock_{scope}"), identity.get(f"action_capital_{scope}")
        discard_reference[scope] = None if stock is None or funds is None else stock*6 + funds*1.5
    return {"identity": identity, "markets": prices._records(markets), "aging": segments, "provision": provision, "discard_90": discard,
            "discard_reference": discard_reference, "records": history, "sources": base["sources"], "revision": base["revision"]}


@lru_cache(maxsize=24)
def _sku_series(revision: str, sku: str, asin: str, country: str, days: int, day: str, data_dir_text: str) -> dict:
    del revision
    data_dir = Path(data_dir_text)
    index = load_listing_index(data_dir)
    today = date.fromisoformat(day)
    latest_info = source_info("sales_volume_detail", data_dir)
    latest_reference = date.fromisoformat(latest_info["end"] or str(latest_info["uploaded_at"] or day)[:10])
    sales_end = min(latest_reference, today - timedelta(days=1))
    price_end = date.fromisoformat(str(index.iloc[-1]["日期"])) if not index.empty else sales_end
    end = max(sales_end, price_end)
    start = end - timedelta(days=days-1)
    units: dict[str, float | None] = {}
    observed: dict[str, float | None] = {}

    def select_sales(frame: pd.DataFrame, reference: date):
        aliases = {str(c).strip().casefold(): c for c in frame.columns}
        keys = [aliases.get("msku"), aliases.get("asin"), aliases.get("国家") or aliases.get("country")]
        if not all(keys):
            return
        mask = frame[keys[0]].map(prices._normal_text).eq(sku) & frame[keys[1]].map(prices._normal_text).eq(asin)
        mask &= frame[keys[2]].map(lambda v: COUNTRY_MAP.get(prices._normal_text(v), prices._normal_text(v))).eq(country)
        selected = prices._dated_sales(frame.loc[mask], reference)
        if not selected.empty:
            row = selected.iloc[0]
            for column in selected.columns:
                if column not in prices.KEYS and start.isoformat() <= column <= sales_end.isoformat():
                    if pd.notna(row[column]) or column not in units:
                        units[column] = None if pd.isna(row[column]) else float(row[column])

    for source in get_sales_history_paths(data_dir):
        if start.strftime("%Y-%m") <= source.stem <= end.strftime("%Y-%m"):
            select_sales(read_local_table(source), (pd.Timestamp(source.stem)+pd.offsets.MonthEnd()).date())
    latest_path = get_latest_source_path("sales_volume_detail", data_dir)
    if latest_path:
        select_sales(read_local_table(latest_path), latest_reference)
    for text in index["日期"].astype(str):
        if start.isoformat() <= text <= end.isoformat():
            snapshot = prices._price_snapshot(text, data_dir)
            selected = snapshot.loc[snapshot["MSKU"].map(prices._normal_text).eq(sku) & snapshot["ASIN"].map(prices._normal_text).eq(asin) & snapshot["国家"].eq(country)]
            if not selected.empty:
                value = pd.to_numeric(pd.Series([selected.iloc[0]["当前实际总价"]]), errors="coerce").iloc[0]
                observed[text] = None if pd.isna(value) else float(value)
    events = prices._event_frame(data_dir)
    for key, value in zip(prices.KEYS, (sku, asin, country)):
        events = events.loc[events[key].eq(value)]
    events = events.loc[events["date"].between(start.isoformat(), end.isoformat())].copy()
    if not events.empty:
        events["change"] = pd.to_numeric(events["new_effective_price"]) / pd.to_numeric(events["old_effective_price"]) - 1
        events["observation"] = events["gap_days"].map(lambda value: f"间隔{int(value)}天，首次观察到" if value > 1 else "相邻日快照")
    event_dates = set(events["date"])
    rows = []
    for offset in range(days):
        text = (start + timedelta(days=offset)).isoformat()
        rows.append({"date": text, "units": units.get(text), "price": observed.get(text), "event": text in event_dates})
    return {"rows": rows, "events": prices._records(events.sort_values("date", ascending=False)), "sales_as_of": sales_end.isoformat(), "days": days}


@router.get("/skus/{sku}/series")
def sku_series(sku: str, asin: str = Query(..., min_length=1, max_length=200), country: str = Query(..., pattern="^(DE|FR|ES|IT)$"), days: int = Query(30)):
    if days not in {30, 90, 180}:
        raise HTTPException(422, "时间范围只能是30、90或180天")
    return _sku_series(prices._signature(DATA_DIR), prices._normal_text(sku), prices._normal_text(asin), country, days,
                       prices.business_day().isoformat(), str(DATA_DIR.resolve()))


def price_frame(direction="up", developers="", country="", band=None, date_start=None, date_end=None, search="", trend="all", sort_by="abs_t", sort_order="desc"):
    base = prices.base_data()
    catalog = catalog_data()
    # Financial volume is usable only for the same marketplace and exact window dates.
    enriched = base["frame"].copy()
    gross_period = catalog["sources"].get("gross_profit", {})
    if base["as_of"]:
        cutoff = date.fromisoformat(base["as_of"])
        markets = catalog["markets"].set_index(prices.KEYS)
        volumes = markets["units"].reindex(pd.MultiIndex.from_frame(enriched[prices.KEYS])).to_numpy()
        changed = False
        for window in (7, 30):
            if gross_period.get("start") == (cutoff - timedelta(days=window-1)).isoformat() and gross_period.get("end") == cutoff.isoformat():
                candidate = pd.Series(volumes, index=enriched.index)
                fill = enriched[f"units_{window}"].isna() & candidate.ge(0) & candidate.lt(float("inf")) & enriched["date"].le(base["as_of"])
                enriched.loc[fill, f"units_{window}"] = candidate.loc[fill]
                enriched.loc[fill, f"units_{window}_source"] = f"毛利原始表（同{window}天周期）"
                changed |= bool(fill.any())
        if changed:
            enriched["t_value"] = enriched["units_7"] / 7 - enriched["units_30"] / 30
            enriched.loc[enriched["date"].gt(base["as_of"]), "t_value"] = None
            enriched["abs_t"] = enriched["t_value"].abs()
            enriched["trend"] = enriched["t_value"].map(lambda value: "missing" if pd.isna(value) else "up" if value > 0 else "down" if value < 0 else "flat")
    base = {**base, "frame": enriched}
    frame = prices.filtered(base, direction, "", country, None, date_start, date_end, "", trend, sort_by, sort_order).copy()
    names = catalog["facts"].set_index("sku")
    frame["developer"] = frame["sku"].map(names["developer"]).fillna(frame["developer"])
    if developers:
        selected = set(developers.split(","))
        frame = frame.loc[frame["developer"].map(lambda text: bool(selected.intersection(text.split("；"))))]
    frame["product_name"] = frame["sku"].map(names["product_name"]).fillna("")
    for window in (7, 30):
        frame[f"sku_units_{window}"] = frame["sku"].map(names[f"units_{window}"])
    frame["sku_t_value"] = frame["sku_units_7"] / 7 - frame["sku_units_30"] / 30
    frame["sku_sales_source"] = None
    frame.loc[frame[["sku_units_7", "sku_units_30"]].notna().any(axis=1), "sku_sales_source"] = "运营原始表（SKU跨国汇总）"
    frame["sku_sales_snapshot"] = catalog["sources"].get("operational_sales", {}).get("uploaded_at")
    for field in ("is_aged", "is_low_margin", "is_low_sales_new"):
        frame[field] = frame["sku"].map(names[field]).fillna(False).astype(bool)
    if search.strip():
        needle = search.strip().casefold()
        frame = frame.loc[(frame["sku"] + " " + frame["asin"] + " " + frame["product_name"]).str.casefold().str.contains(needle, regex=False)]
    distribution = frame
    if band is not None:
        frame = frame.loc[frame["band"].eq(band)]
    return base, catalog, frame, distribution


@router.get("/prices")
def tracking(direction: str = Query("up", pattern="^(up|down)$"), developers: str = "", country: str = Query("", pattern="^(|DE|FR|ES|IT)$"),
             band: int | None = Query(None, ge=0), date_start: str | None = None, date_end: str | None = None, search: str = Query("", max_length=200),
             trend: str = Query("all", pattern="^(all|up|down|flat|missing)$"), sort_by: str = "abs_t", sort_order: str = Query("desc", pattern="^(asc|desc)$"),
             page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=200)):
    base, catalog, frame, distribution = price_frame(direction, developers, country, band, date_start, date_end, search, trend, sort_by, sort_order)
    buckets = []
    for lower, group in distribution.groupby("band", sort=True):
        valid = group["t_value"].dropna()
        counts = group["trend"].value_counts()
        buckets.append({"band": int(lower), "count": len(group), "mean_t": float(valid.mean()) if len(valid) else None,
                        **{kind: int(counts.get(kind, 0)) for kind in ("up", "down", "flat", "missing")}})
    sources = {key: dict(value) for key, value in catalog["sources"].items()}
    sales_source = sources["sales_volume_detail"]
    missing_trends = int(base["frame"]["t_value"].isna().sum())
    sales_source.update(status="missing" if not sales_source["available"] else "partial" if missing_trends else "complete", missing_trends=missing_trends)
    return {"rows": prices._records(frame.iloc[(page-1)*page_size:page*page_size]), "total": len(frame), "page": page, "page_size": page_size,
            "buckets": buckets, "distribution_total": len(distribution), "metrics": {"sku_count": frame["sku"].nunique(), "records": len(frame),
               "up": int(frame["t_value"].gt(0).sum()), "down": int(frame["t_value"].lt(0).sum()), "missing": int(frame["t_value"].isna().sum()),
               "sku_reference": int((frame["t_value"].isna() & frame["sku_t_value"].notna()).sum())},
            "as_of": base["as_of"], "coverage": base["coverage"], "developers": sorted(set(base["developers"]) | {name for text in catalog["facts"]["developer"] for name in text.split("；") if name}),
            "sources": sources, "warnings": base["warnings"]}


@router.get("/prices/export.csv")
def export_tracking(direction: str = Query("up", pattern="^(up|down)$"), developers: str = "", country: str = Query("", pattern="^(|DE|FR|ES|IT)$"),
                    band: int | None = Query(None, ge=0), date_start: str | None = None, date_end: str | None = None, search: str = Query("", max_length=200),
                    trend: str = Query("all", pattern="^(all|up|down|flat|missing)$"), sort_by: str = "abs_t", sort_order: str = Query("desc", pattern="^(asc|desc)$")):
    base, _, frame, _ = price_frame(direction, developers, country, band, date_start, date_end, search, trend, sort_by, sort_order)
    names = {"sku": "SKU", "product_name": "中文品名", "asin": "ASIN", "country": "国家", "date": "观察日期", "developer": "开发员",
             "old_effective_price": "前实际价", "new_effective_price": "后实际价", "currency": "币种", "change": "涨跌幅（比例）", "units_7": "站点7天销量", "units_30": "站点30天销量", "t_value": "站点T值（件每天）",
             "units_7_source": "站点7天销量来源", "units_30_source": "站点30天销量来源", "sku_units_7": "SKU汇总参考7天销量", "sku_units_30": "SKU汇总参考30天销量", "sku_t_value": "SKU汇总参考T值（不计入站点排名）", "sku_sales_source": "SKU参考来源", "sku_sales_snapshot": "SKU参考上传快照", "observation": "观察提示"}
    output = frame.reindex(columns=list(names)).rename(columns=names)
    output["销量截止日"] = base["as_of"]
    return Response(output.to_csv(index=False).encode("utf-8-sig"), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="price-tracking-{direction}.csv"'})
