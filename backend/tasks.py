from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator

from backend.db import connect

router = APIRouter(prefix="/api", tags=["tasks"])
TaskStatus = Literal["todo", "current", "in_progress", "snoozed", "completed"]
RecurrenceType = Literal["none", "daily", "weekly", "monthly"]
STATUS_ORDER = {"todo": 0, "current": 1, "in_progress": 2, "snoozed": 3, "completed": 4}


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def as_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class TaskInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=5000)
    status: TaskStatus = "todo"
    due_at: datetime | None = None
    remind_at: datetime | None = None
    recurrence_type: RecurrenceType = "none"
    recurrence_days: list[int] = Field(default_factory=list)

    @field_validator("recurrence_days")
    @classmethod
    def valid_days(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 31 for day in value):
            raise ValueError("重复日期必须在 0 到 31 之间")
        return sorted(set(value))


class TransitionInput(BaseModel):
    status: TaskStatus
    remind_at: datetime | None = None


class MoveInput(BaseModel):
    status: TaskStatus
    before_id: str | None = None


def top_sort_order(conn, status: TaskStatus) -> int:
    row = conn.execute("SELECT MIN(sort_order) AS value FROM tasks WHERE status = ?", (status,)).fetchone()
    return (row["value"] if row and row["value"] is not None else 0) - 1


def serialize(row) -> dict:
    task = dict(row)
    task["recurrence_days"] = json.loads(task["recurrence_days"] or "[]")
    task["is_overdue"] = bool(
        task["due_at"] and task["status"] != "completed" and task["due_at"] < as_iso(now())
    )
    return task


def get_task(task_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(404, "任务不存在")
    return row


def next_occurrence(task: dict, base: datetime) -> datetime | None:
    kind = task["recurrence_type"]
    if kind == "none":
        return None
    if kind == "daily":
        return base + timedelta(days=1)
    if kind == "weekly":
        selected = task["recurrence_days"] or [base.weekday()]
        for offset in range(1, 8):
            candidate = base + timedelta(days=offset)
            if candidate.weekday() in selected:
                return candidate
    if kind == "monthly":
        days = task["recurrence_days"] or [base.day]
        year, month = base.year, base.month + 1
        if month == 13:
            year, month = year + 1, 1
        import calendar
        return base.replace(year=year, month=month, day=min(days[0], calendar.monthrange(year, month)[1]))
    return None


def next_future_occurrence(task: dict, base: datetime, reference: datetime | None = None) -> datetime | None:
    """Return the first scheduled occurrence strictly after ``reference``."""
    reference = reference or now()
    if base.tzinfo is None and reference.tzinfo is not None:
        reference = reference.replace(tzinfo=None)
    elif base.tzinfo is not None and reference.tzinfo is None:
        reference = reference.replace(tzinfo=base.tzinfo)

    occurrence = next_occurrence(task, base)
    while occurrence is not None and occurrence <= reference:
        occurrence = next_occurrence(task, occurrence)
    return occurrence


def apply_task_lifecycle() -> None:
    """Apply time-based task transitions before returning task data.

    A task stays in ``todo`` until its reminder time (or due time when no
    reminder is set), then automatically becomes ``current``.  Completed
    recurring tasks from legacy imports are reopened at ``next_reminder_at``.
    Non-recurring completed tasks are retained for one week after their set
    task time and then removed.
    """
    timestamp = as_iso(now())
    cleanup_before = as_iso(now() - timedelta(days=7))
    with connect() as conn:
        conn.execute("""DELETE FROM tasks WHERE status = 'completed' AND recurrence_type = 'none'
            AND COALESCE(remind_at, due_at, completed_at) IS NOT NULL
            AND COALESCE(remind_at, due_at, completed_at) <= ?""", (cleanup_before,))
        due_todos = conn.execute("""SELECT id FROM tasks
            WHERE status = 'todo' AND COALESCE(remind_at, due_at) IS NOT NULL
              AND COALESCE(remind_at, due_at) <= ? ORDER BY sort_order DESC""", (timestamp,)).fetchall()
        for row in due_todos:
            conn.execute("""UPDATE tasks SET status = 'current', next_reminder_at = NULL,
                updated_at = ?, sort_order = ? WHERE id = ?""",
                (timestamp, top_sort_order(conn, "current"), row["id"]))
        rows = conn.execute("""SELECT id, status, next_reminder_at FROM tasks
            WHERE recurrence_type != 'none' AND status IN ('todo', 'completed')
              AND next_reminder_at IS NOT NULL AND next_reminder_at <= ?
            ORDER BY sort_order DESC""", (timestamp,)).fetchall()
        for row in rows:
            next_due = next_reminder = row["next_reminder_at"]
            conn.execute("""UPDATE tasks SET status = 'current',
                due_at = ?, remind_at = ?,
                next_reminder_at = NULL, completed_at = NULL, notification_read_at = NULL,
                updated_at = ?, sort_order = ? WHERE id = ?""",
                (next_due, next_reminder, timestamp, top_sort_order(conn, "current"), row["id"]))


@router.get("/tasks")
def list_tasks(
    search: str | None = None,
    status: TaskStatus | None = None,
    due_from: datetime | None = None,
    due_to: datetime | None = None,
):
    apply_task_lifecycle()
    clauses, values = [], []
    if search:
        clauses.append("(title LIKE ? OR notes LIKE ?)")
        values.extend([f"%{search}%", f"%{search}%"])
    if status:
        clauses.append("status = ?")
        values.append(status)
    if due_from:
        clauses.append("due_at >= ?")
        values.append(as_iso(due_from))
    if due_to:
        clauses.append("due_at <= ?")
        values.append(as_iso(due_to))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM tasks{where} ORDER BY status, sort_order, created_at DESC", values).fetchall()
    return [serialize(row) for row in rows]


@router.post("/tasks", status_code=201)
def create_task(payload: TaskInput):
    timestamp = as_iso(now())
    task = {"id": str(uuid.uuid4()), **payload.model_dump(mode="json"), "created_at": timestamp, "updated_at": timestamp, "completed_at": None, "notification_read_at": None}
    task["recurrence_days"] = json.dumps(task["recurrence_days"])
    with connect() as conn:
        task["sort_order"] = top_sort_order(conn, payload.status)
        conn.execute("""INSERT INTO tasks (id,title,notes,status,due_at,remind_at,recurrence_type,recurrence_days,next_reminder_at,notification_read_at,created_at,updated_at,completed_at,sort_order)
            VALUES (:id,:title,:notes,:status,:due_at,:remind_at,:recurrence_type,:recurrence_days,:remind_at,:notification_read_at,:created_at,:updated_at,:completed_at,:sort_order)""", task)
    return serialize(get_task(task["id"]))


@router.put("/tasks/{task_id}")
def update_task(task_id: str, payload: TaskInput):
    old = get_task(task_id)
    values = payload.model_dump(mode="json")
    values["recurrence_days"] = json.dumps(values["recurrence_days"])
    values["updated_at"] = as_iso(now())
    values["id"] = task_id
    with connect() as conn:
        values["sort_order"] = top_sort_order(conn, payload.status) if payload.status != old["status"] else old["sort_order"]
        conn.execute("""UPDATE tasks SET title=:title,notes=:notes,status=:status,due_at=:due_at,remind_at=:remind_at,
            recurrence_type=:recurrence_type,recurrence_days=:recurrence_days,next_reminder_at=:remind_at,
            updated_at=:updated_at,sort_order=:sort_order WHERE id=:id""", values)
    return serialize(get_task(task_id))


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: str):
    get_task(task_id)
    with connect() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


