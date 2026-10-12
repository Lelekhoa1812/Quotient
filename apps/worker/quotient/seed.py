"""Motivation vs Logic

Motivation: The staging portal lists meetings from the API process, under the
subject stored on each row. That process starts empty, and a task replacement
drops every meeting a reviewer was looking at.
Logic: Read one JSON document from the artifacts bucket and install its rows.
A missing object is an empty seed. A damaged object is reported and skipped so
the API still boots. A row already in memory is left alone. Export bytes are
not in the document, so a ready export is marked not run.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

_DEFAULT_KEY = "seed/meetings.json"
_MAX_BYTES = 16_000_000

Runner = Callable[..., object]


def load_into(port: object, env: Mapping[str, str] | None = None, *, run: Runner | None = None) -> int:
    document = read_remote(env, run=run)
    if document is None:
        return 0
    return install(port, document)


def read_remote(env: Mapping[str, str] | None = None, *, run: Runner | None = None) -> dict | None:
    source = os.environ if env is None else env
    if source.get("QUOTIENT_ENVIRONMENT", "").strip().lower() == "local":
        return None
    bucket = source.get("ARTIFACTS_BUCKET", "").strip()
    if not bucket:
        return None
    key = source.get("QUOTIENT_SEED_KEY", "").strip() or _DEFAULT_KEY
    runner = run or subprocess.run
    fd, temporary = tempfile.mkstemp(prefix="meeting-seed-", suffix=".json")
    os.close(fd)
    path = Path(temporary)
    try:
        try:
            result = runner(
                ["aws", "s3api", "get-object", "--bucket", bucket, "--key", key, str(path)],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            _note(f"meeting seed skipped: {type(exc).__name__}")
            return None
        code = getattr(result, "returncode", 1)
        if code:
            detail = f"{getattr(result, 'stderr', '')} {getattr(result, 'stdout', '')}"
            if "NoSuchKey" in detail or "Not Found" in detail or "404" in detail:
                return None
            _note("meeting seed skipped: the artifacts object could not be read")
            return None
        try:
            raw = path.read_bytes()
        except OSError as exc:
            _note(f"meeting seed skipped: {type(exc).__name__}")
            return None
        if len(raw) > _MAX_BYTES:
            _note("meeting seed skipped: the document is larger than 16 MB")
            return None
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            _note("meeting seed skipped: the document is not JSON")
            return None
        if not isinstance(parsed, dict):
            _note("meeting seed skipped: the document is not an object")
            return None
        return parsed
    finally:
        path.unlink(missing_ok=True)


def install(port: object, document: dict) -> int:
    rows = document.get("meetings")
    if not isinstance(rows, list):
        _note("meeting seed skipped: meetings is not a list")
        return 0
    installed = 0
    lock = getattr(port, "_lock", None)
    if lock is None:
        return _install(port, rows)
    with lock:
        installed = _install(port, rows)
    if installed:
        _note(f"meeting seed installed {installed}")
    return installed


def _install(port: object, rows: list) -> int:
    current = getattr(port, "_rows", None)
    index = getattr(port, "_idempotency", None)
    if not isinstance(current, dict) or not isinstance(index, dict):
        return 0
    installed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        meeting_id = row.get("meeting_id")
        subject = row.get("subject")
        if not isinstance(meeting_id, str) or not meeting_id or not isinstance(subject, str) or not subject:
            continue
        if meeting_id in current:
            continue
        stored = copy.deepcopy(row)
        artifacts = stored.get("artifacts")
        if isinstance(artifacts, dict) and artifacts.get("exports") == "ready":
            artifacts["exports"] = "not_run"
        current[meeting_id] = stored
        idem = stored.get("idempotency_key")
        if isinstance(idem, str) and idem:
            index[(subject, idem)] = meeting_id
        installed += 1
    return installed


def _note(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
