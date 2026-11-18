from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import listing_prices as listing
from backend.reports_api import router
from dashboard.data_processing import (
    build_product_rating_columns,
    build_replenishment_rating_summary,
    normalize_rating_source,
    read_local_table,
)
from dashboard.report_store import get_latest_source_path


def workbook(*, count=120, score=4.5, ratings=True):
    row = dict(zip(listing.LISTING_REQUIRED, ["sku-1", "asin-1", "DE", "EUR", 90, 0, 0, 100, 90]))
    row.update({"父ASIN": "PARENT", "变体属性": "color:blue"})
    if ratings:
        row.update({"Rating总数": count, "评分": score})
    buffer = io.BytesIO()
    pd.DataFrame([row]).to_excel(buffer, index=False)
    return buffer.getvalue()


class ListingRatingUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(listing.clear_listing_cache)

    def ratings(self):
        return normalize_rating_source(read_local_table(get_latest_source_path("rating", self.root)))

    def upload(self, name, data):
        return listing.upload_listing_file(name, data, self.root)

    def test_daily_upload_updates_both_consumers_and_preserves_snapshot_fields(self):
        self.upload("Listing20261116.xlsx", workbook())
        rating = self.ratings()
        self.assertEqual(rating.iloc[0]["国家"], "德国")
        self.assertEqual(build_product_rating_columns(rating).iloc[0]["Rating"], "120(4.5)")
        summary = build_replenishment_rating_summary(rating).iloc[0]
        self.assertEqual(summary["产品评价数"], 120)
        self.assertEqual(summary["产品评分值"], 4.5)
        snapshot = listing.load_snapshot("2026-11-16", self.root).iloc[0]
        self.assertEqual(snapshot["当前实际总价"], 90)
        self.assertEqual(snapshot["父ASIN"], "PARENT")
        self.assertEqual(snapshot["Rating总数"], 120)

    def test_zero_count_and_blank_score_keep_existing_null_semantics(self):
        self.upload("Listing20261116.xlsx", workbook(count=0, score=None))
        rating = self.ratings().iloc[0]
        self.assertEqual(rating["Rating总数"], 0)
        self.assertTrue(pd.isna(rating["评分"]))

    def test_same_day_replace_updates_rating_and_older_backfill_cannot_revert_it(self):
        self.upload("Listing20261116.xlsx", workbook(count=120))
        self.assertTrue(self.upload("Listing20261116.xlsx", workbook(count=200))["replaced"])
        self.upload("Listing20261115.xlsx", workbook(count=5))
        self.assertEqual(self.ratings().iloc[0]["Rating总数"], 200)

    def test_idempotent_reupload_recovers_missing_rating_without_rewriting_it_again(self):
        content = workbook()
        self.upload("Listing20261116.xlsx", content)
        source = get_latest_source_path("rating", self.root)
        source.unlink()
        self.assertTrue(self.upload("Listing20261116.xlsx", content)["idempotent"])
        before = source.stat().st_mtime_ns
        self.assertTrue(self.upload("Listing20261116.xlsx", content)["idempotent"])
        self.assertEqual(source.stat().st_mtime_ns, before)
        self.assertEqual(self.ratings().iloc[0]["Rating总数"], 120)

    def test_invalid_rating_rejects_whole_upload_before_changing_either_source(self):
        self.upload("Listing20261115.xlsx", workbook())
        for kwargs in ({"count": "bad"}, {"count": -1}, {"count": 1.5}, {"score": 5.1}, {"score": -1}, {"ratings": False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.upload("Listing20261116.xlsx", workbook(**kwargs))
        self.assertEqual(listing.load_listing_index(self.root)["日期"].tolist(), ["2026-11-15"])
        self.assertEqual(self.ratings().iloc[0]["Rating总数"], 120)

    def test_identical_legacy_snapshot_upgrades_discarded_rating_columns(self):
        content = workbook()
        self.upload("Listing20261116.xlsx", content)
        path = self.root / "listing_prices" / "2026-11-16.csv"
        old = pd.read_csv(path).drop(columns=listing.LISTING_RATING_COLUMNS)
        old.to_csv(path, index=False, encoding="utf-8-sig")
        self.assertTrue(self.upload("Listing20261116.xlsx", content)["idempotent"])
        self.assertEqual(listing.load_snapshot("2026-11-16", self.root).iloc[0]["Rating总数"], 120)

    def test_snapshot_write_failure_restores_rating_and_listing_together(self):
        self.upload("Listing20261116.xlsx", workbook())
        paths = [path for path in self.root.rglob("*") if path.is_file()]
        before = {path: path.read_bytes() for path in paths}
        original = listing._atomic_bytes
        failed = False

        def fail_once(path, data):
            nonlocal failed
            if path == self.root / "listing_prices" / "2026-11-16.xlsx" and not failed:
                failed = True
                raise OSError("simulated write failure")
            return original(path, data)

        with patch.object(listing, "_atomic_bytes", side_effect=fail_once), self.assertRaises(OSError):
            self.upload("Listing20261116.xlsx", workbook(count=300))
        self.assertEqual({path: path.read_bytes() for path in paths}, before)

    def test_old_snapshot_remains_readable_without_erasing_existing_rating(self):
        self.upload("Listing20261115.xlsx", workbook())
        listing.persist_listing_snapshot("Listing20261116.xlsx", workbook(ratings=False), self.root)
        self.assertEqual(self.ratings().iloc[0]["Rating总数"], 120)
        self.assertTrue(listing.load_snapshot("2026-11-16", self.root)["评分"].isna().all())

    def test_upload_api_uses_one_file_and_rejects_missing_rating_columns(self):
        app = FastAPI()
        app.include_router(router)
        with (
            TestClient(app) as client,
            patch("backend.reports_api.upload_listing_file", side_effect=self.upload),
            patch("backend.reports_api._invalidate_dashboard_cache") as invalidate,
        ):
            invalid = client.post("/api/reports/listing-prices", files={"file": ("Listing20261116.xlsx", workbook(ratings=False))})
            self.assertEqual(invalid.status_code, 422)
            self.assertIn("Rating总数", invalid.json()["detail"])
            invalidate.assert_not_called()
            valid = client.post("/api/reports/listing-prices", files={"file": ("Listing20261116.xlsx", workbook())})
            self.assertEqual(valid.status_code, 200, valid.text)
            invalidate.assert_called_once()
            self.assertEqual(self.ratings().iloc[0]["Rating总数"], 120)


if __name__ == "__main__":
    unittest.main()
