"""Independent, append-only adjustments. Legacy migration is an explicit operator action."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from backend import db
from dashboard.promotions import normalize_promotion_sku

router = APIRouter(prefix="/api/pricing", tags=["pricing"])
MIGRATION = "2026-09-separate-price-adjustments-v1"
LEGACY = {"-26日均<0.5单,直接降价10%": (388, "2026-08-18"), "90天库存,日均<2单,-10%": (230, "2026-08-26")}
ADJUSTMENT_COLUMNS = ["调价生效日期", "本次调价降幅", "累计调价降幅"]


def today_text():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(conn):
    # Do not use executescript: all DDL participates in the caller's transaction.
    conn.execute("""CREATE TABLE IF NOT EXISTS price_adjustments (
        id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, batch_name TEXT NOT NULL, sku TEXT NOT NULL,
        discount_percent INTEGER NOT NULL CHECK(discount_percent BETWEEN 1 AND 99),
        effective_date TEXT NOT NULL, created_at TEXT NOT NULL, migration_source TEXT,
        voided_at TEXT, void_reason TEXT, UNIQUE(batch_id,sku))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_adjustments_sku ON price_adjustments(sku,effective_date)")
    conn.execute("""CREATE TABLE IF NOT EXISTS pricing_requests (
        request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, batch_id TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS pricing_audit (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, source_id TEXT NOT NULL,
        payload TEXT NOT NULL, recorded_at TEXT NOT NULL, migration_key TEXT)""")
    if "activity_id" not in {r[1] for r in conn.execute("PRAGMA table_info(sku_promotions)")}:
        conn.execute("ALTER TABLE sku_promotions ADD COLUMN activity_id TEXT NOT NULL DEFAULT ''")


def audit(conn, kind, row, migration_key=None):
    row = dict(row)
    conn.execute("INSERT INTO pricing_audit(kind,source_id,payload,recorded_at,migration_key) VALUES(?,?,?,?,?)",
                 (kind, row.get("id") or row.get("promotion_id") or row.get("sku", ""),
                  json.dumps(row, ensure_ascii=False, sort_keys=True), timestamp(), migration_key))


