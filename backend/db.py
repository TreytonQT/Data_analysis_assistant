from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "app.db"
PROMOTION_NAME_MIGRATION = "2026-07-promotion-name-active-reset"
LAST_PROMOTION_SNAPSHOT_MIGRATION = "2026-07-last-promotion-snapshot-backfill"
HISTORY_PROMOTION_NAME = "历史未命名促销"
LOCAL_TIMEZONE = timezone(timedelta(hours=8))


def initialize_database() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                due_at TEXT,
                remind_at TEXT,
                recurrence_type TEXT NOT NULL DEFAULT 'none',
                recurrence_days TEXT NOT NULL DEFAULT '[]',
                next_reminder_at TEXT,
                notification_read_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_remind_at ON tasks(remind_at);
            CREATE TABLE IF NOT EXISTS sku_promotions (
                id TEXT PRIMARY KEY,
                sku TEXT NOT NULL,
                promotion_name TEXT NOT NULL DEFAULT '历史未命名促销',
                asin_snapshot TEXT NOT NULL DEFAULT '',
                developer_snapshot TEXT NOT NULL DEFAULT '',
                discount_percent INTEGER NOT NULL
                    CHECK (typeof(discount_percent) = 'integer' AND discount_percent BETWEEN 1 AND 99),
                rule_key TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (end_date IS NULL OR end_date >= start_date)
            );
            CREATE INDEX IF NOT EXISTS idx_sku_promotions_sku ON sku_promotions(sku);
            CREATE INDEX IF NOT EXISTS idx_sku_promotions_dates
                ON sku_promotions(start_date, end_date);
            CREATE TABLE IF NOT EXISTS sku_last_promotions (
                sku TEXT PRIMARY KEY,
                promotion_id TEXT NOT NULL,
                promotion_name TEXT NOT NULL,
                discount_percent INTEGER NOT NULL
                    CHECK (typeof(discount_percent) = 'integer' AND discount_percent BETWEEN 1 AND 99),
                start_date TEXT NOT NULL,
                end_date TEXT,
                updated_at TEXT NOT NULL,
                CHECK (end_date IS NULL OR end_date >= start_date)
            );
            CREATE INDEX IF NOT EXISTS idx_sku_last_promotions_updated_at
                ON sku_last_promotions(updated_at DESC);
            CREATE TABLE IF NOT EXISTS app_migrations (
                migration_key TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS batch_monitor_batches (
                batch_no TEXT PRIMARY KEY,
                artwork_completed_date TEXT,
                source_file_name TEXT NOT NULL DEFAULT '',
                source_file_hash TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS batch_monitor_skus (
                sku TEXT PRIMARY KEY,
                batch_no TEXT NOT NULL,
                de_price REAL CHECK (de_price IS NULL OR de_price > 0),
                fr_price REAL CHECK (fr_price IS NULL OR fr_price > 0),
                es_price REAL CHECK (es_price IS NULL OR es_price > 0),
                it_price REAL CHECK (it_price IS NULL OR it_price > 0),
                developer_snapshot TEXT NOT NULL DEFAULT '',
                monitor_basis TEXT NOT NULL DEFAULT 'historical_confirmed'
                    CHECK (monitor_basis IN ('historical_confirmed', 'creation_match')),
                created_at TEXT NOT NULL,
                FOREIGN KEY (batch_no) REFERENCES batch_monitor_batches(batch_no)
            );
            CREATE INDEX IF NOT EXISTS idx_batch_monitor_skus_batch
                ON batch_monitor_skus(batch_no);
            CREATE TABLE IF NOT EXISTS sku_first_shipments (
                sku TEXT PRIMARY KEY,
                shipment_no TEXT NOT NULL,
                asin TEXT NOT NULL,
                arrival_date TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sku_first_shipments_shipment
                ON sku_first_shipments(shipment_no);
            CREATE INDEX IF NOT EXISTS idx_sku_first_shipments_arrival
                ON sku_first_shipments(arrival_date);
            CREATE TABLE IF NOT EXISTS batch_monitor_imports (
                file_hash TEXT NOT NULL,
                import_type TEXT NOT NULL,
                file_name TEXT NOT NULL,
                stats_json TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                PRIMARY KEY (file_hash, import_type)
            );
            CREATE TABLE IF NOT EXISTS batch_monitor_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sku_launch_prices (
                sku TEXT PRIMARY KEY,
                de_price REAL CHECK (de_price IS NULL OR de_price > 0),
                fr_price REAL CHECK (fr_price IS NULL OR fr_price > 0),
                es_price REAL CHECK (es_price IS NULL OR es_price > 0),
                it_price REAL CHECK (it_price IS NULL OR it_price > 0),
                source_file_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sku_launch_prices_source
                ON sku_launch_prices(source_file_hash);
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
        if "sort_order" not in columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            rows = conn.execute("""SELECT id, status FROM tasks
                ORDER BY status, due_at IS NULL, due_at, created_at DESC""").fetchall()
            positions: dict[str, int] = {}
            for row in rows:
                position = positions.get(row["status"], 0)
                conn.execute("UPDATE tasks SET sort_order = ? WHERE id = ?", (position, row["id"]))
                positions[row["status"]] = position + 1
        conn.commit()
        _ensure_batch_prices_nullable(conn)
        conn.commit()
        _ensure_batch_monitor_schema(conn)
        conn.commit()
        _migrate_promotion_discount_constraint(conn)
        _ensure_promotion_name_column(conn)
        conn.commit()
        _reset_active_promotions_once(conn)
        conn.commit()
        _backfill_last_promotion_snapshots_once(conn)
        conn.commit()


def _ensure_batch_prices_nullable(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]: row
        for row in conn.execute("PRAGMA table_info(batch_monitor_skus)")
    }
    price_columns = ("de_price", "fr_price", "es_price", "it_price")
    if not columns or not any(int(columns[name]["notnull"]) for name in price_columns):
        return

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DROP INDEX IF EXISTS idx_batch_monitor_skus_batch")
        conn.execute("ALTER TABLE batch_monitor_skus RENAME TO batch_monitor_skus_legacy_prices")
        conn.execute(
            """CREATE TABLE batch_monitor_skus (
                sku TEXT PRIMARY KEY,
                batch_no TEXT NOT NULL,
                de_price REAL CHECK (de_price IS NULL OR de_price > 0),
                fr_price REAL CHECK (fr_price IS NULL OR fr_price > 0),
                es_price REAL CHECK (es_price IS NULL OR es_price > 0),
                it_price REAL CHECK (it_price IS NULL OR it_price > 0),
                developer_snapshot TEXT NOT NULL DEFAULT '',
                monitor_basis TEXT NOT NULL DEFAULT 'historical_confirmed'
                    CHECK (monitor_basis IN ('historical_confirmed', 'creation_match')),
                created_at TEXT NOT NULL,
                FOREIGN KEY (batch_no) REFERENCES batch_monitor_batches(batch_no)
            )"""
        )
        developer_expression = (
            "developer_snapshot" if "developer_snapshot" in columns else "''"
        )
        basis_expression = (
            "monitor_basis" if "monitor_basis" in columns else "'historical_confirmed'"
        )
        conn.execute(
            f"""INSERT INTO batch_monitor_skus
            (sku, batch_no, de_price, fr_price, es_price, it_price,
             developer_snapshot, monitor_basis, created_at)
            SELECT sku, batch_no, de_price, fr_price, es_price, it_price,
                   {developer_expression}, {basis_expression}, created_at
            FROM batch_monitor_skus_legacy_prices"""
        )
        conn.execute("DROP TABLE batch_monitor_skus_legacy_prices")
        conn.execute(
            "CREATE INDEX idx_batch_monitor_skus_batch ON batch_monitor_skus(batch_no)"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _ensure_batch_monitor_schema(conn: sqlite3.Connection) -> None:
    """Lock batch membership metadata and remove the obsolete first-seen date."""

    batch_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(batch_monitor_skus)")
    }
    shipment_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(sku_first_shipments)")
    }
    needs_batch_columns = (
        "developer_snapshot" not in batch_columns
        or "monitor_basis" not in batch_columns
    )
    needs_shipment_rebuild = "first_seen_at" in shipment_columns
    if not needs_batch_columns and not needs_shipment_rebuild:
        return

    if needs_shipment_rebuild and DB_PATH.exists():
        backup_dir = DB_PATH.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = (
            backup_dir
            / f"{DB_PATH.stem}-before-batch-monitor-schema-{timestamp}{DB_PATH.suffix}"
        )
        backup = sqlite3.connect(backup_path)
        try:
            conn.backup(backup)
        finally:
            backup.close()

    conn.execute("BEGIN IMMEDIATE")
    try:
        if "developer_snapshot" not in batch_columns:
            conn.execute(
                "ALTER TABLE batch_monitor_skus "
                "ADD COLUMN developer_snapshot TEXT NOT NULL DEFAULT ''"
            )
        if "monitor_basis" not in batch_columns:
            conn.execute(
                "ALTER TABLE batch_monitor_skus "
                "ADD COLUMN monitor_basis TEXT NOT NULL DEFAULT 'historical_confirmed' "
                "CHECK (monitor_basis IN ('historical_confirmed', 'creation_match'))"
            )

        if needs_shipment_rebuild:
            conn.execute("DROP INDEX IF EXISTS idx_sku_first_shipments_shipment")
            conn.execute("DROP INDEX IF EXISTS idx_sku_first_shipments_arrival")
            conn.execute(
                "ALTER TABLE sku_first_shipments "
                "RENAME TO sku_first_shipments_legacy_first_seen"
            )
            conn.execute(
                """CREATE TABLE sku_first_shipments (
                    sku TEXT PRIMARY KEY,
                    shipment_no TEXT NOT NULL,
                    asin TEXT NOT NULL,
                    arrival_date TEXT,
                    updated_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                """INSERT INTO sku_first_shipments
                (sku, shipment_no, asin, arrival_date, updated_at)
                SELECT sku, shipment_no, asin, arrival_date, updated_at
                FROM sku_first_shipments_legacy_first_seen"""
            )
            conn.execute("DROP TABLE sku_first_shipments_legacy_first_seen")
            conn.execute(
                "CREATE INDEX idx_sku_first_shipments_shipment "
                "ON sku_first_shipments(shipment_no)"
            )
            conn.execute(
                "CREATE INDEX idx_sku_first_shipments_arrival "
                "ON sku_first_shipments(arrival_date)"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _migrate_promotion_discount_constraint(conn: sqlite3.Connection) -> None:
    """Widen the legacy 5/8/10 promotion constraint without losing records."""

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'sku_promotions'"
    ).fetchone()
    table_sql = str(row["sql"] or "") if row else ""
    compact_sql = "".join(table_sql.lower().split())
    if "discount_percentin(5,8,10)" not in compact_sql:
        return

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DROP INDEX IF EXISTS idx_sku_promotions_sku")
        conn.execute("DROP INDEX IF EXISTS idx_sku_promotions_dates")
        conn.execute("ALTER TABLE sku_promotions RENAME TO sku_promotions_legacy_discount")
        conn.execute(
            """CREATE TABLE sku_promotions (
                id TEXT PRIMARY KEY,
                sku TEXT NOT NULL,
                promotion_name TEXT NOT NULL DEFAULT '历史未命名促销',
                asin_snapshot TEXT NOT NULL DEFAULT '',
                developer_snapshot TEXT NOT NULL DEFAULT '',
                discount_percent INTEGER NOT NULL
                    CHECK (typeof(discount_percent) = 'integer' AND discount_percent BETWEEN 1 AND 99),
                rule_key TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (end_date IS NULL OR end_date >= start_date)
            )"""
        )
        conn.execute(
            """INSERT INTO sku_promotions
            (id, sku, promotion_name, asin_snapshot, developer_snapshot, discount_percent, rule_key,
             start_date, end_date, created_at, updated_at)
            SELECT id, sku, ?, asin_snapshot, developer_snapshot, discount_percent, rule_key,
                   start_date, end_date, created_at, updated_at
            FROM sku_promotions_legacy_discount"""
            ,
            (HISTORY_PROMOTION_NAME,),
        )
        conn.execute("DROP TABLE sku_promotions_legacy_discount")
        conn.execute("CREATE INDEX idx_sku_promotions_sku ON sku_promotions(sku)")
        conn.execute(
            "CREATE INDEX idx_sku_promotions_dates ON sku_promotions(start_date, end_date)"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _ensure_promotion_name_column(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(sku_promotions)")}
    if "promotion_name" not in columns:
        conn.execute(
            "ALTER TABLE sku_promotions ADD COLUMN promotion_name TEXT NOT NULL "
            f"DEFAULT '{HISTORY_PROMOTION_NAME}'"
        )


def _backup_database(conn: sqlite3.Connection) -> Path:
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{DB_PATH.stem}-before-promotion-name-reset-{timestamp}{DB_PATH.suffix}"
    backup = sqlite3.connect(backup_path)
    try:
        conn.backup(backup)
    finally:
        backup.close()
    return backup_path


def _reset_active_promotions_once(conn: sqlite3.Connection) -> None:
    """Remove only the pre-name active records once, after backing up the database."""

    already_applied = conn.execute(
        "SELECT 1 FROM app_migrations WHERE migration_key = ?",
        (PROMOTION_NAME_MIGRATION,),
    ).fetchone()
    if already_applied:
        return

    reference_date = datetime.now(LOCAL_TIMEZONE).date().isoformat()
    active_count = conn.execute(
        """SELECT COUNT(*) AS count FROM sku_promotions
        WHERE start_date <= ? AND (end_date IS NULL OR end_date >= ?)""",
        (reference_date, reference_date),
    ).fetchone()["count"]
    if active_count:
        _backup_database(conn)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """DELETE FROM sku_promotions
            WHERE start_date <= ? AND (end_date IS NULL OR end_date >= ?)""",
            (reference_date, reference_date),
        )
        conn.execute(
            "INSERT INTO app_migrations (migration_key, applied_at) VALUES (?, ?)",
            (PROMOTION_NAME_MIGRATION, datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _backfill_last_promotion_snapshots_once(conn: sqlite3.Connection) -> None:
    """Seed the durable per-SKU last-promotion snapshot without changing history."""
    already_applied = conn.execute(
        "SELECT 1 FROM app_migrations WHERE migration_key = ?",
        (LAST_PROMOTION_SNAPSHOT_MIGRATION,),
    ).fetchone()
    if already_applied:
        return

    rows = conn.execute(
        """SELECT id, sku, promotion_name, discount_percent, start_date, end_date, updated_at
        FROM sku_promotions
        ORDER BY updated_at DESC, start_date DESC, id DESC"""
    ).fetchall()
    seen_skus: set[str] = set()
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for row in rows:
            sku = str(row["sku"])
            if sku in seen_skus:
                continue
            seen_skus.add(sku)
            conn.execute(
                """INSERT INTO sku_last_promotions
                (sku, promotion_id, promotion_name, discount_percent, start_date, end_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    sku,
                    str(row["id"]),
                    str(row["promotion_name"] or HISTORY_PROMOTION_NAME),
                    int(row["discount_percent"]),
                    str(row["start_date"]),
                    row["end_date"],
                    str(row["updated_at"] or timestamp),
                ),
            )
        conn.execute(
            "INSERT INTO app_migrations (migration_key, applied_at) VALUES (?, ?)",
            (LAST_PROMOTION_SNAPSHOT_MIGRATION, timestamp),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
