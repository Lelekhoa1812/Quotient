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
import tempfile
from pathlib import Path

from bedrock.wire import Transport, invalidate_iam
from graph.span import Span
from loop.pool import map_ordered
from loop.quality import Ledger
from media.clock import build_table
from media.compact import IndexedSpan
from media.pcm import write_pcm
from media.probe import classify_file, probe
from pegasus.client import PegasusClient, VisualNote
from pegasus.parts import pack_scenes
from registry.load import Registry
from sonic.client import SonicClient

_BUCKET = "axion-meeting-local"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


# Motivation vs Logic
# Motivation: ffmpeg and aws calls had no timeout, so a hung process left a meeting "working"
# forever and held its thread. Logic: Generous fixed ceilings (a long recording legitimately
# takes minutes); a timeout raises and the meeting fails with a plain message.
MEDIA_TIMEOUT_SECONDS = int(os.environ.get("QUOTIENT_MEDIA_TIMEOUT_SECONDS", "3600"))
UPLOAD_TIMEOUT_SECONDS = int(os.environ.get("QUOTIENT_UPLOAD_TIMEOUT_SECONDS", "1800"))


def _transcript_cache(scope: str | None, pcm: bytes, registry, context: str | None):
    """Per-owner, per-audio cache of finished transcription segments. Off unless local or configured."""
    from bedrock.limits import SONIC_HANDOFF_SAMPLES, SONIC_MODEL
    from registry.ids import SONIC
    from sonic.cache import TranscriptCache, cache_key

    directory = os.environ.get("QUOTIENT_TRANSCRIPT_CACHE_DIR", "").strip()
    if directory.lower() == "off" or not scope:
        return None
    if not directory:
        if os.environ.get("QUOTIENT_ENVIRONMENT", "").strip().lower() != "local":
            return None
        directory = str(repo_root() / ".local" / "run" / "transcripts")
    key = cache_key(
        scope, pcm, handoff=SONIC_HANDOFF_SAMPLES, model=SONIC_MODEL, version=registry.prompt(SONIC).version, context=context
    )
    return TranscriptCache(Path(directory), key)


def resolve_object(object_key: str) -> Path:
    root = repo_root()
    derivatives = (root / "derivatives").resolve()
    candidate = (root / object_key).resolve()
    if candidate != derivatives and derivatives not in candidate.parents:
        raise FileNotFoundError("object key is outside derivatives")
    if not candidate.is_file():
        raise FileNotFoundError("media object is not on disk")
    return candidate


def assemble(
    path: Path,
    meeting_id: str,
    *,
    context: str | None = None,
    progress_callback=None,
    should_stop=None,
    cache_scope: str | None = None,
) -> Ledger:
    # The extracted PCM is large and contains the full spoken meeting. Keep it
    # outside derivatives and remove it after success or any failed stage.
    with tempfile.TemporaryDirectory(prefix="quotient-audio-") as temporary:
        return _assemble(
            path,
            meeting_id,
            pcm_path=Path(temporary) / "audio.pcm",
            context=context,
            progress_callback=progress_callback,
            should_stop=should_stop,
            cache_scope=cache_scope,
        )