def migrate_legacy(path: Path, backup_path: Path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if conn.execute("SELECT 1 FROM app_migrations WHERE migration_key=?", (MIGRATION,)).fetchone():
            return {"already_applied": True}
        if backup_path.exists():
            raise ValueError("备份文件已存在，请使用新的备份路径")
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(backup_path)) as backup:
            conn.backup(backup)
        conn.execute("BEGIN IMMEDIATE")
        rows = [dict(r) for r in conn.execute("SELECT * FROM sku_promotions")]
        snapshots = [dict(r) for r in conn.execute("SELECT * FROM sku_last_promotions")]
        for name, (count, start) in LEGACY.items():
            group = [r for r in rows if r["promotion_name"] == name]
            if len(group) != count or any(r["start_date"] != start or r["end_date"] is not None or r["discount_percent"] != 10 for r in group):
                raise ValueError(f"迁移清单发生变化：{name}")
        permanent = [r for r in rows if r["promotion_name"] in LEGACY]
        permanent_skus = {normalize_promotion_sku(r["sku"]) for r in permanent}
        if len(permanent_skus) != 618:
            raise ValueError("长期调价 SKU 数量或重复情况不符合清单")
        timed = [r for r in rows if r["promotion_name"] not in LEGACY]
        counts = {}
        for r in timed:
            key = (r["promotion_name"], r["start_date"], r["end_date"], r["discount_percent"])
            counts[key] = counts.get(key, 0) + 1
        if counts != {("-26新品","2026-07-28","2026-08-10",10):170, ("-26新品","2026-08-11","2026-08-31",10):123}:
            raise ValueError("发现新活动或无法归类的数据，原数据已保留，请重新确认清单")
        for r in snapshots:
            if r["promotion_name"] in LEGACY and (r["start_date"] != LEGACY[r["promotion_name"]][1] or r["discount_percent"] != 10 or r["end_date"] is not None or normalize_promotion_sku(r["sku"]) not in permanent_skus):
                raise ValueError("长期调价快照与清单不一致")
        ensure_schema(conn)
        for row in rows:
            audit(conn, "legacy_activity", row, MIGRATION)
        for row in snapshots:
            audit(conn, "legacy_snapshot", row, MIGRATION)
        for r in permanent:
            batch_key = json.dumps(
                [r["promotion_name"], r["start_date"], r["discount_percent"]],
                ensure_ascii=False,
            )
            batch = str(uuid.uuid5(uuid.NAMESPACE_URL, MIGRATION + batch_key))
            conn.execute("""INSERT INTO price_adjustments
                (id,batch_id,batch_name,sku,discount_percent,effective_date,created_at,migration_source)
                VALUES(?,?,?,?,?,?,?,?)""", (str(uuid.uuid5(uuid.NAMESPACE_URL, MIGRATION+r["id"])),
                batch,r["promotion_name"],normalize_promotion_sku(r["sku"]),10,r["start_date"],r["created_at"],r["id"]))
            conn.execute("DELETE FROM sku_promotions WHERE id=?", (r["id"],))
        last = {}
        for r in timed:
            key = json.dumps([r[k] for k in ("promotion_name","start_date","end_date","discount_percent")])
            conn.execute("UPDATE sku_promotions SET activity_id=? WHERE id=?",
                         (str(uuid.uuid5(uuid.NAMESPACE_URL, MIGRATION+key)),r["id"]))
            snapshot = {k:r[k] for k in ("sku","promotion_name","discount_percent","start_date","end_date","updated_at")}
            snapshot["promotion_id"] = r["id"]
            last[r["sku"]] = max([last.get(r["sku"],snapshot),snapshot],key=lambda x:(x["updated_at"],x["promotion_id"]))
        for r in snapshots:
            if r["promotion_name"] not in LEGACY:
                last[r["sku"]] = r  # registration snapshot wins over later activity edits
        conn.execute("DELETE FROM sku_last_promotions")
        for r in last.values():
            conn.execute("""INSERT INTO sku_last_promotions
                (sku,promotion_id,promotion_name,discount_percent,start_date,end_date,updated_at)
                VALUES(?,?,?,?,?,?,?)""", tuple(r[k] for k in ("sku","promotion_id","promotion_name","discount_percent","start_date","end_date","updated_at")))
        conn.execute("INSERT INTO app_migrations VALUES(?,?)", (MIGRATION,timestamp()))
        conn.commit()
        return {"adjustments":618,"timed_records":293,"snapshots":len(last),"archived_snapshots":len(snapshots),"backup":str(backup_path)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def adjustment_state(conn, reference=None):
    groups = {}
    for r in conn.execute("SELECT * FROM price_adjustments WHERE voided_at IS NULL AND effective_date<=? ORDER BY effective_date,created_at,id", (reference or today_text(),)):
        groups.setdefault(r["sku"],[]).append(dict(r))
    return {sku:{"sku":sku,"effective_date":rows[-1]["effective_date"],"discount_percent":rows[-1]["discount_percent"],
                 "cumulative_discount":100*(1-math.prod(1-r["discount_percent"]/100 for r in rows))}
            for sku,rows in groups.items()}


def adjustment_batches(conn):
    states = adjustment_state(conn)
    grouped = {}
    for raw in conn.execute(
        "SELECT * FROM price_adjustments ORDER BY effective_date DESC, created_at DESC, id DESC"
    ):
        row = dict(raw)
        batch = grouped.setdefault(
            row["batch_id"],
            {
                "batch_id": row["batch_id"],
                "batch_name": row["batch_name"],
                "effective_date": row["effective_date"],
                "discount_percent": row["discount_percent"],
                "events": [],
            },
        )
        row["cumulative_discount"] = states.get(row["sku"], {}).get("cumulative_discount")
        row["status"] = (
            "voided" if row["voided_at"]
            else "pending" if row["effective_date"] > today_text()
            else "active"
        )
        batch["events"].append(row)
    result = []
    for batch in grouped.values():
        events = batch["events"]
        batch["sku_count"] = len({row["sku"] for row in events})
        batch["active_sku_count"] = len({row["sku"] for row in events if row["status"] == "active"})
        batch["voided_sku_count"] = len({row["sku"] for row in events if row["status"] == "voided"})
        statuses = {row["status"] for row in events}
        batch["status"] = (
            "active" if "active" in statuses
            else "pending" if "pending" in statuses
            else "voided"
        )
        result.append(batch)
    return result


def merge_adjustments(frame, sku_column="SKU"):
    result = frame.copy()
    try:
        with db.connect() as conn:
            states = adjustment_state(conn)
    except sqlite3.OperationalError:
        states = {}
    keys = result[sku_column].map(normalize_promotion_sku) if sku_column in result else pd.Series("",index=result.index)
    for target,field in zip(ADJUSTMENT_COLUMNS,("effective_date","discount_percent","cumulative_discount")):
        result[target] = keys.map(lambda sku:states.get(sku,{}).get(field))
    return result


class AdjustmentInput(BaseModel):
    request_id: str = Field(min_length=8,max_length=100)
    batch_name: str = Field(min_length=1,max_length=100)
    skus: list[str] = Field(min_length=1,max_length=5000)
    discount_percent: int = Field(ge=1,le=99,strict=True)
    effective_date: date

    @field_validator("batch_name")
    @classmethod
    def name(cls,value):
        if not value.strip():
            raise ValueError("请输入调价批次名称")
        return value.strip()

    @field_validator("skus")
    @classmethod
    def skus_normalized(cls,values):
        result = list(dict.fromkeys(normalize_promotion_sku(v) for v in values))
        if any(not v or len(v)>200 for v in result):
            raise ValueError("SKU不能为空或超过200字符")
        return result


@router.post("/adjustments/preview")
def preview_adjustment(payload: AdjustmentInput):
    with db.connect() as conn:
        current = adjustment_state(conn)
        effective = adjustment_state(conn, payload.effective_date.isoformat())
    try:
        from backend.listing_prices import latest_listing_wide
        listing = latest_listing_wide()
        listing_map = listing.set_index("MSKU").to_dict("index") if not listing.empty else {}
    except Exception:
        listing_map = {}
    rows = []
    for sku in payload.skus:
        row = {
            "sku": sku,
            "current": current.get(sku, {}).get("cumulative_discount", 0),
            "before": effective.get(sku, {}).get("cumulative_discount", 0),
            "after": 100 - (100 - effective.get(sku, {}).get("cumulative_discount", 0)) * (1 - payload.discount_percent / 100),
        }
        source = listing_map.get(sku, {})
        row["actual_prices"] = {
            code: {
                "launch_price": source.get(f"{code}_开售价"),
                "current_price": source.get(f"{code}_当前实际总价"),
                "estimated_after_price": (
                    float(source[f"{code}_当前实际总价"]) * (1 - payload.discount_percent / 100)
                    if source.get(f"{code}_当前实际总价") is not None else None
                ),
            }
            for code in ("DE", "FR", "ES", "IT")
        }
        rows.append(row)
    return {"rows": rows}


@router.post("/adjustments",status_code=201)
def create_adjustment(payload: AdjustmentInput):
    digest = hashlib.sha256(json.dumps(payload.model_dump(mode="json"),sort_keys=True).encode()).hexdigest()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute("SELECT * FROM pricing_requests WHERE request_id=?", (payload.request_id,)).fetchone()
        if old:
            if old["payload_hash"] != digest:
                raise HTTPException(409,"该提交标识已用于不同内容，请重新预览")
            return {"batch_id":old["batch_id"],"replayed":True}
        batch = str(uuid.uuid4())
        conn.execute("INSERT INTO pricing_requests VALUES(?,?,?)", (payload.request_id,digest,batch))
        for sku in payload.skus:
            conn.execute("""INSERT INTO price_adjustments(id,batch_id,batch_name,sku,discount_percent,effective_date,created_at)
                VALUES(?,?,?,?,?,?,?)""",(str(uuid.uuid4()),batch,payload.batch_name,sku,payload.discount_percent,payload.effective_date.isoformat(),timestamp()))
    return {"batch_id":batch,"replayed":False}


class VoidInput(BaseModel):
    reason: str = Field(min_length=1,max_length=500)


@router.post("/adjustments/{event_id}/void")
def void_adjustment(event_id: str,payload: VoidInput):
    if not payload.reason.strip():
        raise HTTPException(422,"请输入作废原因")
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM price_adjustments WHERE id=?", (event_id,)).fetchone():
            raise HTTPException(404,"调价记录不存在")
        conn.execute("UPDATE price_adjustments SET voided_at=?,void_reason=? WHERE id=? AND voided_at IS NULL",
                     (timestamp(),payload.reason.strip(),event_id))
    return {"voided":event_id}


@router.get("/history")
def history(sku: str = ""):
    needle = normalize_promotion_sku(sku)
    with db.connect() as conn:
        states = adjustment_state(conn)
        events = [dict(r) for r in conn.execute("SELECT * FROM price_adjustments")]
        promos = [dict(r) for r in conn.execute("SELECT * FROM sku_promotions")]
        snapshots = [dict(r) for r in conn.execute("SELECT * FROM sku_last_promotions")]
        archived = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM pricing_audit WHERE kind IN ('deleted_promotion','legacy_snapshot','registered_promotion')")]
    rows = []
    for r in events:
        r.update(type="adjustment",name=r["batch_name"],start_date=r["effective_date"],end_date=None,
                 status="voided" if r["voided_at"] else "pending" if r["effective_date"]>today_text() else "active",
                 cumulative_discount=states.get(r["sku"],{}).get("cumulative_discount",0))
        rows.append(r)
    seen = set()
    for r in promos:
        seen.add(r["id"])
        r.update(type="promotion",name=r["promotion_name"],status="pending" if r["start_date"]>today_text() else "ended" if r["end_date"] and r["end_date"]<today_text() else "active")
        rows.append(r)
    for r in snapshots+archived:
        key = r.get("promotion_id") or r.get("id")
        if key in seen or r["promotion_name"] in LEGACY:
            continue
        seen.add(key)
        r.update(id=key,type="snapshot",name=r["promotion_name"],status="historical")
        rows.append(r)
    return {"rows":sorted([r for r in rows if not needle or needle in r["sku"]],
                          key=lambda r:(r["start_date"],r.get("created_at",r.get("updated_at",""))),reverse=True)}


@router.get("/adjustment-batches")
def list_adjustment_batches():
    with db.connect() as conn:
        return {"rows": adjustment_batches(conn)}
