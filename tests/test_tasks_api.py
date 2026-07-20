from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import backend.db as db
from backend.main import app


class TasksApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DB_PATH
        db.DB_PATH = Path(self.temp.name) / "tasks.db"
        db.initialize_database()
        self.client = TestClient(app)

    def tearDown(self):
        db.DB_PATH = self.original_db
        self.temp.cleanup()

    def task_payload(self, **overrides):
        return {
            "title": "检查库存",
            "notes": "补货前确认可售库存",
            "status": "todo",
            "due_at": "2030-07-11T09:00:00Z",
            "remind_at": "2030-07-10T09:00:00Z",
            "recurrence_type": "none",
            "recurrence_days": [],
            **overrides,
        }

    def test_create_transition_and_export(self):
        created = self.client.post("/api/tasks", json=self.task_payload()).json()
        self.assertEqual(created["status"], "todo")

        moved = self.client.post(f"/api/tasks/{created['id']}/transition", json={"status": "completed"})
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["status"], "completed")

        exported = self.client.get("/api/tasks/export.csv")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("检查库存", exported.text)

    def test_transition_places_task_at_top_of_destination(self):
        first = self.client.post("/api/tasks", json=self.task_payload(
            title="先完成", status="completed", due_at="2030-01-01T00:00:00Z", remind_at="2030-01-01T00:00:00Z"
        )).json()
        moving = self.client.post("/api/tasks", json=self.task_payload(
            title="待迁移", due_at="2030-02-01T00:00:00Z", remind_at="2030-02-01T00:00:00Z"
        )).json()
        self.client.post(f"/api/tasks/{moving['id']}/transition", json={"status": "completed"})

        completed = [task for task in self.client.get("/api/tasks").json() if task["status"] == "completed"]
        self.assertEqual([task["id"] for task in completed[:2]], [moving["id"], first["id"]])

    def test_drag_reorder_is_persisted(self):
        first = self.client.post("/api/tasks", json=self.task_payload(
            title="第一项", due_at="2030-01-01T00:00:00Z", remind_at="2030-01-01T00:00:00Z"
        )).json()
        second = self.client.post("/api/tasks", json=self.task_payload(
            title="第二项", due_at="2030-02-01T00:00:00Z", remind_at="2030-02-01T00:00:00Z"
        )).json()

        response = self.client.post(
            f"/api/tasks/{first['id']}/move", json={"status": "todo", "before_id": second["id"]}
        )
        self.assertEqual(response.status_code, 200)
        todos = [task for task in self.client.get("/api/tasks").json() if task["status"] == "todo"]
        self.assertEqual([task["id"] for task in todos[:2]], [first["id"], second["id"]])

    def test_completing_daily_task_keeps_one_record_until_next_occurrence(self):
        created = self.client.post("/api/tasks", json=self.task_payload(
            due_at="2030-07-11T09:00:00Z", remind_at="2030-07-10T09:00:00Z", recurrence_type="daily"
        )).json()
        completed = self.client.post(f"/api/tasks/{created['id']}/transition", json={"status": "completed"}).json()
        tasks = self.client.get("/api/tasks").json()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["id"], created["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["next_reminder_at"], "2030-07-11T09:00:00+00:00")

    def test_completing_overdue_recurring_task_schedules_next_future_cycle(self):
        created = self.client.post("/api/tasks", json=self.task_payload(
            due_at="2020-01-01T09:00:00Z", remind_at="2020-01-01T09:00:00Z",
            recurrence_type="weekly", recurrence_days=[0],
        )).json()

        completed = self.client.post(f"/api/tasks/{created['id']}/transition", json={"status": "completed"}).json()
        tasks = self.client.get("/api/tasks").json()

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["id"], created["id"])
        self.assertEqual(tasks[0]["status"], "completed")
        self.assertGreater(tasks[0]["next_reminder_at"], completed["completed_at"])

    def test_due_completed_recurring_task_reopens_as_current(self):
        created = self.client.post("/api/tasks", json=self.task_payload(
            status="completed", due_at="2020-01-01T09:00:00Z", remind_at="2020-01-02T09:00:00Z", recurrence_type="daily"
        )).json()

        tasks = self.client.get("/api/tasks").json()
        reopened = next(task for task in tasks if task["id"] == created["id"])
        self.assertEqual(reopened["status"], "current")
        self.assertEqual(reopened["due_at"], "2020-01-02T09:00:00Z")
        self.assertIsNone(reopened["next_reminder_at"])

    def test_due_todo_task_moves_to_current(self):
        created = self.client.post("/api/tasks", json=self.task_payload(
            due_at="2020-01-01T09:00:00Z", remind_at="2020-01-01T09:00:00Z"
        )).json()

        tasks = self.client.get("/api/tasks").json()
        current = next(task for task in tasks if task["id"] == created["id"])
        self.assertEqual(current["status"], "current")

    def test_old_completed_non_repeating_task_is_removed(self):
        created = self.client.post("/api/tasks", json=self.task_payload(
            due_at="2020-01-01T09:00:00Z", remind_at="2020-01-01T09:00:00Z"
        )).json()
        self.client.post(f"/api/tasks/{created['id']}/transition", json={"status": "completed"})

        self.assertNotIn(created["id"], [task["id"] for task in self.client.get("/api/tasks").json()])

    def test_notifications_include_due_task_and_can_be_marked_read(self):
        created = self.client.post("/api/tasks", json=self.task_payload(remind_at="2020-01-01T09:00:00Z")).json()
        notices = self.client.get("/api/notifications").json()
        self.assertEqual(notices[0]["id"], created["id"])
        self.assertEqual(self.client.post(f"/api/notifications/{created['id']}/read").status_code, 200)

    def test_import_tasks(self):
        response = self.client.post("/api/tasks/import", json=[self.task_payload(title="导入任务")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["imported"], 1)
