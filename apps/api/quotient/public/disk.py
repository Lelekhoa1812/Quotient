"""Motivation vs Logic

Motivation: An offline computer still has to remember the integration key and
its jobs. The deployed service uses DynamoDB instead.
Logic: One JSON document under .local/run. Readers see an empty document when
the file is missing. Writers replace the file atomically.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path


class Disk:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def read(self) -> dict:
        with self._lock:
            return self._read()

    def update(self, mutate: Callable[[dict], None]) -> None:
        with self._lock:
            document = self._read()
            mutate(document)
            self._write(document)

    def _read(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return {"keys": [], "jobs": []}
        if not isinstance(raw, dict):
            return {"keys": [], "jobs": []}
        keys = raw.get("keys") if isinstance(raw.get("keys"), list) else []
        jobs = raw.get("jobs") if isinstance(raw.get("jobs"), list) else []
        return {"keys": keys, "jobs": jobs}

    def _write(self, document: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="integration-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(document, handle, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def default_path() -> Path:
    return Path(__file__).resolve().parents[4] / ".local" / "run" / "integration.json"