def _assemble(
    path: Path,
    meeting_id: str,
    *,
    pcm_path: Path,
    context: str | None = None,
    progress_callback=None,
    should_stop=None,
    cache_scope: str | None = None,
) -> Ledger:
    info = probe(path)
    kind = classify_file(path)
    duration_ms = _duration_ms(info)
    # Bugs vs Fixes
    # Bug: PCM, silence detection, and the S3 put ran one after another, and
    # Sonic's real-time stream finished before Pegasus was even opened.
    # Fix: Prepare the file on three threads, then run Sonic and Pegasus together.
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
    pegasus_bucket = os.environ.get("QUOTIENT_PEGASUS_BUCKET", "").strip()
    local_endpoint = os.environ.get("QUOTIENT_S3_ENDPOINT_URL", "").strip()
    if progress_callback:
        if kind == "video" and local_endpoint and not pegasus_bucket:
            progress_callback("Streaming audio transcription; visual analysis is unavailable on local MinIO")
        elif kind == "video":
            progress_callback("Transcribing audio and analyzing video in parallel")
        else:
            progress_callback("Streaming audio transcription")

    def run_sonic():
        _stage("sonic")
        client = SonicClient(registry, transport)
        client.should_stop = should_stop
        client.refresh_credentials = invalidate_iam
        client.cache = _transcript_cache(cache_scope, pcm, registry, context)
        return client.transcribe(
            pcm,
            meeting_id=meeting_id,
            speech_spans=speech,
            table=table,
            context=context,
        )

    def run_pegasus():
        # AWS Bedrock cannot read objects from a developer's local S3-compatible
        # endpoint, so never hand a MinIO URI to Pegasus. With QUOTIENT_PEGASUS_BUCKET
        # set, the parts go to that AWS bucket instead; otherwise visual analysis is skipped.
        if local_endpoint and not pegasus_bucket:
            _stage("pegasus_skipped_local_s3")
            note = VisualNote(
                id=f"{meeting_id}-note-local-s3",
                statement=(
                    "Visual analysis was skipped because the media is stored in a local S3-compatible "
                    "endpoint that Bedrock cannot access."
                ),
            )
            return [], [note]
        _stage("pegasus")
        scenes = [(0, duration_ms)]
        parts = pack_scenes(scenes)

        def upload(part):
            # The playback copy on MinIO is not readable by Bedrock, so it is only reused for AWS input.
            if uploaded and part.index == 0 and part.source_start_ms == 0 and not pegasus_bucket:
                return uploaded
            piece = _cut(path, part)
            return _put_object(piece, f"derivatives/{meeting_id}-{part.index}.mp4", aws_bucket=pegasus_bucket or None)

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

    def run_diarization():
        _stage("diarization")
        from media.diarize import diarize_pcm

        return diarize_pcm(pcm, should_stop=should_stop)

    # Diarization runs beside transcription (seconds versus real-time streaming) and is optional.
    if kind == "video":
        spoken_pack, pegasus_pack, turns = map_ordered(lambda fn: fn(), (run_sonic, run_pegasus, run_diarization))
        spoken, _seams = spoken_pack
        observations, notes = pegasus_pack
    else:
        spoken_pack, turns = map_ordered(lambda fn: fn(), (run_sonic, run_diarization))
        spoken, _seams = spoken_pack
        observations = []
        notes = []
    _clamp(spoken, duration_ms)
    from media.diarize import attach_speakers

    attach_speakers(spoken, turns)
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
        timeout=MEDIA_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0 and "silence_" not in (completed.stderr or ""):
        # A failed run used to read as "no silence found", so the whole file counted as speech.
        raise subprocess.CalledProcessError(completed.returncode, ["ffmpeg", "silencedetect"], stderr=completed.stderr)
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
        timeout=MEDIA_TIMEOUT_SECONDS,
    )
    return dest


def _put_object(path: Path, key: str, *, aws_bucket: str | None = None) -> str:
    # Bugs vs Fixes
    # Bug: The object went up without a video content type, and Pegasus
    # answered that the video was unprocessable.
    # Fix: Set the object content type to video/mp4 on the upload.
    if aws_bucket:
        # Pegasus input goes to a real AWS bucket with the normal AWS credential chain, never MinIO.
        bucket = aws_bucket
        endpoint = ""
    else:
        bucket = os.environ.get("QUOTIENT_MEDIA_BUCKET", "").strip()
        if not bucket:
            if os.environ.get("QUOTIENT_ENVIRONMENT", "").strip().lower() != "local":
                raise RuntimeError("QUOTIENT_MEDIA_BUCKET must be configured outside local development")
            bucket = _BUCKET
        endpoint = os.environ.get("QUOTIENT_S3_ENDPOINT_URL", "").strip()
    uri = f"s3://{bucket}/{key}"
    command = [
        "aws",
        "s3",
        "cp",
        str(path),
        uri,
        "--region",
        os.environ.get("AWS_REGION", "ap-southeast-2"),
    ]
    if endpoint:
        command.extend(["--endpoint-url", endpoint])
    command.extend(
        [
            "--content-type",
            "video/mp4",
            "--only-show-errors",
        ]
    )
    upload_env = None
    if endpoint:
        # MinIO credentials must not replace the worker's AWS identity. Bedrock
        # uses the normal process credential chain while this child alone gets
        # credentials for the developer's local S3-compatible service.
        access_key = os.environ.get("QUOTIENT_S3_ACCESS_KEY_ID", "")
        secret_key = os.environ.get("QUOTIENT_S3_SECRET_ACCESS_KEY", "")
        if bool(access_key) != bool(secret_key):
            raise RuntimeError("Local S3 credentials must include both access and secret keys")
        upload_env = os.environ.copy()
        if access_key and secret_key:
            upload_env["AWS_ACCESS_KEY_ID"] = access_key
            upload_env["AWS_SECRET_ACCESS_KEY"] = secret_key
            upload_env.pop("AWS_SESSION_TOKEN", None)
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=upload_env,
        timeout=UPLOAD_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        # Keep the failure useful without copying arbitrary CLI output into the
        # meeting's public failure message (which may contain account details).
        diagnostic = (completed.stderr or "").casefold()
        if "session has expired" in diagnostic or "expiredtoken" in diagnostic:
            reason = "AWS session expired; reauthenticate with `aws login`"
        elif "accessdenied" in diagnostic or "access denied" in diagnostic or "not authorized" in diagnostic:
            reason = "AWS credentials lack permission to upload the media object"
        elif "could not connect" in diagnostic or "connection timed out" in diagnostic:
            reason = "S3 endpoint could not be reached; check endpoint and network connectivity"
        else:
            reason = "check AWS credentials, bucket configuration, and upload permissions"
        raise RuntimeError(f"S3 upload failed: {reason}")
    return uri
