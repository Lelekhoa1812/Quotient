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
        stdin=subprocess.DEVNULL,
        timeout=120,
    )
    return json.loads(completed.stdout)


def readable_duration_ms(path: str | Path, declared_ms: int) -> int:
    # Bugs vs Fixes
    # Bug: A truncated file keeps the original length in its header. The pipeline
    # then seeks pictures and builds a clock past the last byte that exists.
    # Fix: Use the last packet time when it ends more than 1.5 s before the header.
    if declared_ms <= 0:
        return declared_ms
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "packet=pts_time",
                "-of",
                "csv=p=0",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return declared_ms
    last = 0.0
    for line in completed.stdout.splitlines():
        piece = line.strip()
        if not piece or piece == "N/A":
            continue
        try:
            last = max(last, float(piece))
        except ValueError:
            continue
    if last <= 0:
        return declared_ms
    # The packet time is the start of the last packet. Keep a short tail so that packet is inside the clock.
    readable = int(round(last * 1000)) + 200
    if declared_ms - readable > 1500:
        return min(declared_ms, readable)
    return declared_ms


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
