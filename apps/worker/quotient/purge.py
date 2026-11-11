"""Remove test meetings from the shared store, leaving a tombstone so no process brings them back.

Motivation vs Logic
Motivation: The portal can only hide a meeting in the browser; nothing removed it from the store, so test meetings stayed
in the list for everyone. A plain delete would also be undone by the next save from any warm process that still holds the
row, so the removal has to be recorded.
Logic: plan() is pure: it decides which of the named meetings can go (not while queued or working) and returns the new
document with a tombstone for each. apply_to_store() backs up the stored document first, then writes the new one.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from quotient.seed import deleted_ids

ACTIVE = {"queued", "working"}


def plan(document: dict, meeting_ids: list[str]) -> tuple[dict, list[str], list[str], list[str]]:
    """(new document, removed, refused as still running, not found)."""
    rows = [row for row in document.get("meetings") or [] if isinstance(row, dict)]
    by_id = {row.get("meeting_id"): row for row in rows}
    removed, refused, missing = [], [], []
    for meeting_id in dict.fromkeys(meeting_ids):
        row = by_id.get(meeting_id)
        if row is None:
            missing.append(meeting_id)
        elif row.get("status") in ACTIVE:
            refused.append(meeting_id)
        else:
            removed.append(meeting_id)
    gone = set(removed)
    kept = [row for row in document.get("meetings") or [] if not (isinstance(row, dict) and row.get("meeting_id") in gone)]
    tombstones = sorted(deleted_ids(document) | gone)
    return {**document, "meetings": kept, "deleted": tombstones}, removed, refused, missing


def fetch(bucket: str, key: str) -> dict:
    fd, path = tempfile.mkstemp(prefix="purge-get-", suffix=".json")
    os.close(fd)
    try:
        subprocess.run(["aws", "s3api", "get-object", "--bucket", bucket, "--key", key, path], check=True, capture_output=True, text=True)
        return json.loads(Path(path).read_text(encoding="utf-8"))
    finally:
        Path(path).unlink(missing_ok=True)


def store(bucket: str, key: str, document: dict) -> None:
    fd, path = tempfile.mkstemp(prefix="purge-put-", suffix=".json")
    os.close(fd)
    try:
        Path(path).write_text(json.dumps(document, ensure_ascii=False, default=str), encoding="utf-8")
        subprocess.run(
            ["aws", "s3api", "put-object", "--bucket", bucket, "--key", key, "--body", path, "--content-type", "application/json"],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        Path(path).unlink(missing_ok=True)


def backup(document: dict, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"purge-backup-{time.strftime('%Y%m%dT%H%M%S')}.json"
    target.write_text(json.dumps(document, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return target
