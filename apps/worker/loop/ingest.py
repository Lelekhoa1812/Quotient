# Motivation vs Logic
# Motivation: submit_meeting has an object key and no transcript. The worker has to
# build the ledger from that file before the publish gate can run.
# Logic: Resolve the key under derivatives/, pace Sonic on the slice PCM, send
# that same slice to Pegasus through S3, then return a Ledger. The full source
# file is never opened.

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from bedrock.wire import Transport
from graph.span import Span
from loop.pool import map_ordered
from loop.quality import Ledger
from media.clock import build_table
from media.compact import IndexedSpan
from media.pcm import write_pcm
from media.probe import classify_file, probe
from pegasus.client import PegasusClient
from pegasus.parts import pack_scenes
from registry.load import Registry
from sonic.client import SonicClient

LIVE_CEILING = 240
_BUCKET = "axion-meeting-probe-255834078973-apse2"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_object(object_key: str) -> Path:
    root = repo_root()
    derivatives = (root / "derivatives").resolve()
    candidate = (root / object_key).resolve()
    if candidate != derivatives and derivatives not in candidate.parents:
        raise FileNotFoundError("object key is outside derivatives")
    if not candidate.is_file():
        raise FileNotFoundError("media object is not on disk")
    return candidate


def assemble(path: Path, meeting_id: str, *, context: str | None = None) -> Ledger:
    info = probe(path)
    kind = classify_file(path)
    duration_ms = _duration_ms(info)
    # Bugs vs Fixes
    # Bug: PCM, silence detection, and the S3 put ran one after another, and
    # Sonic's real-time stream finished before Pegasus was even opened.
    # Fix: Prepare the file on three threads, then run Sonic and Pegasus together.
    pcm_path = path.with_suffix(".pcm")

    def prepare_pcm() -> None:
        _stage("pcm")
        write_pcm(path, pcm_path)

    def prepare_upload() -> str | None:
        if kind != "video":
            return None
        _stage("upload")
        return _put_object(path, f"derivatives/{meeting_id}-0.mp4")

    prepared = map_ordered(lambda fn: fn(), (prepare_pcm, lambda: _silence_ranges(path, duration_ms), prepare_upload))
    silent = prepared[1]
    uploaded = prepared[2]
    pcm = pcm_path.read_bytes()
    speech, silence = _timeline_from(meeting_id, duration_ms, silent)
    registry = Registry()
    transport = Transport()
    table = build_table(duration_ms, [])

    def run_sonic():
        _stage("sonic")
        client = SonicClient(registry, transport)
        return client.transcribe(
            pcm,
            meeting_id=meeting_id,
            speech_spans=speech,
            table=table,
            context=context,
        )

    def run_pegasus():
        _stage("pegasus")
        scenes = [(0, duration_ms)]
        parts = pack_scenes(scenes)

        def upload(part):
            if uploaded and part.index == 0 and part.source_start_ms == 0:
                return uploaded
            piece = _cut(path, part)
            return _put_object(piece, f"derivatives/{meeting_id}-{part.index}.mp4")

        client = PegasusClient(registry, transport)
        observed = client.analyze(parts, upload, meeting_id)
        if observed.incomplete:
            raise RuntimeError("Pegasus length continuation did not finish")
        # Bugs vs Fixes
        # Bug: A statement without start_ms became a note and was dropped, so
        # raw_transcript.video was empty while Pegasus had described the scene.
        # Fix: Return timed observations and untimed notes. Cross-modal pairing
        # still uses only the timed observations.
        return list(observed.observations), list(observed.notes)

    if kind == "video":
        spoken_pack, pegasus_pack = map_ordered(lambda fn: fn(), (run_sonic, run_pegasus))
        spoken, _seams = spoken_pack
        observations, notes = pegasus_pack
    else:
        spoken, _seams = run_sonic()
        observations = []
        notes = []
    _clamp(spoken, duration_ms)
    spans = list(spoken) + silence
    return Ledger(
        meeting_id=meeting_id,
        duration_ms=duration_ms,
        kind=kind,
        spans=spans,
        index=[
            IndexedSpan(
                id=span.id,
                kind=span.kind,
                start_ms=span.start_ms,
                end_ms=span.end_ms,
                overlap=bool(span.overlap),
            )
            for span in spans
        ],
        observations=observations,
        notes=notes,
    )


