"""Motivation vs Logic

Motivation: The staging portal lists meetings from the API process, under the
subject stored on each row. That process starts empty, and a task replacement
drops every meeting a reviewer was looking at.
Logic: Read one JSON document from the artifacts bucket and install its rows.
Prioritize persistent state at state/meetings.json. If state/meetings.json is
missing, fall back to seed/meetings.json. Any changes made to meetings in memory
are saved back to state/meetings.json so they survive redeployments.
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
_DEFAULT_STATE_KEY = "state/meetings.json"
_MAX_BYTES = 32_000_000

Runner = Callable[..., object]


def load_into(port: object, env: Mapping[str, str] | None = None, *, run: Runner | None = None) -> int:
    document, source_key = read_state_or_seed(env, run=run)
    if document is None:
        return 0
    return install(port, document)


def read_state_or_seed(
    env: Mapping[str, str] | None = None,
    *,
    run: Runner | None = None,
) -> tuple[dict | None, str]:
    source = os.environ if env is None else env
    # If QUOTIENT_SEED_KEY is explicitly specified without QUOTIENT_STATE_KEY, honor it directly
    if "QUOTIENT_SEED_KEY" in source and "QUOTIENT_STATE_KEY" not in source and run is not None:
        key = source.get("QUOTIENT_SEED_KEY", "").strip() or _DEFAULT_KEY
        return read_remote(env, key=key, run=run), key

    state_key = source.get("QUOTIENT_STATE_KEY", "").strip() or _DEFAULT_STATE_KEY
    doc = read_remote(env, key=state_key, run=run)
    if doc is not None:
        return doc, state_key

    seed_key = source.get("QUOTIENT_SEED_KEY", "").strip() or _DEFAULT_KEY
    doc = read_remote(env, key=seed_key, run=run)
    if doc is not None:
        return doc, seed_key
    return None, ""


def read_remote(
    env: Mapping[str, str] | None = None,
    *,
    key: str | None = None,
    run: Runner | None = None,
) -> dict | None:
    source = os.environ if env is None else env
    if source.get("QUOTIENT_ENVIRONMENT", "").strip().lower() == "local":
        return None
    bucket = source.get("ARTIFACTS_BUCKET", "").strip()
    if not bucket:
        return None
    target_key = key or source.get("QUOTIENT_SEED_KEY", "").strip() or _DEFAULT_KEY
    runner = run or subprocess.run
    fd, temporary = tempfile.mkstemp(prefix="meeting-seed-", suffix=".json")
    os.close(fd)
    path = Path(temporary)
    try:
        try:
            result = runner(
                ["aws", "s3api", "get-object", "--bucket", bucket, "--key", target_key, str(path)],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            _note(f"meeting storage skipped: {type(exc).__name__}")
            return None
        code = getattr(result, "returncode", 1)
        if code:
            detail = f"{getattr(result, 'stderr', '')} {getattr(result, 'stdout', '')}"
            if "NoSuchKey" in detail or "Not Found" in detail or "404" in detail:
                return None
            _note("meeting storage skipped: the artifacts object could not be read")
            return None
        try:
            raw = path.read_bytes()
        except OSError as exc:
            _note(f"meeting storage skipped: {type(exc).__name__}")
            return None
        if len(raw) > _MAX_BYTES:
            _note("meeting storage skipped: the document is larger than limit")
            return None
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            _note("meeting storage skipped: the document is not JSON")
            return None
        if not isinstance(parsed, dict):
            _note("meeting storage skipped: the document is not an object")
            return None
        return parsed
    finally:
        path.unlink(missing_ok=True)


def save_remote_state(
    document: dict,
    env: Mapping[str, str] | None = None,
    *,
    key: str | None = None,
    run: Runner | None = None,
) -> bool:
    source = os.environ if env is None else env
    if source.get("QUOTIENT_ENVIRONMENT", "").strip().lower() == "local":
        return False
    bucket = source.get("ARTIFACTS_BUCKET", "").strip()
    if not bucket:
        return False
    target_key = key or source.get("QUOTIENT_STATE_KEY", "").strip() or _DEFAULT_STATE_KEY
    encoded = json.dumps(document, ensure_ascii=False, default=str)

    if run is None:
        try:
            import botocore.session
            from botocore.config import Config

            session = botocore.session.get_session()
            endpoint = source.get("QUOTIENT_S3_ENDPOINT_URL", "").strip() or None
            kwargs = {
                "region_name": source.get("AWS_REGION", "ap-southeast-2"),
                "config": Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    connect_timeout=5,
                    read_timeout=60,
                ),
            }
            if endpoint:
                kwargs.update(endpoint_url=endpoint)
            client = session.create_client("s3", **kwargs)
            client.put_object(
                Bucket=bucket,
                Key=target_key,
                Body=encoded.encode("utf-8"),
                ContentType="application/json",
            )
            return True
        except Exception as exc:
            _note(f"meeting state save via botocore failed: {type(exc).__name__}: {str(exc)[:100]}")

    runner = run or subprocess.run
    fd, temporary = tempfile.mkstemp(prefix="meeting-save-", suffix=".json")
    os.close(fd)
    path = Path(temporary)
    try:
        path.write_text(encoded, encoding="utf-8")
        result = runner(
            ["aws", "s3api", "put-object", "--bucket", bucket, "--key", target_key, "--body", str(path)],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
        code = getattr(result, "returncode", 1)
        if code:
            _note(f"meeting state remote save failed: {getattr(result, 'stderr', '')[:100]}")
            return False
        return True
    except Exception as exc:
        _note(f"meeting state remote save skipped: {type(exc).__name__}")
        return False
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
