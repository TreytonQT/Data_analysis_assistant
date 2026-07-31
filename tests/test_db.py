from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import backend.db as db


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DB_PATH
        db.DB_PATH = Path(self.temp.name) / "app.db"

    def tearDown(self):
        db.DB_PATH = self.original_db
        self.temp.cleanup()

    def test_legacy_promotion_discount_constraint_is_widened_idempotently(self):
        conn = sqlite3.connect(db.DB_PATH)
        conn.executescript(
            """CREATE TABLE sku_promotions (
                id TEXT PRIMARY KEY,
                sku TEXT NOT NULL,
                asin_snapshot TEXT NOT NULL DEFAULT '',
                developer_snapshot TEXT NOT NULL DEFAULT '',
                discount_percent INTEGER NOT NULL CHECK (discount_percent IN (5, 8, 10)),
                rule_key TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (end_date IS NULL OR end_date >= start_date)
            );
            CREATE INDEX idx_sku_promotions_sku ON sku_promotions(sku);
            CREATE INDEX idx_sku_promotions_dates ON sku_promotions(start_date, end_date);
            INSERT INTO sku_promotions VALUES
                ('legacy', 'SKU-A', 'ASIN-A', 'Dev', 10, 'sales_le_10',
                 '2026-07-01', '2026-07-02', '2026-07-01T00:00:00Z', '2026-07-01T00:00:00Z');"""
        )
        conn.close()

        db.initialize_database()
        db.initialize_database()

        with db.connect() as migrated:
            self.assertEqual(migrated.execute("SELECT discount_percent FROM sku_promotions WHERE id = 'legacy'").fetchone()[0], 10)
            self.assertEqual(migrated.execute("SELECT promotion_name FROM sku_promotions WHERE id = 'legacy'").fetchone()[0], db.HISTORY_PROMOTION_NAME)
            migrated.execute(
                """INSERT INTO sku_promotions VALUES
                ('manual', 'SKU-B', '手动活动', '', '', 12, 'manual',
                 '2026-07-22', NULL, '2026-07-22T00:00:00Z', '2026-07-22T00:00:00Z')"""
            )
            indexes = {row[1] for row in migrated.execute("PRAGMA index_list(sku_promotions)")}
            self.assertIn("idx_sku_promotions_sku", indexes)
            self.assertIn("idx_sku_promotions_dates", indexes)

        for invalid in (0, 100, 12.5):
            with self.subTest(invalid=invalid), self.assertRaises(sqlite3.IntegrityError):
                with db.connect() as migrated:
                    migrated.execute(
                        """INSERT INTO sku_promotions VALUES
                        (?, ?, '测试活动', '', '', ?, 'manual', '2026-07-22', NULL,
                         '2026-07-22T00:00:00Z', '2026-07-22T00:00:00Z')""",
                        (f"invalid-{invalid}", f"SKU-{invalid}", invalid),
                    )

    def test_promotion_name_reset_deletes_current_active_records_once_after_backup(self):
        db.initialize_database()
        with db.connect() as conn:
            conn.executemany(
                """INSERT INTO sku_promotions
                (id, sku, promotion_name, asin_snapshot, developer_snapshot, discount_percent, rule_key,
                 start_date, end_date, created_at, updated_at)
                VALUES (?, ?, ?, '', '', 10, 'manual', ?, ?, '2026-07-01T00:00:00Z', '2026-07-01T00:00:00Z')""",
                [
                    ('active', 'SKU-ACTIVE', '旧活动', '2026-07-01', None),
                    ('ended', 'SKU-ENDED', '旧活动', '2026-07-01', '2026-07-02'),
                ],
            )
            conn.execute("DELETE FROM app_migrations WHERE migration_key = ?", (db.PROMOTION_NAME_MIGRATION,))

        db.initialize_database()

        with db.connect() as migrated:
            self.assertIsNone(migrated.execute("SELECT 1 FROM sku_promotions WHERE id = 'active'").fetchone())
            self.assertIsNotNone(migrated.execute("SELECT 1 FROM sku_promotions WHERE id = 'ended'").fetchone())
            self.assertIsNotNone(migrated.execute("SELECT 1 FROM app_migrations WHERE migration_key = ?", (db.PROMOTION_NAME_MIGRATION,)).fetchone())
            migrated.execute(
                """INSERT INTO sku_promotions
                (id, sku, promotion_name, asin_snapshot, developer_snapshot, discount_percent, rule_key,
                 start_date, end_date, created_at, updated_at)
                VALUES ('fresh', 'SKU-FRESH', '新活动', '', '', 10, 'manual', '2026-07-01', NULL,
                        '2026-07-01T00:00:00Z', '2026-07-01T00:00:00Z')"""
            )

        db.initialize_database()
        with db.connect() as migrated:
            self.assertIsNotNone(migrated.execute("SELECT 1 FROM sku_promotions WHERE id = 'fresh'").fetchone())
        backups = list((db.DB_PATH.parent / "backups").glob("app-before-promotion-name-reset-*.db"))
        self.assertEqual(len(backups), 1)

    def test_last_promotion_snapshot_backfill_uses_latest_saved_record_once(self):
        db.initialize_database()
        with db.connect() as conn:
            conn.executemany(
                """INSERT INTO sku_promotions
                (id, sku, promotion_name, asin_snapshot, developer_snapshot, discount_percent, rule_key,
                 start_date, end_date, created_at, updated_at)
                VALUES (?, ?, ?, '', '', ?, 'manual', ?, ?, ?, ?)""",
                [
                    ('older', 'SKU-A', 'Old campaign', 5, '2026-06-01', '2026-06-10', '2026-06-01T00:00:00Z', '2026-06-01T00:00:00Z'),
                    ('newer', 'SKU-A', 'New campaign', 10, '2026-07-01', '2026-07-10', '2026-07-01T00:00:00Z', '2026-07-01T00:00:00Z'),
                    ('missing-source', 'SKU-MISSING', 'Missing campaign', 12, '2026-07-02', None, '2026-07-02T00:00:00Z', '2026-07-02T00:00:00Z'),
                ],
            )
            conn.execute("DELETE FROM app_migrations WHERE migration_key = ?", (db.LAST_PROMOTION_SNAPSHOT_MIGRATION,))

        db.initialize_database()
        with db.connect() as conn:
            snapshots = {
                row['sku']: dict(row)
                for row in conn.execute("SELECT * FROM sku_last_promotions")
            }
            self.assertEqual(snapshots['SKU-A']['promotion_id'], 'newer')
            self.assertEqual(snapshots['SKU-A']['promotion_name'], 'New campaign')
            self.assertEqual(snapshots['SKU-MISSING']['promotion_name'], 'Missing campaign')

            conn.execute("UPDATE sku_promotions SET promotion_name = 'Should not replace' WHERE id = 'newer'")

        db.initialize_database()
        with db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT promotion_name FROM sku_last_promotions WHERE sku = 'SKU-A'").fetchone()[0],
                'New campaign',
            )


if __name__ == "__main__":
    unittest.main()
