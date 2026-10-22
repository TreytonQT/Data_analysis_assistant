from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.batch_monitor as batch_monitor
import backend.db as db
import dashboard.parquet_cache as parquet_cache

app = FastAPI()
app.include_router(batch_monitor.router)


def workbook_bytes(rows: list[dict]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="sheet1")
    return buffer.getvalue()


def csv_bytes(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")


class BatchMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DB_PATH
        self.original_upload_dir = batch_monitor.BATCH_UPLOAD_DIR
        db.DB_PATH = Path(self.temp.name) / "app.db"
        batch_monitor.BATCH_UPLOAD_DIR = Path(self.temp.name) / "uploads"
        db.initialize_database()
        eligible = {
            sku: "运营二十部-陈千潼"
            for sku in (
                "SKU-A01",
                "SKU-A02",
                "SKU-A03",
                "SKU-X01",
                "SKU-ORPHAN",
            )
        }
        self.scope_patch = patch.object(
            batch_monitor,
            "_operational_developer_maps",
            return_value=(eligible, eligible),
        )
        self.scope_mock = self.scope_patch.start()

        self.client = TestClient(app)
        self.warmup = patch("backend.dashboard_api.schedule_replenishment_warmup")
        self.warmup.start()

    def tearDown(self):
        self.scope_patch.stop()
        self.warmup.stop()
        db.DB_PATH = self.original_db
        batch_monitor.BATCH_UPLOAD_DIR = self.original_upload_dir
        self.temp.cleanup()

    def batch_file(self, *skus: str) -> bytes:
        rows = [
            {
                "SKU": 137,
                "DE_PRICE": 137,
                "FR_PRICE": 137,
                "ES_PRICE": 137,
                "IT_PRICE": 137,
                "OTHER": 137,
            }
        ]
        rows.extend(
            {
                "SKU": sku,
                "DE_PRICE": 5.99,
                "FR_PRICE": 6.99,
                "ES_PRICE": 7.99,
                "IT_PRICE": 8.99,
                "OTHER": "保留但不导入",
            }
            for sku in skus
        )
        return workbook_bytes(rows)

    def create_batch(self, batch_no: str, *skus: str):
        return self.client.post(
            "/api/batch-monitor/batches",
            data={"batch_no": batch_no},
            files={
                "file": (
                    f"{batch_no}.xlsx",
                    self.batch_file(*skus),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

    def upload_shipments(self, rows: list[dict]):
        return self.client.post(
            "/api/batch-monitor/shipments",
            files={"file": ("shipments.csv", csv_bytes(rows), "text/csv")},
        )

    def test_list_reads_real_operational_sources_and_invalidates_scope_cache(self):
        self.assertEqual(self.create_batch("ABC260701", "SKU-A01").status_code, 200)
        self.assertEqual(self.upload_shipments([
            {"货件单号": "FBA-ORPHAN", "MSKU": "SKU-ORPHAN", "ASIN": "B0ABC00001"}
        ]).status_code, 200)
        self.scope_patch.stop()
        cache_root = Path(self.temp.name) / "cache"
        rows = [
            {"MSKU": "SKU-A01", "开发员": "运营二十部-陈千潼"},
            {"MSKU": "SKU-ORPHAN", "开发员": "运营二十部-陈千潼"},
        ]
        try:
            for suffix in (".csv", ".xlsx"):
                with self.subTest(suffix=suffix):
                    source = Path(self.temp.name) / f"operational{suffix}"
                    write_source = csv_bytes if suffix == ".csv" else workbook_bytes
                    source.write_bytes(write_source(rows))
                    batch_monitor._cached_operational_developer_maps.cache_clear()
                    with patch.object(parquet_cache, "CACHE_DIR", cache_root), patch.object(
                        batch_monitor, "get_latest_source_path", return_value=source
                    ), patch.object(
                        batch_monitor, "read_local_table", wraps=batch_monitor.read_local_table
                    ) as reader:
                        for view, total in (("incomplete", 1), ("all", 1), ("completed", 0)):
                            response = self.client.get(f"/api/batch-monitor/batches?view={view}")
                            self.assertEqual(response.status_code, 200, response.text)
                            result = response.json()
                            self.assertEqual(result["total"], total)
                            self.assertEqual(result["orphan_count"], 1)
                            self.assertTrue(result["orphan_scope_available"])
                            self.assertEqual(result["metrics"]["incomplete_batches"], 1)
                        reader.assert_called_once_with(source)
                        source.write_bytes(write_source([
                            rows[0], {"MSKU": "SKU-ORPHAN", "开发员": "其他开发员"}
                        ]))
                        response = self.client.get("/api/batch-monitor/batches?view=all")
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(response.json()["orphan_count"], 0)
                        self.assertEqual(reader.call_count, 2)
                        orphans = self.client.get("/api/batch-monitor/orphans")
                        self.assertEqual(orphans.status_code, 200, orphans.text)
                        self.assertEqual(orphans.json()["total"], 0)
        finally:
            batch_monitor._cached_operational_developer_maps.cache_clear()
            parquet_cache.clear_parquet_memory_cache()

    def test_batch_upload_skips_template_row_and_rejects_batch_or_sku_conflicts(self):
        created = self.create_batch("ABC260701", "SKU-A01", "SKU-A02")
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["sku_count"], 2)
        self.assertEqual(created.json()["source_sku_count"], 2)
        self.assertEqual(created.json()["ignored_sku_count"], 0)

        duplicate_batch = self.create_batch("ABC260701", "SKU-A03")
        self.assertEqual(duplicate_batch.status_code, 422)
        self.assertIn("已存在", duplicate_batch.json()["detail"])

        conflicting_sku = self.create_batch("XYZ260701", "SKU-A02", "SKU-X01")
        self.assertEqual(conflicting_sku.status_code, 422)
        self.assertIn("SKU-A02", conflicting_sku.json()["detail"])

        listed = self.client.get("/api/batch-monitor/batches?view=all").json()
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["rows"][0]["sku_count"], 2)

    def test_shipment_upload_preserves_first_binding_and_reports_unassigned(self):
        self.create_batch("ABC260701", "SKU-A01")
        first = self.upload_shipments(
            [{"货件单号": "FBA-FIRST", "MSKU": " sku-a01 ", "ASIN": "b0abc12345"}]
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["inserted"], 1)
        self.assertEqual(first.json()["unassigned"], 0)
        self.assertEqual(first.json()["affected_batches"][0]["batch_no"], "ABC260701")
        self.assertIn("updated_at", first.json())

        second = self.upload_shipments(
            [
                {"货件单号": "FBA-LATER", "MSKU": "SKU-A01", "ASIN": "B0ZZZ12345"},
                {"货件单号": "FBA-LATER", "MSKU": "SKU-ORPHAN", "ASIN": "B0YYY12345"},
            ]
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["inserted"], 1)
        self.assertEqual(second.json()["ignored"], 1)
        self.assertEqual(second.json()["conflicts"], 1)
        self.assertEqual(second.json()["unassigned"], 1)

        details = self.client.get("/api/batch-monitor/batches/ABC260701").json()
        self.assertEqual(details["skus"][0]["shipment_no"], "FBA-FIRST")
        self.assertEqual(details["skus"][0]["asin"], "B0ABC12345")
        orphans = self.client.get("/api/batch-monitor/orphans").json()
        self.assertEqual(orphans["total"], 1)
        self.assertEqual(orphans["rows"][0]["sku"], "SKU-ORPHAN")

    def test_copy_lists_return_unbound_skus_and_unique_pending_batch_shipments(self):
        self.create_batch("ABC260701", "SKU-A01", "SKU-A02", "SKU-A03", "SKU-X01")
        self.upload_shipments(
            [
                {"货件单号": "FBA-PENDING", "MSKU": "SKU-A01", "ASIN": "B0ABC00001"},
                {"货件单号": "FBA-PENDING", "MSKU": "SKU-A02", "ASIN": "B0ABC00002"},
                {"货件单号": "FBA-ARRIVED", "MSKU": "SKU-A03", "ASIN": "B0ABC00003"},
                {
                    "货件单号": "FBA-ORPHAN",
                    "MSKU": "SKU-ORPHAN",
                    "ASIN": "B0ABC00004",
                },
            ]
        )
        arrived = self.client.put(
            "/api/batch-monitor/skus/SKU-A03/arrival",
            json={"arrived": True, "arrival_date": "2026-07-20"},
        )
        self.assertEqual(arrived.status_code, 200, arrived.text)

        response = self.client.get("/api/batch-monitor/copy-lists")
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["unbound_shipment_skus"], ["SKU-X01"])
        self.assertEqual(result["unbound_shipment_count"], 1)
        self.assertEqual(result["pending_shipment_nos"], ["FBA-PENDING"])
        self.assertEqual(result["pending_shipment_count"], 1)

    def test_file_internal_shipment_conflict_is_atomic(self):
        response = self.upload_shipments(
            [
                {"货件单号": "FBA-ONE", "MSKU": "SKU-A01", "ASIN": "B0ABC12345"},
                {"货件单号": "FBA-TWO", "MSKU": "SKU-A01", "ASIN": "B0ABC12345"},
            ]
        )
        self.assertEqual(response.status_code, 422)
        with db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM sku_first_shipments").fetchone()[0],
                0,
            )

    def test_artwork_and_arrival_updates_refresh_counts_without_overwriting_dates(self):
        self.create_batch("ABC260701", "SKU-A01", "SKU-A02")
        self.upload_shipments(
            [
                {"货件单号": "FBA-ONE", "MSKU": "SKU-A01", "ASIN": "B0ABC12345"},
                {"货件单号": "FBA-ONE", "MSKU": "SKU-A02", "ASIN": "B0ABC54321"},
            ]
        )
        artwork = self.client.put(
            "/api/batch-monitor/batches/ABC260701/artwork",
            json={"completed": True},
        )
        self.assertEqual(artwork.status_code, 200)
        self.assertTrue(artwork.json()["completed"])

        sku_arrival = self.client.put(
            "/api/batch-monitor/skus/SKU-A01/arrival",
            json={"arrived": True, "arrival_date": "2026-07-20"},
        )
        self.assertEqual(sku_arrival.status_code, 200)
        shipment_arrival = self.client.put(
            "/api/batch-monitor/shipments/FBA-ONE/arrival",
            json={"arrival_date": "2026-07-21"},
        )
        self.assertEqual(shipment_arrival.status_code, 200)
        self.assertEqual(shipment_arrival.json()["updated"], 1)
        self.assertEqual(
            shipment_arrival.json()["affected_batches"],
            [{
                "batch_no": "ABC260701",
                "updated_skus": 1,
                "arrived_count": 2,
                "sku_count": 2,
                "is_complete": True,
                "manual_completed_at": None,
                "completion_mode": "automatic",
            }],
        )
        details = self.client.get("/api/batch-monitor/batches/ABC260701").json()
        dates = {row["sku"]: row["arrival_date"] for row in details["skus"]}
        self.assertEqual(dates, {"SKU-A01": "2026-07-20", "SKU-A02": "2026-07-21"})

        cleared = self.client.put(
            "/api/batch-monitor/skus/SKU-A01/arrival",
            json={"arrived": False},
        )
        self.assertEqual(cleared.status_code, 200)
        listed = self.client.get("/api/batch-monitor/batches?view=incomplete").json()
        self.assertEqual(listed["rows"][0]["arrived_count"], 1)
        self.assertEqual(listed["metrics"]["pending_arrival_skus"], 1)

        reset_artwork = self.client.put(
            "/api/batch-monitor/batches/ABC260701/artwork",
            json={"completed": False},
        )
        self.assertEqual(reset_artwork.status_code, 200)
        self.assertFalse(reset_artwork.json()["completed"])

    def test_new_batch_filters_once_and_locks_matched_chen_skus(self):
        all_developers = {
            "SKU-A01": "运营二十部-陈千潼-26",
            "SKU-OTHER": "运营一部-李四",
        }
        self.scope_mock.return_value = (
            all_developers,
            {"SKU-A01": "运营二十部-陈千潼-26"},
        )
        data = workbook_bytes([
            {
                "SKU": "SKU-A01",
                "DE_PRICE": 5.99,
                "FR_PRICE": 6.99,
                "ES_PRICE": 7.99,
                "IT_PRICE": 8.99,
            },
            {
                "SKU": "SKU-OTHER",
                "DE_PRICE": -1,
                "FR_PRICE": None,
                "ES_PRICE": 0,
                "IT_PRICE": "非法但应忽略",
            },
        ])
        created = self.client.post(
            "/api/batch-monitor/batches",
            data={"batch_no": "ABC260701"},
            files={
                "file": (
                    "ABC260701.xlsx",
                    data,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["source_sku_count"], 2)
        self.assertEqual(created.json()["imported_sku_count"], 1)
        self.assertEqual(created.json()["ignored_sku_count"], 1)
        self.assertEqual(created.json()["ignored_examples"][0]["sku"], "SKU-OTHER")

        # Changing the latest operational scope does not change locked membership.
        self.scope_mock.return_value = ({}, {})
        listed = self.client.get("/api/batch-monitor/batches?view=all").json()
        self.assertEqual(listed["rows"][0]["sku_count"], 1)
        details = self.client.get("/api/batch-monitor/batches/ABC260701").json()
        self.assertEqual([row["sku"] for row in details["skus"]], ["SKU-A01"])
        with db.connect() as conn:
            row = conn.execute(
                """SELECT developer_snapshot, monitor_basis
                FROM batch_monitor_skus WHERE sku = 'SKU-A01'"""
            ).fetchone()
        self.assertEqual(row["developer_snapshot"], "运营二十部-陈千潼-26")
        self.assertEqual(row["monitor_basis"], "creation_match")

    def test_new_batch_rejects_when_every_sku_is_out_of_scope(self):
        self.scope_mock.return_value = (
            {"SKU-A01": "运营一部-李四"},
            {},
        )
        response = self.create_batch("ABC260701", "SKU-A01")
        self.assertEqual(response.status_code, 422)
        self.assertIn("没有开发员包含", response.json()["detail"])
        with db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM batch_monitor_batches").fetchone()[0],
                0,
            )

    def test_shipment_arrival_requires_non_future_date_and_schema_has_no_first_seen(self):
        self.create_batch("ABC260701", "SKU-A01")
        self.upload_shipments(
            [{"货件单号": "FBA-ONE", "MSKU": "SKU-A01", "ASIN": "B0ABC12345"}]
        )
        missing = self.client.put(
            "/api/batch-monitor/shipments/FBA-ONE/arrival",
            json={},
        )
        self.assertEqual(missing.status_code, 422)
        future = self.client.put(
            "/api/batch-monitor/shipments/FBA-ONE/arrival",
            json={"arrival_date": (date.today() + timedelta(days=1)).isoformat()},
        )
        self.assertEqual(future.status_code, 422)
        sku_future = self.client.put("/api/batch-monitor/skus/SKU-A01/arrival", json={"arrived": True, "arrival_date": (date.today() + timedelta(days=1)).isoformat()})
        self.assertEqual(sku_future.status_code, 422)
        with db.connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(sku_first_shipments)")
            }
        self.assertNotIn("first_seen_at", columns)

    def test_legacy_first_seen_schema_migrates_without_losing_shipment_data(self):
        db.DB_PATH.unlink()
        conn = sqlite3.connect(db.DB_PATH)
        try:
            conn.executescript(
                """CREATE TABLE batch_monitor_batches (
                    batch_no TEXT PRIMARY KEY,
                    artwork_completed_date TEXT,
                    source_file_name TEXT NOT NULL DEFAULT '',
                    source_file_hash TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE batch_monitor_skus (
                    sku TEXT PRIMARY KEY,
                    batch_no TEXT NOT NULL,
                    de_price REAL,
                    fr_price REAL,
                    es_price REAL,
                    it_price REAL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE sku_first_shipments (
                    sku TEXT PRIMARY KEY,
                    shipment_no TEXT NOT NULL,
                    asin TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    arrival_date TEXT,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO sku_first_shipments
                VALUES ('SKU-A01', 'FBA-ONE', 'B0ABC12345',
                        '2026-07-01T10:00:00+08:00', '2026-07-20',
                        '2026-07-20T10:00:00+08:00');"""
            )
            conn.commit()
        finally:
            conn.close()

        db.initialize_database()
        with db.connect() as migrated:
            columns = {
                row["name"]
                for row in migrated.execute("PRAGMA table_info(sku_first_shipments)")
            }
            shipment = migrated.execute(
                "SELECT * FROM sku_first_shipments WHERE sku = 'SKU-A01'"
            ).fetchone()
            batch_columns = {
                row["name"]
                for row in migrated.execute("PRAGMA table_info(batch_monitor_skus)")
            }
            completion_columns = {
                row["name"]
                for row in migrated.execute("PRAGMA table_info(batch_monitor_batches)")
            }
        db.initialize_database()
        self.assertNotIn("first_seen_at", columns)
        self.assertEqual(shipment["shipment_no"], "FBA-ONE")
        self.assertEqual(shipment["arrival_date"], "2026-07-20")
        self.assertIn("developer_snapshot", batch_columns)
        self.assertIn("monitor_basis", batch_columns)
        self.assertIn("manual_completed_at", completion_columns)

    def test_manual_completion_is_idempotent_preserves_progress_and_can_be_undone(self):
        self.create_batch("ABC260701", "SKU-A01", "SKU-A02")
        self.upload_shipments([
            {"货件单号": "FBA-ONE", "MSKU": "SKU-A01", "ASIN": "B0ABC12345"},
        ])
        self.client.put(
            "/api/batch-monitor/skus/SKU-A01/arrival",
            json={"arrived": True, "arrival_date": "2026-09-01"},
        )
        before = self.client.get("/api/batch-monitor/batches/ABC260701").json()
        completed = self.client.put(
            "/api/batch-monitor/batches/ABC260701/completion",
            json={"completed": True},
        )
        self.assertEqual(completed.status_code, 200, completed.text)
        row = completed.json()["batch"]
        self.assertTrue(row["is_complete"])
        self.assertEqual(row["completion_mode"], "manual")
        self.assertTrue(row["manual_completed_at"])
        self.assertIsNone(row["artwork_completed_date"])
        self.assertEqual((row["shipped_count"], row["arrived_count"]), (1, 1))

        repeated = self.client.put(
            "/api/batch-monitor/batches/ABC260701/completion",
            json={"completed": True},
        ).json()["batch"]
        self.assertEqual(repeated["manual_completed_at"], row["manual_completed_at"])
        after = self.client.get("/api/batch-monitor/batches/ABC260701").json()
        self.assertEqual(after["skus"], before["skus"])
        self.assertEqual(after["batch"]["artwork_completed_date"], before["batch"]["artwork_completed_date"])

        incomplete = self.client.get("/api/batch-monitor/batches?view=incomplete").json()
        completed_view = self.client.get("/api/batch-monitor/batches?view=completed").json()
        self.assertEqual(incomplete["total"], 0)
        self.assertEqual(completed_view["rows"][0]["completion_mode"], "manual")
        self.assertEqual(incomplete["metrics"]["incomplete_batches"], 0)
        copy_lists = self.client.get("/api/batch-monitor/copy-lists").json()
        self.assertEqual(copy_lists["unbound_shipment_skus"], [])
        self.assertEqual(copy_lists["pending_shipment_nos"], [])

        undone = self.client.put(
            "/api/batch-monitor/batches/ABC260701/completion",
            json={"completed": False},
        )
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertIsNone(undone.json()["batch"]["manual_completed_at"])
        self.assertEqual(undone.json()["batch"]["completion_mode"], "in_progress")
        self.assertFalse(undone.json()["batch"]["is_complete"])
        self.assertEqual(self.client.get("/api/batch-monitor/batches?view=incomplete").json()["total"], 1)
        self.assertEqual(self.client.get("/api/batch-monitor/copy-lists").json()["unbound_shipment_skus"], ["SKU-A02"])

        self.client.put("/api/batch-monitor/batches/ABC260701/artwork", json={"completed": True})
        self.upload_shipments([
            {"货件单号": "FBA-TWO", "MSKU": "SKU-A02", "ASIN": "B0ABC54321"},
        ])
        self.client.put(
            "/api/batch-monitor/skus/SKU-A02/arrival",
            json={"arrived": True, "arrival_date": "2026-09-02"},
        )
        natural = self.client.get("/api/batch-monitor/batches?view=completed").json()["rows"][0]
        self.assertEqual(natural["completion_mode"], "automatic")
        self.assertTrue(natural["is_complete"])

    def test_batch_monitor_list_excludes_price_metrics(self):
        response = self.client.get("/api/batch-monitor/batches?include_price_metrics=true")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()["metrics"]), {
            "incomplete_batches",
            "pending_artwork_batches",
            "pending_shipment_skus",
            "pending_arrival_skus",
        })
        self.assertEqual(self.client.get("/api/batch-monitor/price-metrics").status_code, 404)

    def test_launch_price_import_is_validated_and_idempotent(self):
        path = Path(self.temp.name) / "开售价.xlsx"
        path.write_bytes(
            workbook_bytes(
                [
                    {
                        "SKU": " sku-a01 ",
                        "DE开售价格": 5.99,
                        "FR开售价格": 6.99,
                        "ES开售价格": 0,
                        "IT开售价格": 8.99,
                    },
                    {
                        "SKU": "SKU-A02",
                        "DE开售价格": 7.99,
                        "FR开售价格": None,
                        "ES开售价格": 9.99,
                        "IT开售价格": 10.99,
                    },
                ]
            )
        )

        stats = batch_monitor.import_launch_price_file(path)
        self.assertEqual(stats, {"rows": 2, "inserted": 2, "updated": 0})
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT sku, de_price, fr_price, es_price, it_price FROM sku_launch_prices ORDER BY sku"
            ).fetchall()
        self.assertEqual([tuple(row) for row in rows], [
            ("SKU-A01", 5.99, 6.99, None, 8.99),
            ("SKU-A02", 7.99, None, 9.99, 10.99),
        ])
        self.assertEqual(batch_monitor.import_launch_price_file(path), stats)

    def test_launch_price_import_rejects_duplicate_skus(self):
        path = Path(self.temp.name) / "duplicate.xlsx"
        path.write_bytes(
            workbook_bytes(
                [
                    {"SKU": "SKU-A01", "DE开售价格": 5, "FR开售价格": 6, "ES开售价格": 7, "IT开售价格": 8},
                    {"SKU": " sku-a01 ", "DE开售价格": 5, "FR开售价格": 6, "ES开售价格": 7, "IT开售价格": 8},
                ]
            )
        )
        with self.assertRaisesRegex(ValueError, "SKU 重复"):
            batch_monitor.import_launch_price_file(path)

    def test_launch_price_import_rejects_negative_prices(self):
        path = Path(self.temp.name) / "invalid-price.xlsx"
        path.write_bytes(
            workbook_bytes(
                [
                    {"SKU": "SKU-A01", "DE开售价格": -1, "FR开售价格": 6, "ES开售价格": 7, "IT开售价格": 8},
                ]
            )
        )
        with self.assertRaisesRegex(ValueError, "价格不能为负数"):
            batch_monitor.import_launch_price_file(path)

    def test_provided_files_match_migration_and_first_shipment_baselines(self):
        history_path = Path("C:/Users/Admin/Desktop/批次监控.xlsx")
        batch_path = Path("D:/20-FAK-CQT-2607-1-1785400037239.xlsx")
        shipment_path = Path(
            "D:/fba报表-货件列表_2026-07-29 ~ 2026-07-29_61669205439412633639014126972.csv"
        )
        if not all(path.exists() for path in (history_path, batch_path, shipment_path)):
            self.skipTest("用户提供的验收文件当前不可用")

        stats = batch_monitor.import_history_file(history_path)
        self.assertEqual(
            {
                key: stats[key]
                for key in (
                    "batches",
                    "batch_skus",
                    "shipments",
                    "arrived_shipments",
                    "pending_shipments",
                    "batch_shipped",
                    "batch_arrived",
                    "artwork_completed_batches",
                    "artwork_pending_batches",
                    "orphan_shipments",
                )
            },
            {
                "batches": 89,
                "batch_skus": 2467,
                "shipments": 2937,
                "arrived_shipments": 2757,
                "pending_shipments": 180,
                "batch_shipped": 1916,
                "batch_arrived": 1820,
                "artwork_completed_batches": 83,
                "artwork_pending_batches": 6,
                "orphan_shipments": 1021,
            },
        )
        _, sample_rows = batch_monitor.parse_batch_workbook(batch_path.read_bytes())
        self.assertEqual(len(sample_rows), 25)
        shipment_stats = batch_monitor.import_shipment_upload(
            shipment_path.name,
            shipment_path.read_bytes(),
        )
        self.assertEqual(
            {
                key: shipment_stats[key]
                for key in ("inserted", "ignored", "unassigned", "conflicts")
            },
            {"inserted": 37, "ignored": 10, "unassigned": 37, "conflicts": 3},
        )
        rerun = batch_monitor.import_history_file(history_path)
        self.assertEqual(rerun, stats)


if __name__ == "__main__":
    unittest.main()
