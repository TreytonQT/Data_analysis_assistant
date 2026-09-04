from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

import backend.db as db
from backend import dashboard_api
from backend.main import app


class PromotionsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DB_PATH
        db.DB_PATH = Path(self.temp.name) / "app.db"
        db.initialize_database()
        self.client = TestClient(app)
        self.current = date.today()
        self.metrics = pd.DataFrame(
            [
                self.metric("SKU-A", "ASIN-A", "甲", 25, 10, 5, 5, 3, 2),
                self.metric("SKU-B", "ASIN-B", "乙", 30, 20, 4, 1, 2, -1),
                self.metric("SKU-C", "ASIN-C", "甲", 40, 30, 3, 4, 4, 0),
                self.metric("SKU-D", "ASIN-D", "丙", 50, 80, 0, 10, 8, 2),
            ]
        )
        self.candidates = pd.DataFrame(
            [
                {**self.metrics.iloc[0].to_dict(), "discount_percent": 10, "rule_key": "sales_le_10"},
                {**self.metrics.iloc[1].to_dict(), "discount_percent": 8, "rule_key": "sales_11_20"},
                {**self.metrics.iloc[2].to_dict(), "discount_percent": 5, "rule_key": "sales_21_30"},
            ]
        )
        self.frames = patch(
            "backend.promotions.load_promotion_frames",
            side_effect=lambda: (self.metrics.copy(), self.candidates.copy()),
        )
        self.frames.start()

    def tearDown(self):
        self.frames.stop()
        db.DB_PATH = self.original_db
        self.temp.cleanup()

    @staticmethod
    def metric(sku, asin, developer, available, sales_90d, aged, average_7d, average_30d, lift):
        return {
            "sku": sku,
            "asin": asin,
            "developer": developer,
            "available_inventory": available,
            "sales_90d": sales_90d,
            "aged_inventory_90d": aged,
            "average_7d": average_7d,
            "average_30d": average_30d,
            "daily_lift": lift,
        }

    def dates(self, start_offset=0, end_offset=None, promotion_name="测试促销"):
        return {
            "promotion_name": promotion_name,
            "start_date": (self.current + timedelta(days=start_offset)).isoformat(),
            "end_date": None if end_offset is None else (self.current + timedelta(days=end_offset)).isoformat(),
        }

    def create(self, skus, start_offset=0, end_offset=None):
        return self.client.post(
            "/api/promotions",
            json={"skus": skus, **self.dates(start_offset, end_offset)},
        )

    def test_product_promotions_use_current_date_window(self):
        self.assertEqual(self.create_manual(["SKU-A"], discount=10, start_offset=-1, end_offset=0).status_code, 201)
        self.assertEqual(self.create_manual(["SKU-B"], discount=8, start_offset=1, end_offset=2).status_code, 201)
        self.assertEqual(self.create_manual(["SKU-C"], discount=5, start_offset=-2, end_offset=-1).status_code, 201)
        self.assertEqual(self.create_manual(["SKU-D"], discount=12, start_offset=-2).status_code, 201)

        active = dashboard_api._active_product_promotion_rows(self.current).set_index("SKU")

        self.assertEqual(active.loc["SKU-A", "促销折扣"], 10)
        self.assertEqual(active.loc["SKU-D", "促销折扣"], 12)
        self.assertNotIn("SKU-B", active.index)
        self.assertNotIn("SKU-C", active.index)

    def create_manual(self, skus, discount=12, start_offset=0, end_offset=None, promotion_name="手动促销"):
        return self.client.post(
            "/api/promotions/manual",
            json={"skus": skus, "discount_percent": discount, **self.dates(start_offset, end_offset, promotion_name)},
        )

    def test_candidates_support_paging_search_sort_copy_and_csv(self):
        response = self.client.get(
            "/api/promotions/candidates/10",
            params={"search": "sku-a", "developers": "甲", "sort_by": "daily_lift", "sort_order": "desc"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["rows"][0]["sku"], "SKU-A")
        self.assertEqual(payload["developers"], ["甲"])
        self.assertTrue(any(column["key"] == "daily_lift" and column["precision"] == 2 for column in payload["columns"]))

        text = self.client.get("/api/promotions/candidates/10/skus.txt").text
        self.assertEqual(text, "SKU-A\n")
        exported = self.client.get("/api/promotions/candidates/10/export.csv")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("SKU-A", exported.text)
        self.assertIn("日均提升", exported.text)

        invalid_sort = self.client.get("/api/promotions/candidates/10", params={"sort_by": "unknown"})
        self.assertEqual(invalid_sort.status_code, 422)
        long_search = self.client.get("/api/promotions/candidates/10", params={"search": "x" * 201})
        self.assertEqual(long_search.status_code, 422)

    def test_batch_create_is_atomic_and_current_promotions_leave_candidates(self):
        failed = self.create(["SKU-A", "NOT-A-CANDIDATE"])
        self.assertEqual(failed.status_code, 409)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sku_promotions").fetchone()[0], 0)

        created = self.create(["SKU-A", "SKU-B"])
        self.assertEqual(created.status_code, 201)
        rows = created.json()["created"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(isinstance(row["id"], str) and len(row["id"]) == 36 for row in rows))
        self.assertEqual({row["status"] for row in rows}, {"active"})
        self.assertEqual(self.client.get("/api/promotions/candidates/10").json()["total"], 0)
        self.assertEqual(self.client.get("/api/promotions/candidates/8").json()["total"], 0)

        duplicate = self.create(["SKU-A"])
        self.assertEqual(duplicate.status_code, 409)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sku_promotions").fetchone()[0], 2)

    def test_manual_create_accepts_non_candidates_and_missing_source(self):
        response = self.create_manual([" SKU-D ", "SKU-D", "SKU-MISSING"], discount=12)

        self.assertEqual(response.status_code, 201)
        rows = {row["sku"]: row for row in response.json()["created"]}
        self.assertEqual(set(rows), {"SKU-D", "SKU-MISSING"})
        self.assertEqual(rows["SKU-D"]["discount_percent"], 12)
        self.assertEqual(rows["SKU-D"]["promotion_name"], "手动促销")
        self.assertEqual(rows["SKU-D"]["rule_key"], "manual")
        self.assertEqual(rows["SKU-D"]["asin_snapshot"], "ASIN-D")
        self.assertFalse(rows["SKU-D"]["source_missing"])
        self.assertEqual(rows["SKU-MISSING"]["asin_snapshot"], "")
        self.assertTrue(rows["SKU-MISSING"]["source_missing"])

        records = self.client.get("/api/promotions/records", params={"status": "all"}).json()
        self.assertEqual(records["total"], 2)

    def test_manual_create_validates_discount_and_replaces_current_record(self):
        for discount in [0, 100, 12.5]:
            with self.subTest(discount=discount):
                self.assertEqual(self.create_manual(["SKU-A"], discount=discount).status_code, 422)

        original = self.create_manual(["SKU-A"], discount=1, start_offset=0, end_offset=2)
        self.assertEqual(original.status_code, 201)
        original_id = original.json()["created"][0]["id"]

        replaced = self.create_manual(["SKU-B", "SKU-A"], discount=99, start_offset=1, end_offset=7)
        self.assertEqual(replaced.status_code, 201, replaced.text)
        self.assertEqual(replaced.json()["replaced"], 1)
        rows = {row["sku"]: row for row in replaced.json()["created"]}
        self.assertEqual(rows["SKU-A"]["id"], original_id)
        self.assertEqual(rows["SKU-A"]["discount_percent"], 99)
        self.assertEqual(rows["SKU-A"]["start_date"], self.dates(1, 7)["start_date"])
        self.assertEqual(rows["SKU-A"]["end_date"], self.dates(1, 7)["end_date"])
        self.assertEqual(rows["SKU-A"]["status"], "pending")
        self.assertEqual(rows["SKU-A"]["rule_key"], "manual")
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sku_promotions").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sku_promotions WHERE sku = 'SKU-A'").fetchone()[0], 1)

    def test_manual_replace_still_rejects_historical_overlap_atomically(self):
        historical = self.create_manual(["SKU-A"], discount=10, start_offset=-10, end_offset=-5)
        self.assertEqual(historical.status_code, 201)

        conflict = self.create_manual(["SKU-A", "SKU-B"], discount=30, start_offset=-7, end_offset=-3)
        self.assertEqual(conflict.status_code, 409)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sku_promotions").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sku_promotions WHERE sku = 'SKU-B'").fetchone()[0], 0)

    def test_manual_promotion_blocks_candidate_and_reenters_after_end(self):
        created = self.create_manual(["SKU-A"], discount=15)
        self.assertEqual(created.status_code, 201)
        promotion_id = created.json()["created"][0]["id"]
        self.assertEqual(self.client.get("/api/promotions/candidates/10").json()["total"], 0)

        ended = self.client.put(f"/api/promotions/{promotion_id}", json=self.dates(0, -1))
        self.assertEqual(ended.status_code, 422)
        ended = self.client.put(f"/api/promotions/{promotion_id}", json=self.dates(-2, -1))
        self.assertEqual(ended.status_code, 200)
        self.assertEqual(self.client.get("/api/promotions/candidates/10").json()["total"], 1)

    def test_manual_promotion_is_included_in_activity_overview_grouping(self):
        self.assertEqual(self.create_manual(["SKU-D"], discount=12, promotion_name="夏季清仓").status_code, 201)

        overview = self.client.get("/api/promotions/overview").json()
        by_promotion = {row["promotion_name"]: row for row in overview["by_promotion"]}
        self.assertEqual(overview["active_sku_count"], 1)
        self.assertEqual(overview["daily_lift_total"], 2)
        self.assertEqual(by_promotion["夏季清仓"]["sku_count"], 1)

    def test_status_dates_update_delete_and_ended_candidate_reentry(self):
        ended = self.create(["SKU-B"], -20, -10)
        self.assertEqual(ended.status_code, 201)
        ended_id = ended.json()["created"][0]["id"]
        self.assertEqual(ended.json()["created"][0]["status"], "ended")
        self.assertEqual(self.client.get("/api/promotions/candidates/8").json()["total"], 1)

        future = self.create(["SKU-C"], 2, 5)
        future_id = future.json()["created"][0]["id"]
        self.assertEqual(future.json()["created"][0]["status"], "pending")
        self.assertEqual(self.client.get("/api/promotions/candidates/5").json()["total"], 0)

        active = self.create(["SKU-A"], -5, 0)
        active_id = active.json()["created"][0]["id"]
        self.assertEqual(active.json()["created"][0]["status"], "active")
        active_records = self.client.get("/api/promotions/records").json()
        self.assertEqual(active_records["total"], 1)
        self.assertEqual(active_records["rows"][0]["id"], active_id)

        update = self.client.put(f"/api/promotions/{active_id}", json=self.dates(-5, -1))
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json()["status"], "ended")
        self.assertEqual(self.client.get("/api/promotions/candidates/10").json()["total"], 1)

        deleted = self.client.delete(f"/api/promotions/{future_id}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get("/api/promotions/candidates/5").json()["total"], 1)
        self.assertEqual(self.client.delete(f"/api/promotions/{future_id}").status_code, 404)

        all_records = self.client.get("/api/promotions/records", params={"status": "all"}).json()
        self.assertEqual(all_records["total"], 2)
        self.assertIn(ended_id, {row["id"] for row in all_records["rows"]})

    def test_overlapping_periods_are_rejected_and_invalid_dates_are_422(self):
        first = self.create(["SKU-B"], -30, -20)
        self.assertEqual(first.status_code, 201)
        overlap = self.create(["SKU-B"], -25, -15)
        self.assertEqual(overlap.status_code, 409)
        non_overlap = self.create(["SKU-B"], -19, -10)
        self.assertEqual(non_overlap.status_code, 201)

        invalid = self.client.post(
            "/api/promotions",
            json={"skus": ["SKU-A"], "promotion_name": "测试促销", "start_date": self.current.isoformat(), "end_date": (self.current - timedelta(days=1)).isoformat()},
        )
        self.assertEqual(invalid.status_code, 422)

        first_id = first.json()["created"][0]["id"]
        edit_overlap = self.client.put(f"/api/promotions/{first_id}", json=self.dates(-22, -12))
        self.assertEqual(edit_overlap.status_code, 409)

    def test_overview_preserves_negative_lift_and_missing_source_is_explicit(self):
        self.assertEqual(self.create(["SKU-A", "SKU-B"]).status_code, 201)
        timestamp = "2026-01-01T00:00:00+00:00"
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO sku_promotions
                (id, sku, promotion_name, asin_snapshot, developer_snapshot, discount_percent, rule_key,
                 start_date, end_date, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "missing-source-id",
                    "SKU-MISSING",
                    "历史活动",
                    "ASIN-M",
                    "甲",
                    5,
                    "aged_90d",
                    (self.current - timedelta(days=1)).isoformat(),
                    None,
                    timestamp,
                    timestamp,
                ),
            )

        overview = self.client.get("/api/promotions/overview").json()
        self.assertEqual(overview["active_sku_count"], 2)
        self.assertEqual(overview["source_missing_count"], 1)
        self.assertEqual(overview["average_7d_total"], 6)
        self.assertEqual(overview["average_30d_total"], 5)
        self.assertEqual(overview["daily_lift_total"], 1)
        self.assertEqual(overview["daily_lift_average"], 0.5)
        by_promotion = {row["promotion_name"]: row for row in overview["by_promotion"]}
        self.assertEqual(by_promotion["测试促销"]["daily_lift"], 1)
        self.assertEqual(by_promotion["测试促销"]["discount_percents"], [8, 10])

        filtered = self.client.get("/api/promotions/overview", params={"developers": "乙"}).json()
        self.assertEqual(filtered["active_sku_count"], 1)
        self.assertEqual(filtered["daily_lift_total"], -1)

        records = self.client.get(
            "/api/promotions/records",
            params={"status": "all", "search": "SKU-MISSING"},
        ).json()
        self.assertEqual(records["total"], 1)
        self.assertTrue(records["rows"][0]["source_missing"])
        self.assertIsNone(records["rows"][0]["daily_lift"])
        exported = self.client.get("/api/promotions/records/export.csv", params={"status": "all"})
        self.assertIn("SKU-MISSING", exported.text)

    def test_overview_keeps_ended_activity_with_dates_until_activity_is_deleted(self):
        ended = self.create_manual(
            ["SKU-A", "SKU-B"],
            discount=10,
            start_offset=-7,
            end_offset=-1,
            promotion_name="Review campaign",
        )
        self.assertEqual(ended.status_code, 201)
        current = self.create_manual(["SKU-D"], discount=12, promotion_name="Current campaign")
        self.assertEqual(current.status_code, 201)

        overview = self.client.get("/api/promotions/overview").json()
        activities = {row["promotion_name"]: row for row in overview["by_promotion"]}
        review = activities["Review campaign"]
        self.assertEqual(review["status"], "ended")
        self.assertEqual(review["start_date"], self.dates(-7, -1)["start_date"])
        self.assertEqual(review["end_date"], self.dates(-7, -1)["end_date"])
        self.assertEqual(review["sku_count"], 2)
        self.assertEqual(review["discount_percents"], [10])
        self.assertEqual(review["daily_lift"], 1)
        self.assertEqual(overview["active_sku_count"], 1)

        deleted = self.client.request("DELETE", "/api/promotions/activities", json={"promotion_name": "Review campaign"})
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["deleted"], 2)
        remaining = self.client.get("/api/promotions/overview").json()["by_promotion"]
        self.assertEqual([row["promotion_name"] for row in remaining], ["Current campaign"])
        retained_last_records = self.client.get("/api/promotions/last-promotions", params={"search": "Review campaign"}).json()
        self.assertEqual(retained_last_records["total"], 2)
        self.assertEqual(self.client.get("/api/promotions/candidates/10").json()["total"], 1)
        self.assertEqual(self.client.get("/api/promotions/candidates/8").json()["total"], 1)

        missing = self.client.request("DELETE", "/api/promotions/activities", json={"promotion_name": "Review campaign"})
        self.assertEqual(missing.status_code, 404)
        blank = self.client.request("DELETE", "/api/promotions/activities", json={"promotion_name": "  "})
        self.assertEqual(blank.status_code, 422)

    def test_last_promotion_snapshot_persists_after_delete_and_new_promotion_overwrites(self):
        created = self.create_manual(
            ["SKU-A", "SKU-MISSING"],
            discount=12,
            start_offset=0,
            end_offset=1,
            promotion_name="Initial campaign",
        )
        self.assertEqual(created.status_code, 201)
        promotion_id = next(row["id"] for row in created.json()["created"] if row["sku"] == "SKU-A")

        first = self.client.get("/api/promotions/last-promotions", params={"search": "SKU-A"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["total"], 1)
        self.assertIn("Initial campaign -12%", first.json()["rows"][0]["promotion_content"])

        edited = self.client.put(f"/api/promotions/{promotion_id}", json=self.dates(0, 2, "Edited campaign"))
        self.assertEqual(edited.status_code, 200)
        after_edit = self.client.get("/api/promotions/last-promotions", params={"search": "SKU-A"}).json()["rows"][0]
        self.assertIn("Initial campaign -12%", after_edit["promotion_content"])
        self.assertNotIn("Edited campaign", after_edit["promotion_content"])

        deleted = self.client.delete(f"/api/promotions/{promotion_id}")
        self.assertEqual(deleted.status_code, 204)
        after_delete = self.client.get("/api/promotions/last-promotions", params={"search": "SKU-A"}).json()["rows"][0]
        self.assertIn("Initial campaign -12%", after_delete["promotion_content"])
        self.assertNotIn("Edited campaign", after_delete["promotion_content"])

        replacement = self.create_manual(
            ["SKU-A"],
            discount=20,
            start_offset=3,
            end_offset=5,
            promotion_name="Replacement campaign",
        )
        self.assertEqual(replacement.status_code, 201)
        after_replacement = self.client.get("/api/promotions/last-promotions", params={"search": "SKU-A"}).json()["rows"][0]
        self.assertIn("Replacement campaign -20%", after_replacement["promotion_content"])

        all_rows = self.client.get("/api/promotions/last-promotions", params={"page": 1, "page_size": 1, "sort_by": "sku", "sort_order": "asc"})
        self.assertEqual(all_rows.status_code, 200)
        self.assertEqual(all_rows.json()["total"], 2)
        self.assertEqual([column["key"] for column in all_rows.json()["columns"]], ["sku", "promotion_content"])

        exported = self.client.get(
            "/api/promotions/last-promotions/export.csv",
            params={
                "search": "Replacement campaign",
                "sort_by": "sku",
                "sort_order": "asc",
            },
        )
        self.assertEqual(exported.status_code, 200)
        self.assertTrue(exported.content.startswith(b"\xef\xbb\xbf"))
        self.assertIn("SKU-A", exported.text)
        self.assertIn("Replacement campaign -20%", exported.text)
        self.assertNotIn("SKU-MISSING", exported.text)

        self.assertEqual(self.client.get("/api/promotions/last-promotions", params={"sort_by": "unknown"}).status_code, 422)

    def test_promotion_name_is_required_normalized_and_editable(self):
        missing = self.client.post("/api/promotions", json={"skus": ["SKU-A"], "start_date": self.current.isoformat()})
        self.assertEqual(missing.status_code, 422)
        blank = self.client.post("/api/promotions", json={"skus": ["SKU-A"], "promotion_name": "  ", "start_date": self.current.isoformat()})
        self.assertEqual(blank.status_code, 422)
        too_long = self.client.post("/api/promotions", json={"skus": ["SKU-A"], "promotion_name": "x" * 101, "start_date": self.current.isoformat()})
        self.assertEqual(too_long.status_code, 422)

        created = self.create(["SKU-A"])
        self.assertEqual(created.status_code, 201)
        promotion_id = created.json()["created"][0]["id"]
        updated = self.client.put(f"/api/promotions/{promotion_id}", json=self.dates(0, None, "  夏季活动  "))
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["promotion_name"], "夏季活动")

        records = self.client.get("/api/promotions/records", params={"search": "夏季活动"}).json()
        self.assertEqual(records["total"], 1)
        exported = self.client.get("/api/promotions/records/export.csv")
        self.assertIn("夏季活动", exported.text)


if __name__ == "__main__":
    unittest.main()
