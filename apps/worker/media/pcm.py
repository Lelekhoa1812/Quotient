# Motivation vs Logic
# Motivation: Nova 2.5 Sonic consumes 16 kHz mono 16-bit PCM while the source clock stays put.
# Logic: ffmpeg resamples without -ss or atrim. Sample index 0 is source time 0.

from __future__ import annotations

import subprocess
from pathlib import Path

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2


def ffmpeg_pcm_args(src: str | Path, dest: str | Path) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        str(dest),
    ]


def write_pcm(src: str | Path, dest: str | Path) -> int:
    # Bugs vs Fixes
    # Bug: ffmpeg inherited the terminal. A background API process group
    # received SIGTTIN and stayed stopped, so the PCM stage never finished.
    # Fix: Detach stdin. The source path is an argument, not a pipe.
    subprocess.run(
        ffmpeg_pcm_args(src, dest),
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    data = Path(dest).read_bytes()
    if len(data) % SAMPLE_WIDTH:
        raise ValueError("PCM byte length is not a whole number of 16-bit samples")
    return len(data) // SAMPLE_WIDTH