@router.post("/tasks/{task_id}/transition")
def transition_task(task_id: str, payload: TransitionInput):
    old = serialize(get_task(task_id))
    timestamp = as_iso(now())
    fields = {"status": payload.status, "updated_at": timestamp, "completed_at": timestamp if payload.status == "completed" else None}
    if payload.remind_at:
        fields["remind_at"] = as_iso(payload.remind_at)
        fields["next_reminder_at"] = as_iso(payload.remind_at)
    if payload.status == "completed" and old["recurrence_type"] != "none":
        base = datetime.fromisoformat(old["remind_at"] or old["due_at"] or timestamp)
        occurrence = next_future_occurrence(old, base)
        fields["next_reminder_at"] = as_iso(occurrence)
    elif payload.status != "todo":
        fields["next_reminder_at"] = None
    with connect() as conn:
        fields["sort_order"] = top_sort_order(conn, payload.status) if payload.status != old["status"] else old["sort_order"]
        conn.execute("""UPDATE tasks SET status=:status, updated_at=:updated_at,
            completed_at=:completed_at, remind_at=COALESCE(:remind_at, remind_at),
            next_reminder_at=:next_reminder_at, sort_order=:sort_order WHERE id=:id""", {
                **fields,
                "id": task_id,
                "remind_at": fields.get("remind_at"),
                "next_reminder_at": fields.get("next_reminder_at"),
            })
    return serialize(get_task(task_id))


@router.post("/tasks/{task_id}/move")
def move_task(task_id: str, payload: MoveInput):
    task = get_task(task_id)
    if task["status"] != payload.status:
        raise HTTPException(409, "任务状态已变化，请刷新后重试")
    with connect() as conn:
        rows = conn.execute("""SELECT id FROM tasks
            WHERE status = ? AND id != ? ORDER BY sort_order, created_at DESC""",
            (payload.status, task_id)).fetchall()
        ordered_ids = [row["id"] for row in rows]
        if payload.before_id is not None:
            if payload.before_id not in ordered_ids:
                raise HTTPException(400, "目标任务不在当前状态中")
            ordered_ids.insert(ordered_ids.index(payload.before_id), task_id)
        else:
            ordered_ids.append(task_id)
        for position, ordered_id in enumerate(ordered_ids):
            conn.execute("UPDATE tasks SET sort_order = ? WHERE id = ?", (position, ordered_id))
    return serialize(get_task(task_id))


@router.get("/tasks/export.csv")
def export_tasks_csv():
    rows = list_tasks()
    output = io.StringIO()
    fields = ["id", "title", "notes", "status", "due_at", "remind_at", "recurrence_type", "recurrence_days", "created_at", "updated_at"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        row["recurrence_days"] = json.dumps(row["recurrence_days"])
        writer.writerow({key: row.get(key) for key in fields})
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=tasks.csv"})


@router.post("/tasks/import")
def import_tasks(tasks: list[TaskInput]):
    """Import a JSON array exported by an administrator or prepared offline."""
    for task in tasks:
        create_task(task)
    return {"imported": len(tasks)}


@router.get("/notifications")
def list_notifications():
    apply_task_lifecycle()
    current = as_iso(now())
    with connect() as conn:
        rows = conn.execute("""SELECT * FROM tasks WHERE status != 'completed' AND (remind_at <= ? OR due_at <= ?)
            ORDER BY COALESCE(remind_at, due_at), created_at DESC""", (current, current)).fetchall()
    return [serialize(row) for row in rows]


@router.post("/notifications/{task_id}/read")
def mark_notification_read(task_id: str):
    get_task(task_id)
    with connect() as conn:
        conn.execute("UPDATE tasks SET notification_read_at = ?, updated_at = ? WHERE id = ?", (as_iso(now()), as_iso(now()), task_id))
    return {"ok": True}
