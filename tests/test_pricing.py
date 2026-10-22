from __future__ import annotations

from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import db, pricing, promotions, dashboard_api


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "app.db"
        self.dbpatch = patch.object(db, "DB_PATH", self.path)
        self.dbpatch.start()
        db.initialize_database()
        app = FastAPI()
        app.include_router(pricing.router)
        app.include_router(promotions.router)
        self.client = TestClient(app)
        metrics = pd.DataFrame([dict(sku="SKU-A", asin="A", developer="甲", available_inventory=20,
                                    sales_90d=1, aged_inventory_90d=10, average_7d=2, average_30d=1, daily_lift=1)])
        self.metricspatch = patch.object(promotions, "_metrics_or_empty", return_value=metrics)
        self.metricspatch.start()
        self.todaypatch = patch.object(pricing, "today_text", return_value="2026-09-15")
        self.todaypatch.start()
        self.promoday = patch.object(promotions, "today", return_value=pricing.date(2026,9,15))
        self.promoday.start()

    def tearDown(self):
        self.promoday.stop()
        self.todaypatch.stop()
        self.metricspatch.stop()
        self.dbpatch.stop()
        self.temp.cleanup()

    def adjust(self, key="request-1", start="2026-09-01", skus=None):
        return self.client.post("/api/pricing/adjustments", json={
            "request_id":key, "batch_name":"调价", "skus":skus or ["SKU-A"],
            "discount_percent":10, "effective_date":start})

    def promo(self, start="2026-09-10", end="2026-09-20", name="活动", skus=None):
        return self.client.post("/api/promotions/manual", json={
            "promotion_name":name,"skus":skus or ["SKU-A"],"discount_percent":10,
            "start_date":start,"end_date":end})

    def states(self, reference=None):
        with db.connect() as conn:
            return pricing.adjustment_state(conn,reference)

    def test_compound_and_deduplicated_overview(self):
        self.assertEqual(self.adjust().status_code,201)
        self.assertEqual(self.promo().status_code,201)
        self.assertAlmostEqual(self.states()["SKU-A"]["cumulative_discount"],10)
        overview = self.client.get("/api/promotions/overview").json()
        self.assertEqual([overview[k] for k in ("adjusted_sku_count","active_sku_count","overlap_sku_count","overall_sku_count")],[1,1,1,1])
        self.assertEqual(overview["average_7d_total"],2)
        self.assertEqual(self.adjust("request-2").status_code,201)
        self.assertAlmostEqual(self.states()["SKU-A"]["cumulative_discount"],19)
        self.assertAlmostEqual(100-(100-10)*.9,19)

    def test_future_void_and_idempotency(self):
        self.adjust()
        first=self.adjust().json()
        self.assertTrue(first["replayed"])
        self.adjust("future-request","2027-01-01")
        self.assertAlmostEqual(self.states()["SKU-A"]["cumulative_discount"],10)
        self.assertAlmostEqual(self.states("2027-01-01")["SKU-A"]["cumulative_discount"],19)
        rows=self.client.get("/api/pricing/history").json()["rows"]
        self.assertEqual(len(rows),2)
        current=next(r for r in rows if r["status"]=="active")
        response=self.client.post("/api/pricing/adjustments/"+current["id"]+"/void",json={"reason":"误登记"})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.states(),{})
        self.assertEqual(self.client.get("/api/pricing/history").json()["rows"][1]["status"],"voided")
        self.assertEqual(self.adjust("request-1","2026-08-01").status_code,409)

    def test_preview_normalization_and_matrix_csv_precision(self):
        self.adjust(skus=[" ＳＫＵ-A ","SKU-A"])
        payload={"request_id":"preview-1","batch_name":"再次降价","skus":["SKU-A"],"discount_percent":10,"effective_date":"2026-09-15"}
        preview=self.client.post("/api/pricing/adjustments/preview",json=payload).json()["rows"][0]
        self.assertAlmostEqual(preview["current"],10)
        self.assertAlmostEqual(preview["after"],19)
        frame=pd.DataFrame({"SKU":["SKU-A","sku-a","SKU-A"],"日均销量":[.12345,0,2],"可售天数":[.123456789,None,3]})
        merged=pricing.merge_adjustments(frame)
        self.assertEqual(merged["SKU"].tolist(),frame["SKU"].tolist())
        self.assertTrue(pd.isna(merged.loc[1,"累计调价降幅"]))
        self.assertEqual(merged["日均销量"].tolist(),frame["日均销量"].tolist())
        exported=dashboard_api._slow_moving_csv_frame({})(merged)
        self.assertEqual(exported.loc[0,"可售天数（天）"],.123456789)
        self.assertIn("累计调价降幅（%）",exported)
        self.assertEqual(len(pricing.merge_adjustments(frame.iloc[:0])),0)

    def test_timed_overlap_stable_ids_and_snapshot_immutable(self):
        one=self.promo().json()["created"][0]
        self.assertEqual(self.promo().status_code,409)
        future=self.promo("2026-10-01","2026-10-02").json()["created"][0]
        self.assertNotEqual(one["activity_id"],future["activity_id"])
        self.assertEqual(self.promo(end=None).status_code,422)
        self.assertEqual(self.promo("2026-09-20","2026-09-21").status_code,409)
        self.client.put("/api/promotions/"+future["id"],json={"promotion_name":"改名","start_date":"2026-10-02","end_date":"2026-10-03"})
        snap=self.client.get("/api/promotions/last-promotions").json()["rows"][0]
        self.assertEqual(snap["start_date"],"2026-10-01")
        self.assertEqual(snap["promotion_name"],"活动")
        removed=self.client.request("DELETE","/api/promotions/activities",json={"activity_id":future["activity_id"]})
        self.assertEqual(removed.json()["deleted"],1)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sku_promotions").fetchone()[0],1)
        self.assertEqual(self.client.get("/api/promotions/last-promotions").json()["rows"][0],snap)
        overview=self.client.get("/api/promotions/overview").json()
        self.assertEqual(overview["active_sku_count"],1)

    def test_expiry_does_not_remove_adjustment(self):
        self.adjust()
        self.promo("2026-09-01","2026-09-14")
        overview=self.client.get("/api/promotions/overview").json()
        self.assertEqual(overview["adjusted_sku_count"],1)
        self.assertEqual(overview["active_sku_count"],0)
        self.assertTrue(any(r["type"] == "promotion" and r["status"] == "ended" for r in self.client.get("/api/pricing/history").json()["rows"]))

    def test_revision_changes_on_register_and_void(self):
        before=promotions.promotion_revision()
        self.adjust()
        after=promotions.promotion_revision()
        self.assertNotEqual(before,after)
        event=self.client.get("/api/pricing/history").json()["rows"][0]
        self.client.post("/api/pricing/adjustments/"+event["id"]+"/void",json={"reason":"测试"})
        self.assertNotEqual(after,promotions.promotion_revision())

    def seed_legacy(self):
        groups=[(name,count,start,None) for name,(count,start) in pricing.LEGACY.items()]
        groups += [("-26新品",170,"2026-07-28","2026-08-10"),("-26新品",123,"2026-08-11","2026-08-31")]
        with db.connect() as conn:
            for group,(name,count,start,end) in enumerate(groups):
                for i in range(count):
                    pid=f"{group}-{i}"; sku="SKU-"+pid
                    conn.execute("""INSERT INTO sku_promotions(id,sku,promotion_name,discount_percent,rule_key,start_date,end_date,created_at,updated_at)
                        VALUES(?,?,?,10,'manual',?,?,?,?)""",(pid,sku,name,start,end,start,start))
                    conn.execute("INSERT INTO sku_last_promotions VALUES(?,?,?,?,?,?,?)",(sku,pid,name,10,start,end,start))
            conn.execute("INSERT INTO sku_last_promotions VALUES('deleted','gone','历史清仓',5,'2026-07-01','2026-07-02','2026-07-01')")

    def test_migration_audit_idempotent_and_no_resurrection(self):
        self.seed_legacy()
        backup=Path(self.temp.name)/"before.db"
        result=pricing.migrate_legacy(self.path,backup)
        self.assertEqual(result["adjustments"],618)
        self.assertEqual(len(self.states()),618)
        self.assertTrue(pricing.migrate_legacy(self.path,backup)["already_applied"])
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sku_promotions").fetchone()[0],293)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pricing_audit WHERE kind='legacy_snapshot'").fetchone()[0],912)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sku_promotions WHERE sku='deleted'").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sku_last_promotions WHERE sku='deleted'").fetchone()[0],1)
        with closing(sqlite3.connect(backup)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sku_promotions").fetchone()[0],911)

    def test_unknown_activity_blocks_migration_without_changes(self):
        self.seed_legacy()
        with db.connect() as conn:
            conn.execute("UPDATE sku_promotions SET promotion_name='未确认' WHERE id='2-0'")
        with self.assertRaises(ValueError):
            pricing.migrate_legacy(self.path,Path(self.temp.name)/"failed-backup.db")
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM price_adjustments").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sku_promotions").fetchone()[0],911)


if __name__ == "__main__":
    unittest.main()
