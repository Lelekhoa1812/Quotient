# Motivation vs Logic
# Motivation: Audio-only meetings must never call Pegasus, and video must call both models.
# Logic: ffprobe codec_type selects the plan. File extensions are not consulted.

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def probe(path: str | Path) -> dict:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return json.loads(completed.stdout)


def classify_streams(streams: list[dict]) -> str:
    kinds = {stream.get("codec_type") for stream in streams}
    if "video" in kinds:
        return "video"
    if "audio" in kinds:
        return "audio"
    raise ValueError("ffprobe found neither an audio nor a video stream")


def classify_file(path: str | Path) -> str:
    return classify_streams(probe(path).get("streams") or [])


def model_plan(kind: str) -> frozenset[str]:
    if kind == "audio":
        return frozenset({"sonic"})
    if kind == "video":
        return frozenset({"sonic", "pegasus"})
    raise ValueError(f"unknown media kind {kind!r}")
