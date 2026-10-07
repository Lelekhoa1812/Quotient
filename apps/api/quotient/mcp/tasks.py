"""Motivation vs Logic

Motivation: submit_meeting is long-running. MCP tasks let the client poll
without holding one HTTP request open for the whole job, and a task must not
be readable from a different authorization context.
Logic: TaskBoard stores tasks by id and subject. A missing id and a foreign
subject both surface as invalid params. Terminal transitions are one-way.
TTL expiry removes the row.
"""

from __future__ import annotations

import asyncio
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from quotient.mcp.errors import INVALID_PARAMS, RELATED_TASK, error

DEFAULT_TTL_MS = 3_600_000
MAX_TTL_MS = 86_400_000
MIN_TTL_MS = 1_000
POLL_INTERVAL_MS = 1000
MAX_CONCURRENT = 8
_TERMINAL = frozenset({"completed", "failed", "cancelled"})


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clamp_ttl(requested: object) -> int:
    if requested is None or isinstance(requested, bool) or not isinstance(requested, (int, float)):
        return DEFAULT_TTL_MS
    value = int(requested)
    if value < MIN_TTL_MS:
        return MIN_TTL_MS
    if value > MAX_TTL_MS:
        return MAX_TTL_MS
    return value


@dataclass
class TaskRecord:
    task_id: str
    auth_subject: str
    session_id: str
    status: str
    status_message: str
    created_at: str
    last_updated_at: str
    ttl_ms: int
    poll_interval_ms: int
    progress_token: str | int | None = None
    meeting_id: str | None = None
    progress: int = 0
    result: dict | None = None
    elicitation_id: str | None = None
    elicitation_body: dict | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    input_future: asyncio.Future | None = None

    def public(self) -> dict:
        payload = {
            "taskId": self.task_id,
            "status": self.status,
            "statusMessage": self.status_message,
            "createdAt": self.created_at,
            "lastUpdatedAt": self.last_updated_at,
            "ttl": self.ttl_ms,
            "pollInterval": self.poll_interval_ms,
        }
        return payload

    def terminal(self) -> bool:
        return self.status in _TERMINAL

    def touch(self, message: str | None = None) -> None:
        self.last_updated_at = utc_now()
        if message is not None:
            self.status_message = message

    def expired(self, now_ms: int | None = None) -> bool:
        del now_ms
        created = datetime.strptime(self.created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age_ms = (datetime.now(timezone.utc) - created).total_seconds() * 1000
        return age_ms > self.ttl_ms

    def complete_tool(self, payload: dict) -> None:
        if self.terminal():
            return
        self.status = "completed"
        self.result = payload
        self.touch(self.status_message)
        self.done.set()

    def fail_tool(self, message: str) -> None:
        if self.terminal():
            return
        self.status = "failed"
        self.result = tool_error(message)
        self.touch(message)
        self.done.set()

    def mark_cancelled(self, message: str) -> None:
        if self.terminal():
            return
        self.status = "cancelled"
        self.result = tool_error(message)
        self.touch(message)
        if self.input_future is not None and not self.input_future.done():
            self.input_future.set_result({"action": "cancel"})
        self.done.set()

    def mark_input_required(self, message: str, body: dict) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        self.input_future = loop.create_future()
        self.elicitation_id = str(body["id"])
        self.elicitation_body = body
        self.status = "input_required"
        self.touch(message)
        return self.input_future

    def mark_working(self, message: str) -> None:
        if self.terminal():
            return
        self.status = "working"
        self.elicitation_body = None
        self.touch(message)

    def result_message(self, request_id: object) -> dict:
        payload = dict(self.result or tool_error("Task result is unavailable."))
        meta = dict(payload.get("_meta") or {})
        meta[RELATED_TASK] = {"taskId": self.task_id}
        payload["_meta"] = meta
        return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def tool_text(structured: dict, *, is_error: bool = False) -> dict:
    import json

    return {
        "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
        "structuredContent": structured,
        "isError": is_error,
    }


def tool_error(message: str) -> dict:
    return tool_text({"error": message}, is_error=True)


class TaskBoard:
    def __init__(self) -> None:
        self._items: dict[str, TaskRecord] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        subject: str,
        session_id: str,
        ttl_ms: int,
        progress_token: str | int | None,
    ) -> TaskRecord:
        with self._lock:
            self._drop_expired_locked()
            active = [
                task
                for task in self._items.values()
                if task.auth_subject == subject and not task.terminal()
            ]
            if len(active) >= MAX_CONCURRENT:
                raise LimitError("Too many concurrent tasks for this authorization context.")
            now = utc_now()
            task = TaskRecord(
                task_id=secrets.token_urlsafe(24),
                auth_subject=subject,
                session_id=session_id,
                status="working",
                status_message="The operation is now in progress.",
                created_at=now,
                last_updated_at=now,
                ttl_ms=ttl_ms,
                poll_interval_ms=POLL_INTERVAL_MS,
                progress_token=progress_token,
            )
            self._items[task.task_id] = task
            return task

    def get(self, task_id: object, subject: str) -> TaskRecord | None:
        if not isinstance(task_id, str) or not task_id:
            return None
        with self._lock:
            self._drop_expired_locked()
            task = self._items.get(task_id)
            if task is None or task.auth_subject != subject:
                return None
            return task

    def for_meeting(self, subject: str, meeting_id: str) -> list[TaskRecord]:
        with self._lock:
            return [
                task
                for task in self._items.values()
                if task.auth_subject == subject and task.meeting_id == meeting_id
            ]

    def for_elicitation(self, subject: str, elicitation_id: str) -> TaskRecord | None:
        with self._lock:
            for task in self._items.values():
                if task.auth_subject == subject and task.elicitation_id == elicitation_id:
                    return task
        return None

    def list_for(self, subject: str, offset: int, page_size: int) -> tuple[list[TaskRecord], int | None]:
        with self._lock:
            self._drop_expired_locked()
            rows = [task for task in self._items.values() if task.auth_subject == subject]
        rows.sort(key=lambda task: task.created_at)
        page = rows[offset : offset + page_size]
        next_offset = offset + page_size if offset + page_size < len(rows) else None
        return page, next_offset

    def _drop_expired_locked(self) -> None:
        expired = [task_id for task_id, task in self._items.items() if task.expired()]
        for task_id in expired:
            del self._items[task_id]


class LimitError(Exception):
    pass


def missing_task(request_id: object, *, expired: bool = False) -> dict:
    message = "Failed to retrieve task: Task has expired" if expired else "Failed to retrieve task: Task not found"
    return error(INVALID_PARAMS, message, request_id)
