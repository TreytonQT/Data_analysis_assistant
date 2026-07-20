from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backend.db as db
import backend.todo_import as todo_import


class TodoImportTests(unittest.TestCase):
    def test_legacy_import_preserves_status_and_is_idempotent(self):
        payload = {
            "tasks": [
                {
                    "id": "legacy-1", "title": "每周任务", "notes": "说明", "status": "doing",
                    "reminderEnabled": True, "date": "2026-07-10", "time": "09:00",
                    "repeat": {"type": "weekly", "weekdays": [1, 4], "monthDays": []},
                    "nextReminderAt": "2026-07-13T01:00:00.000Z",
                    "createdAt": "2026-07-01T00:00:00.000Z", "updatedAt": "2026-07-10T00:00:00.000Z",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "todo.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            database = root / "app.db"
            with patch.object(db, "DB_PATH", database), patch.object(todo_import, "DB_PATH", database):
                first = todo_import.import_legacy_todo(source, backup=False)
                second = todo_import.import_legacy_todo(source, backup=False)
                with db.connect() as conn:
                    row = conn.execute("SELECT * FROM tasks WHERE id = 'legacy-1'").fetchone()
                self.assertEqual(first["imported"], 1)
                self.assertEqual(second["skipped"], 1)
                self.assertEqual(row["status"], "in_progress")
                self.assertEqual(json.loads(row["recurrence_days"]), [0, 3])


if __name__ == "__main__":
    unittest.main()
