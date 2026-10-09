# Motivation vs Logic
# Motivation: Owners of actions, who held which position, and who spoke all need speaker turns. The
# diarizer (pyannote 3.1) needs torch 2.8, which has no wheels for the worker's Python 3.14.
# Logic: Run diarize_cli.py under a dedicated interpreter (QUOTIENT_DIARIZER_PYTHON, or the venv
# scripts/setup-diarizer.sh creates). Any failure (no interpreter, no token, timeout, bad output)
# returns None and the meeting proceeds without speakers: speaker labels are useful, not required.
# Each transcript span then takes the speaker with the largest time overlap.

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import sys
import tempfile
import wave
from pathlib import Path

SAMPLE_RATE = 16000


def _python() -> Path | None:
    configured = os.environ.get("QUOTIENT_DIARIZER_PYTHON", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(__file__).resolve().parents[3] / ".local" / "diarizer-venv" / "bin" / "python")
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _kill_group(process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        process.wait(timeout=5)
    except Exception:
        pass


def diarize_pcm(pcm: bytes, *, timeout_s: float | None = None, should_stop=None) -> list[tuple[int, int, str]] | None:
    """Speaker turns for 16 kHz mono 16-bit PCM, or None when diarization is unavailable."""
    python = _python()
    if python is None or not pcm or not os.environ.get("HF_TOKEN", "").strip():
        print("diarization skipped: diarizer or HF_TOKEN not configured", file=sys.stderr, flush=True)
        return None
    seconds = len(pcm) / (2 * SAMPLE_RATE)
    limit = timeout_s if timeout_s is not None else max(300.0, seconds * 1.5)
    with tempfile.TemporaryDirectory(prefix="quotient-diarize-") as directory:
        wav_path = Path(directory) / "audio.wav"
        out_path = Path(directory) / "turns.json"
        with wave.open(str(wav_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(pcm)
        try:
            process = subprocess.Popen(
                [str(python), str(Path(__file__).with_name("diarize_cli.py")), str(wav_path), str(out_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # its own process group, so a stop or a timeout takes down all of it
            )
        except OSError as exc:
            print(f"diarization skipped: {type(exc).__name__}", file=sys.stderr, flush=True)
            return None
        # Poll instead of blocking, so a cancelled meeting stops this too instead of running to the end.
        deadline = time.monotonic() + limit
        while True:
            try:
                process.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                reason = "timed out" if time.monotonic() > deadline else "cancelled" if should_stop is not None and should_stop() else None
                if reason:
                    _kill_group(process)
                    print(f"diarization skipped: {reason}", file=sys.stderr, flush=True)
                    return None
        if process.returncode != 0 or not out_path.is_file():
            print(f"diarization skipped: exit {process.returncode}", file=sys.stderr, flush=True)
            return None
        try:
            payload = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    raw = payload.get("turns") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        print("diarization skipped: unexpected output", file=sys.stderr, flush=True)
        return None
    turns = []
    for item in raw:
        if isinstance(item, list) and len(item) == 3 and isinstance(item[2], str):
            try:
                start, end = int(item[0]), int(item[1])
            except (TypeError, ValueError):
                continue
            if end > start >= 0:
                turns.append((start, end, item[2]))
    print(f"diarization: {len({t[2] for t in turns})} speakers, {len(turns)} turns", file=sys.stderr, flush=True)
    return turns or None


def attach_speakers(spans: list, turns: list[tuple[int, int, str]] | None) -> None:
    """Give each speech span the speaker who talks longest inside it; mark spans with two voices."""
    if not turns:
        return
    for span in spans:
        if span.kind != "speech" or span.start_ms is None or span.end_ms is None:
            continue
        talk: dict[str, int] = {}
        for start, end, name in turns:
            overlap = min(end, span.end_ms) - max(start, span.start_ms)
            if overlap > 0:
                talk[name] = talk.get(name, 0) + overlap
        if not talk:
            continue
        ranked = sorted(talk.items(), key=lambda item: -item[1])
        span.speaker_hypothesis_id = ranked[0][0]
        if len(ranked) > 1 and ranked[1][1] >= 0.3 * ranked[0][1]:
            span.overlap = True