def _stage(name: str) -> None:
    print(f"analysis stage: {name}", file=sys.stderr, flush=True)


def _duration_ms(info: dict) -> int:
    raw = (info.get("format") or {}).get("duration")
    seconds = float(raw) if raw is not None else 0.0
    if seconds <= 0:
        raise RuntimeError("ffprobe did not report a duration")
    return int(round(seconds * 1000))


def _timeline(path: Path, meeting_id: str, duration_ms: int) -> tuple[list[Span], list[Span]]:
    silent = _silence_ranges(path, duration_ms)
    return _timeline_from(meeting_id, duration_ms, silent)


def _timeline_from(meeting_id: str, duration_ms: int, silent: list[tuple[int, int]]) -> tuple[list[Span], list[Span]]:
    speech_ranges = _complement(silent, duration_ms)
    if not speech_ranges:
        speech_ranges = [(0, duration_ms)]
    speech = [
        Span(
            id=f"{meeting_id}-vad-{index}",
            meeting_id=meeting_id,
            kind="speech",
            start_ms=start,
            end_ms=end,
            raw_text="",
        )
        for index, (start, end) in enumerate(speech_ranges)
        if end > start
    ]
    silence = [
        Span(
            id=f"{meeting_id}-silence-{index}",
            meeting_id=meeting_id,
            kind="silence",
            start_ms=start,
            end_ms=end,
            raw_text="",
        )
        for index, (start, end) in enumerate(silent)
        if end > start
    ]
    return speech, silence


def _silence_ranges(path: Path, duration_ms: int) -> list[tuple[int, int]]:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-35dB:d=0.4",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for line in (completed.stderr or "").splitlines():
        if "silence_start:" in line:
            start = _ms_field(line, "silence_start:")
        elif "silence_end:" in line and start is not None:
            end = _ms_field(line, "silence_end:")
            if end > start:
                ranges.append((max(0, start), min(duration_ms, end)))
            start = None
    if start is not None and duration_ms > start:
        ranges.append((start, duration_ms))
    return ranges


def _ms_field(line: str, label: str) -> int:
    tail = line.split(label, 1)[1].strip().split()[0]
    return int(float(tail) * 1000)


def _complement(ranges: list[tuple[int, int]], duration_ms: int) -> list[tuple[int, int]]:
    cursor = 0
    speech: list[tuple[int, int]] = []
    for start, end in ranges:
        if start > cursor:
            speech.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration_ms:
        speech.append((cursor, duration_ms))
    return speech


def _clamp(spans: list, duration_ms: int) -> None:
    for span in spans:
        span.start_ms = max(0, min(duration_ms - 1, span.start_ms))
        span.end_ms = max(span.start_ms + 1, min(duration_ms, span.end_ms))


def _cut(path: Path, part) -> Path:
    dest = path.with_name(f"{path.stem}-{part.index}{path.suffix}")
    start = part.source_start_ms / 1000
    duration = part.duration_ms / 1000
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(path),
            "-c",
            "copy",
            str(dest),
        ],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    return dest


def _put_object(path: Path, key: str) -> str:
    # Bugs vs Fixes
    # Bug: The object went up without a video content type, and Pegasus
    # answered that the video was unprocessable.
    # Fix: Set the object content type to video/mp4 on the upload.
    bucket = os.environ.get("QUOTIENT_MEDIA_BUCKET", _BUCKET).strip() or _BUCKET
    uri = f"s3://{bucket}/{key}"
    completed = subprocess.run(
        [
            "aws",
            "s3",
            "cp",
            str(path),
            uri,
            "--region",
            "ap-southeast-2",
            "--content-type",
            "video/mp4",
            "--only-show-errors",
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"S3 upload failed ({completed.returncode})")
    return uri
