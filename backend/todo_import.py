from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.db import DB_PATH, connect, initialize_database

STATUS_MAP = {
    "todo": "todo",
    "current": "current",
    "doing": "in_progress",
    "paused": "snoozed",
    "done": "completed",
}
RECURRENCE_MAP = {"once": "none", "daily": "daily", "weekly": "weekly", "monthly": "monthly"}


def utc_iso(value: str | None) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def local_due(task: dict) -> str | None:
    date = str(task.get("date") or "").strip()
    if not date:
        return None
    time = str(task.get("time") or "09:00").strip()
    parsed = datetime.fromisoformat(f"{date}T{time}").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def mapped_weekdays(values: list[int]) -> list[int]:
    # Legacy JSON uses JavaScript weekday numbering (Sunday=0); Python uses Monday=0.
    return sorted({(int(value) + 6) % 7 for value in values if 0 <= int(value) <= 6})


def import_legacy_todo(path: Path, backup: bool = True) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("旧 Todo JSON 缺少 tasks 数组")
    initialize_database()
    if backup and DB_PATH.exists():
        backup_path = DB_PATH.with_name(f"{DB_PATH.stem}-before-todo-import{DB_PATH.suffix}")
        if not backup_path.exists():
            shutil.copy2(DB_PATH, backup_path)

    imported = skipped = 0
    counts: dict[str, int] = {}
    with connect() as conn:
        for legacy in tasks:
            task_id = str(legacy.get("id") or "").strip()
            title = str(legacy.get("title") or "").strip()
            if not task_id or not title:
                skipped += 1
                continue
            if conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone():
                skipped += 1
                continue
            status = STATUS_MAP.get(str(legacy.get("status")), "todo")
            repeat = legacy.get("repeat") if isinstance(legacy.get("repeat"), dict) else {}
            recurrence = RECURRENCE_MAP.get(str(repeat.get("type")), "none")
            recurrence_days = mapped_weekdays(repeat.get("weekdays") or []) if recurrence == "weekly" else sorted({int(value) for value in (repeat.get("monthDays") or []) if 1 <= int(value) <= 31}) if recurrence == "monthly" else []
            due_at = local_due(legacy)
            next_reminder = utc_iso(legacy.get("nextReminderAt"))
            reminder_enabled = bool(legacy.get("reminderEnabled"))
            remind_at = (next_reminder or due_at) if reminder_enabled else None
            created_at = utc_iso(legacy.get("createdAt")) or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            updated_at = utc_iso(legacy.get("updatedAt")) or created_at
            completed_at = utc_iso(legacy.get("statusChangedAt")) if status == "completed" else None
            conn.execute(
                """INSERT INTO tasks
                (id,title,notes,status,due_at,remind_at,recurrence_type,recurrence_days,next_reminder_at,
                 notification_read_at,created_at,updated_at,completed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id, title, str(legacy.get("notes") or ""), status, due_at, remind_at, recurrence,
                    json.dumps(recurrence_days), next_reminder if reminder_enabled else None,
                    completed_at if status == "completed" else None, created_at, updated_at, completed_at,
                ),
            )
            imported += 1
            counts[status] = counts.get(status, 0) + 1
    return {"source": str(path), "imported": imported, "skipped": skipped, "status_counts": counts}
