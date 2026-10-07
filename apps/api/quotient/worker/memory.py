"""Motivation vs Logic

Motivation: Partners can exercise MCP before the worker package is importable.
The ledger must record a meeting and human edits, and it must not run claim
extraction, entailment, or any model call.
Logic: Rows live in a process-local dict keyed by meeting id and bound to the
auth subject. submit returns immediately with status queued. settle exists so
a test or a later in-process adapter can move that status; it is not an MCP tool.
"""

from __future__ import annotations

import copy
import secrets
import threading
from datetime import datetime, timezone

from quotient.worker.port import ARTIFACT_KEYS, PortError


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pending_artifacts() -> dict[str, str]:
    return {key: "pending" for key in ARTIFACT_KEYS}


def _blank_meeting(*, meeting_id: str, subject: str, object_key: str, context_names: tuple[str, ...]) -> dict:
    return {
        "meeting_id": meeting_id,
        "subject": subject,
        "object_key": object_key,
        "context_names": list(context_names),
        "status": "queued",
        "prompt_release": None,
        "failure_message": None,
        "updated_at": _now(),
        "artifacts": _pending_artifacts(),
        "spans": [],
        "claims": [],
        "findings": [],
        "synthesis": [],
        "actions": [],
        "disagreements": [],
        "omissions": [],
        "none_in_transcript": [],
        "observations": [],
        "revisions": [],
    }


class MemoryPort:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}
        self._idempotency: dict[tuple[str, str], str] = {}

    def submit(
        self,
        *,
        subject: str,
        object_key: str,
        context_names: tuple[str, ...],
        idempotency_key: str | None,
    ) -> str:
        with self._lock:
            if idempotency_key:
                existing = self._idempotency.get((subject, idempotency_key))
                if existing:
                    return existing
            meeting_id = secrets.token_urlsafe(12)
            self._rows[meeting_id] = _blank_meeting(
                meeting_id=meeting_id,
                subject=subject,
                object_key=object_key,
                context_names=context_names,
            )
            if idempotency_key:
                self._idempotency[(subject, idempotency_key)] = meeting_id
            return meeting_id

    def meeting(self, meeting_id: str, subject: str) -> dict | None:
        with self._lock:
            row = self._rows.get(meeting_id)
            if row is None or row["subject"] != subject:
                return None
            return copy.deepcopy(row)

    def list_meetings(self, subject: str) -> list[dict]:
        with self._lock:
            rows = [row for row in self._rows.values() if row["subject"] == subject]
            rows.sort(key=lambda row: row["meeting_id"])
            return [copy.deepcopy(row) for row in rows]

    def accept_action(self, meeting_id: str, subject: str, action_id: str) -> dict:
        with self._lock:
            row = self._owned(meeting_id, subject)
            for action in row["actions"]:
                if action.get("action_id") != action_id:
                    continue
                acceptance = action.get("acceptance")
                if acceptance == "accepted":
                    row["updated_at"] = _now()
                    return copy.deepcopy(row)
                if acceptance != "proposed":
                    raise PortError("conflict", "Only a proposed action can be accepted.")
                action["acceptance"] = "accepted"
                action["origin"] = action.get("origin") or "model"
                row["updated_at"] = _now()
                return copy.deepcopy(row)
            raise PortError("not_found", "Action not found.")

    def revise_speaker(
        self,
        meeting_id: str,
        subject: str,
        span_id: str,
        scope: str,
        display_name: str,
    ) -> dict:
        with self._lock:
            row = self._owned(meeting_id, subject)
            anchor = next((span for span in row["spans"] if span.get("span_id") == span_id), None)
            if anchor is None:
                raise PortError("not_found", "Span not found.")
            hypothesis = anchor.get("speaker_hypothesis_id")
            if scope == "hypothesis":
                targets = [
                    span
                    for span in row["spans"]
                    if span.get("speaker_hypothesis_id") == hypothesis and hypothesis
                ]
                if not targets:
                    targets = [anchor]
            else:
                targets = [anchor]
                anchor["speaker_hypothesis_id"] = "hyp_" + secrets.token_urlsafe(8)
            for span in targets:
                span["speaker_display"] = display_name
            row["revisions"].append(
                {
                    "span_id": span_id,
                    "scope": scope,
                    "display_name": display_name,
                    "at": _now(),
                }
            )
            row["status"] = "working"
            for key in ("claims", "counterevidence", "entailment", "coverage", "exports"):
                row["artifacts"][key] = "pending"
            row["updated_at"] = _now()
            return copy.deepcopy(row)

    def cancel(self, meeting_id: str, subject: str) -> dict:
        with self._lock:
            row = self._owned(meeting_id, subject)
            row["status"] = "cancelled"
            row["updated_at"] = _now()
            return copy.deepcopy(row)

    def export_bytes(self, meeting_id: str, subject: str, name: str) -> tuple[str, bytes] | None:
        del meeting_id, subject, name
        return None

    def settle(
        self,
        meeting_id: str,
        *,
        status: str,
        graph: dict | None = None,
        prompt_release: str | None = None,
        failure_message: str | None = None,
    ) -> None:
        """Move a ledger row. Not an MCP tool and not a model loop."""

        with self._lock:
            row = self._rows.get(meeting_id)
            if row is None:
                raise PortError("not_found", "Meeting not found.")
            row["status"] = status
            row["updated_at"] = _now()
            if failure_message is not None:
                row["failure_message"] = failure_message
            if prompt_release is not None:
                row["prompt_release"] = prompt_release
            if graph:
                for key in (
                    "spans",
                    "claims",
                    "findings",
                    "synthesis",
                    "actions",
                    "disagreements",
                    "omissions",
                    "none_in_transcript",
                    "observations",
                ):
                    if key in graph:
                        row[key] = copy.deepcopy(graph[key])
            if status in {"ready", "needs_review"}:
                for key in ARTIFACT_KEYS:
                    row["artifacts"][key] = "ready"

    def _owned(self, meeting_id: str, subject: str) -> dict:
        row = self._rows.get(meeting_id)
        if row is None or row["subject"] != subject:
            raise PortError("not_found", "Meeting not found.")
        return row
