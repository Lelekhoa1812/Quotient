# Motivation vs Logic
# Motivation: Transcription is paced in real time (about 6 minutes per segment). A failure at
# minute 54 of an 84-minute recording (an expired sign-in, a crash, a restart) used to discard
# every finished segment, because results were only kept when the whole analysis completed.
# Logic: Each fully transcribed segment is saved to disk, keyed by the exact audio, the owner, the
# model and prompt version, the segment bounds and the context names. A retry replays saved
# segments and streams only the missing ones. Different owners, different audio or a changed
# prompt never share an entry. Segments that lost a window to the provider are not saved, so a
# retry gets another chance at them. Files are private (0600) and old ones are pruned.

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

MAX_FILES = 25
MAX_AGE_SECONDS = 7 * 24 * 3600
FIELDS = ("kind", "start_ms", "end_ms", "raw_text", "coarse", "speaker_hypothesis_id", "overlap")


def cache_key(scope: str, pcm: bytes, *, handoff: int, model: str, version: object, context: str | None) -> str:
    digest = hashlib.sha256()
    for part in (scope, str(handoff), model, str(version), context or ""):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    digest.update(hashlib.sha256(pcm).digest())
    return digest.hexdigest()[:40]


class TranscriptCache:
    def __init__(self, root: Path, key: str) -> None:
        self.root = Path(root)
        self.path = self.root / f"{key}.json"
        self._data = self._read()

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, session_id: str, lo: int, hi: int) -> dict | None:
        entry = self._data.get(session_id)
        if isinstance(entry, dict) and entry.get("lo") == lo and entry.get("hi") == hi and isinstance(entry.get("spans"), list):
            return entry
        return None

    def put(self, session_id: str, lo: int, hi: int, spans: list[dict], history: list[str]) -> None:
        self._data[session_id] = {"lo": lo, "hi": hi, "spans": spans, "history": history}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix="t-", suffix=".json", dir=self.root)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            self._prune()
        except OSError:
            return  # a cache that cannot write must never fail the meeting

    def _prune(self) -> None:
        files = sorted(self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        cutoff = time.time() - MAX_AGE_SECONDS
        for index, item in enumerate(files):
            if index >= MAX_FILES or item.stat().st_mtime < cutoff:
                try:
                    item.unlink()
                except OSError:
                    pass


def span_items(spans: list) -> list[dict]:
    return [{name: getattr(span, name, None) for name in FIELDS} for span in spans]
