"""Motivation vs Logic

Motivation: The meeting loop, model calls, and binary exporters belong to
apps/worker. The MCP process has to enqueue work and read projections without
copying that loop.
Logic: WorkerPort is the narrow surface. load_worker_port imports
apps/worker only when that tree exposes load_port(); any failure falls back
to the in-process ledger.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("quotient.worker")

ARTIFACT_KEYS = (
    "ledger",
    "claims",
    "counterevidence",
    "entailment",
    "coverage",
    "exports",
)

MEETING_STATUSES = (
    "queued",
    "working",
    "ready",
    "needs_review",
    "cancelled",
    "failed",
)


class PortError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WorkerPort(Protocol):
    """Sync surface the MCP server calls. submit must return without a model loop.

    meeting() returns a dict or None when the subject does not own the id.
    The dict keys the API reads are meeting_id, status, prompt_release,
    artifacts, failure_message, updated_at, spans, claims, findings,
    synthesis, actions, disagreements, omissions, none_in_transcript,
    observations.
    export_bytes returns (mime, body) when the worker already rendered a file.
    """

    def submit(
        self,
        *,
        subject: str,
        object_key: str,
        context_names: tuple[str, ...],
        idempotency_key: str | None,
    ) -> str: ...

    def meeting(self, meeting_id: str, subject: str) -> dict | None: ...

    def list_meetings(self, subject: str) -> list[dict]: ...

    def accept_action(self, meeting_id: str, subject: str, action_id: str) -> dict: ...

    def revise_speaker(
        self,
        meeting_id: str,
        subject: str,
        span_id: str,
        scope: str,
        display_name: str,
    ) -> dict: ...

    def revise_text(self, meeting_id: str, subject: str, span_id: str, text: str) -> dict: ...

    def cancel(self, meeting_id: str, subject: str) -> dict: ...

    def export_bytes(self, meeting_id: str, subject: str, name: str) -> tuple[str, bytes] | None: ...

    def media_url(self, meeting_id: str, subject: str) -> str | None: ...


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_file(path: Path) -> object | None:
    spec = importlib.util.spec_from_file_location(f"quotient_worker_{path.stem}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    load_port = getattr(module, "load_port", None)
    if not callable(load_port):
        return None
    return load_port()


def _import_worker_port() -> WorkerPort | None:
    root = _repo_root() / "apps" / "worker"
    if not root.is_dir():
        return None
    candidates = [root / "quotient" / "port.py", root / "port.py"]
    for path in candidates:
        if not path.is_file():
            continue
        loaded = _load_file(path)
        if loaded is not None:
            return loaded  # type: ignore[return-value]
    return None


def load_worker_port() -> WorkerPort:
    try:
        loaded = _import_worker_port()
    except Exception as exc:
        # Bugs vs Fixes
        # Bug: Any failure (for example a corrupt local meetings file) fell back to a ledger that
        # never runs analysis, so new meetings stayed "queued" forever with no visible cause.
        # Fix: In the local environment, fail startup loudly. Elsewhere keep the fallback, now on stderr.
        print(f"worker port failed to load: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr, flush=True)
        if os.environ.get("QUOTIENT_ENVIRONMENT", "").strip().lower() == "local":
            raise RuntimeError(
                "The local worker could not start (see the line above). Fix or move .local/run/meetings.json and start again."
            ) from exc
        loaded = None
    if loaded is None:
        from quotient.worker.memory import MemoryPort

        return MemoryPort()
    # Bugs vs Fixes
    # Bug: create_app binds the worker Port at startup and then stays silent.
    # The ledger fallback only calls logger.info, which uvicorn does not show,
    # so a process booted before load_port() existed could not be told apart
    # from one that file-loaded apps/worker/quotient/port.py.
    # Fix: Write the loaded type to stderr. No meeting text and no credentials.
    kind = f"{type(loaded).__module__}.{type(loaded).__name__}"
    print(f"worker port loaded: {kind}", file=sys.stderr, flush=True)
    return loaded
