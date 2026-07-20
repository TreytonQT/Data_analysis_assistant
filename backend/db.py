from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "app.db"


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
            CREATE INDEX IF NOT EXISTS idx_sku_promotions_sku ON sku_promotions(sku);
            CREATE INDEX IF NOT EXISTS idx_sku_promotions_dates
                ON sku_promotions(start_date, end_date);
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
