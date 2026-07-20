from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

import backend.db as db
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

    def dates(self, start_offset=0, end_offset=None):
        return {
            "start_date": (self.current + timedelta(days=start_offset)).isoformat(),
            "end_date": None if end_offset is None else (self.current + timedelta(days=end_offset)).isoformat(),
        }

    def create(self, skus, start_offset=0, end_offset=None):
        return self.client.post(
            "/api/promotions",
            json={"skus": skus, **self.dates(start_offset, end_offset)},
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
            json={"skus": ["SKU-A"], "start_date": self.current.isoformat(), "end_date": (self.current - timedelta(days=1)).isoformat()},
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
                (id, sku, asin_snapshot, developer_snapshot, discount_percent, rule_key,
                 start_date, end_date, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "missing-source-id",
                    "SKU-MISSING",
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
        by_discount = {row["discount_percent"]: row for row in overview["by_discount"]}
        self.assertEqual(by_discount[8]["daily_lift"], -1)

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


if __name__ == "__main__":
    unittest.main()
