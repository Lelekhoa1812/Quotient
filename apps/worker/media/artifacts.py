# Motivation vs Logic
# Motivation: Names a person gave a voice are keyed to the diarizer's ids (spk_0, spk_1, ...), and the
# diarizer numbers voices by first appearance on every run. A re-analysis ("Reindex identity") therefore
# could attach a name to a different person, and it re-paid the video analysis every time.
# Logic: Keep the diarizer's turns and the visual scan of a recording on disk, keyed by the owner, the exact
# audio, and the settings that shaped them. A re-analysis of the same recording replays them, so voice ids
# stay the same and only the language-model stages run again. Files are private (0600) and old ones pruned.
# Off unless local or configured, like the transcript cache; a cache that cannot read or write never fails
# a meeting.

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

MAX_FILES = 60
MAX_AGE_SECONDS = 14 * 24 * 3600


def artifact_dir(scope: str | None) -> Path | None:
    configured = os.environ.get("QUOTIENT_TRANSCRIPT_CACHE_DIR", "").strip()
    if configured.lower() == "off" or not scope:
        return None
    if configured:
        return Path(configured) / "artifacts"
    if os.environ.get("QUOTIENT_ENVIRONMENT", "").strip().lower() != "local":
        return None
    return Path(__file__).resolve().parents[3] / ".local" / "run" / "artifacts"


def artifact_key(scope: str, kind: str, pcm: bytes, *settings: object) -> str:
    digest = hashlib.sha256()
    for part in (scope, kind, *[str(item) for item in settings]):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    digest.update(hashlib.sha256(pcm).digest())
    return digest.hexdigest()[:40]


class ArtifactCache:
    def __init__(self, root: Path | None, key: str) -> None:
        self.path = Path(root) / f"{key}.json" if root is not None else None

    @classmethod
    def for_audio(cls, scope: str | None, kind: str, pcm: bytes, *settings: object) -> "ArtifactCache":
        return cls(artifact_dir(scope), artifact_key(scope or "", kind, pcm, *settings))

    def get(self):
        if self.path is None:
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, value) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix="a-", suffix=".json", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            self._prune()
        except (OSError, TypeError, ValueError):
            return

    def _prune(self) -> None:
        files = sorted(self.path.parent.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        cutoff = time.time() - MAX_AGE_SECONDS
        for index, item in enumerate(files):
            if index >= MAX_FILES or item.stat().st_mtime < cutoff:
                try:
                    item.unlink()
                except OSError:
                    pass
