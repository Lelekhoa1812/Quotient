# Motivation vs Logic
# Motivation: USER and FINAL text have no timestamps. Source time is samples sent, mapped through compaction.
# Logic: Pace 512-sample frames at 32 ms, open a new Tokyo session at 6 minutes, and bind each text event to the open VAD span.

from __future__ import annotations

import base64
import sys
import time
from dataclasses import dataclass

from bedrock.limits import (
    SONIC_FRAME_SAMPLES,
    SONIC_FRAME_SECONDS,
    SONIC_HANDOFF_SAMPLES,
    SONIC_MODEL,
    SONIC_REGION,
)
from errors import AnalysisCancelled, NotInvocable
from graph.span import Span
from media.clock import map_sample_range
from registry.ids import SONIC

try:  # h2 is only installed where the real transport runs
    from h2.exceptions import H2Error as _H2Error
except ImportError:  # pragma: no cover
    class _H2Error(Exception):
        pass

# Failures of one transcription window that a retry or a smaller window can get past.
_RECOVERABLE = (RuntimeError, TimeoutError, OSError, _H2Error)


def _permanent(error: BaseException) -> bool:
    """Configuration failures must fail the meeting, not turn into "not transcribed"."""
    if isinstance(error, NotInvocable):
        return True
    text = str(error)
    return "sonic HTTP 40" in text or "ResourceNotFound" in text


# A rejected segment is re-run in windows this long so only the rejected part is lost.
SUBWINDOW_SAMPLES = 90 * 16000


def _safe_ms(sample: int, table: list) -> int:
    """Source time of a sample; falls back to the plain sample clock if the table does not cover it."""
    from media.clock import source_ms_of_sample

    try:
        return int(source_ms_of_sample(sample, table))
    except (IndexError, ValueError):
        return int(sample * 1000 // 16000)


def plan_sessions(sample_count: int, handoff_samples: int = SONIC_HANDOFF_SAMPLES) -> list[tuple[int, int]]:
    if handoff_samples <= 0:
        raise ValueError("session handoff must be a positive sample count")
    sessions: list[tuple[int, int]] = []
    cursor = 0
    while cursor < sample_count:
        end = min(sample_count, cursor + handoff_samples)
        sessions.append((cursor, end))
        cursor = end
    return sessions


def iter_frames(pcm: bytes, frame_samples: int = SONIC_FRAME_SAMPLES) -> list[bytes]:
    width = frame_samples * 2
    return [pcm[index : index + width] for index in range(0, len(pcm), width)] if pcm else []


def transcript_text(event: dict) -> str | None:
    body = event.get("event", event)
    if not isinstance(body, dict) or "audioOutput" in body:
        return None
    text = body.get("textOutput")
    if not isinstance(text, dict):
        return None
    role = str(text.get("role", "")).upper()
    stage = str(text.get("stage") or text.get("type") or text.get("contentStage") or "").upper()
    if role == "ASSISTANT" or stage in {"PARTIAL", "SPECULATIVE"}:
        return None
    if role in {"USER", "FINAL"} or stage == "FINAL":
        content = text.get("content")
        return content if isinstance(content, str) and content else None
    return None


def bind_samples(sample_lo: int, sample_hi: int, speech_spans: list, table: list) -> dict:
    src_lo, src_hi = map_sample_range(sample_lo, sample_hi, table)
    open_spans = [
        span for span in speech_spans if span.start_ms < src_hi and span.end_ms > src_lo and span.kind == "speech"
    ]
    open_spans.sort(key=lambda span: (span.start_ms, span.end_ms))
    if len(open_spans) == 1:
        span = open_spans[0]
        if span.end_ms - span.start_ms > 60_000:
            # A single VAD region can be very long for continuous speech. Its
            # full bounds would assign every Sonic event the entire meeting;
            # use the sample-clock interval as a coarse local estimate.
            return {
                "start_ms": src_lo,
                "end_ms": max(src_hi, src_lo + 1),
                "coarse": True,
                "overlap": bool(getattr(span, "overlap", False)),
                "speaker_hypothesis_id": getattr(span, "speaker_hypothesis_id", None),
            }
        return {
            "start_ms": span.start_ms,
            "end_ms": span.end_ms,
            "coarse": False,
            "overlap": bool(getattr(span, "overlap", False)),
            "speaker_hypothesis_id": getattr(span, "speaker_hypothesis_id", None),
        }
    if len(open_spans) > 1:
        return {
            "start_ms": open_spans[0].start_ms,
            "end_ms": open_spans[-1].end_ms,
            "coarse": True,
            "overlap": any(bool(getattr(span, "overlap", False)) for span in open_spans),
            "speaker_hypothesis_id": _hypothesis_for(open_spans[0].start_ms, open_spans[-1].end_ms, open_spans),
        }
    return {
        "start_ms": src_lo,
        "end_ms": max(src_hi, src_lo + 1),
        "coarse": True,
        "overlap": False,
        "speaker_hypothesis_id": None,
    }


def _hypothesis_for(start_ms: int, end_ms: int, spans: list) -> str | None:
    best_id = None
    best = 0
    for span in spans:
        overlap = max(0, min(end_ms, span.end_ms) - max(start_ms, span.start_ms))
        hypothesis = getattr(span, "speaker_hypothesis_id", None)
        if hypothesis and overlap > best:
            best = overlap
            best_id = hypothesis
    return best_id


@dataclass
class Seam:
    session_index: int
    sample_start: int
    source_start_ms: int
    session_id: str


def _content(prompt_name: str, content_name: str, role: str, text: str, kind: str) -> list[dict]:
    return [
        {
            "event": {
                "contentStart": {
                    "promptName": prompt_name,
                    "contentName": content_name,
                    "type": "TEXT",
                    "interactive": False,
                    "role": role,
                    "textInputConfiguration": {"mediaType": "text/plain"},
                }
            }
        },
        {
            "event": {
                "textInput": {
                    "promptName": prompt_name,
                    "contentName": content_name,
                    "content": text,
                }
            }
        },
        {"event": {"contentEnd": {"promptName": prompt_name, "contentName": content_name}}},
    ]


class SonicClient:
    def __init__(self, registry, transport, sleep=None, handoff_samples: int = SONIC_HANDOFF_SAMPLES, clock=None):
        self.registry = registry
        self.transport = transport
        self.sleep = sleep if sleep is not None else _real_sleep
        self.clock = clock if clock is not None else time.monotonic
        self.handoff_samples = handoff_samples
        self.unavailable: list[tuple[str, str]] = []
        self.last_error = ""
        self.should_stop = None
        self.refresh_credentials = None
        self.cache = None

    def transcribe(
        self,
        pcm: bytes,
        *,
        meeting_id: str,
        speech_spans: list,
        table: list,
        context: str | None = None,
    ) -> tuple[list[Span], list[Seam]]:
        prompt = self.registry.prompt(SONIC)
        sample_count = len(pcm) // 2
        sessions = plan_sessions(sample_count, self.handoff_samples)
        spans: list[Span] = []
        seams: list[Seam] = []
        history: list[str] = []
        for index, (sample_lo, sample_hi) in enumerate(sessions):
            session_id = f"sonic-{index}"
            if index:
                from media.clock import source_ms_of_sample

                seams.append(
                    Seam(
                        session_index=index,
                        sample_start=sample_lo,
                        source_start_ms=source_ms_of_sample(sample_lo, table),
                        session_id=session_id,
                    )
                )
            # Motivation vs Logic
            # Motivation: Sessions are independent six-minute segments. A provider
            # rejection of one segment used to fail the whole meeting and discard
            # every segment already transcribed. Some rejections are transient
            # (retrying works); a content-filter rejection is deterministic for that
            # audio, so retrying the same six minutes only wastes them.
            # Logic: Retry a rejected segment once on a fresh session, dropping any
            # partial text. A content-filter rejection skips the retry. A segment
            # that still fails is re-run as 90-second windows with no history, so
            # only the windows the provider keeps rejecting are lost. Each lost
            # window becomes an "untranscribed" span with its source times; the
            # quality loop turns it into a coverage gap and the meeting finishes in
            # review with the missing parts named.
            if self.cache is not None:
                saved = self.cache.get(session_id, sample_lo, sample_hi)
                if saved is not None:
                    self._replay(saved, meeting_id, session_id, spans, history)
                    continue
            mark, history_mark = len(spans), len(history)
            clean = self._attempt(pcm, prompt, history, context, session_id, sample_lo, sample_hi,
                                  meeting_id, speech_spans, table, spans, tries=2)
            if not clean:
                clean = True
                for lo in range(sample_lo, sample_hi, SUBWINDOW_SAMPLES):
                    hi = min(lo + SUBWINDOW_SAMPLES, sample_hi)
                    if hi - lo < SONIC_FRAME_SAMPLES:
                        continue
                    if not self._attempt(pcm, prompt, [], context, session_id, lo, hi,
                                         meeting_id, speech_spans, table, spans, tries=1):
                        self._mark_untranscribed(spans, meeting_id, session_id, lo, hi, table)
                        clean = False
            if clean and self.cache is not None:
                from sonic.cache import span_items

                self.cache.put(session_id, sample_lo, sample_hi, span_items(spans[mark:]), list(history[history_mark:]))
        if sample_count and not any(span.kind == "speech" for span in spans) and self.unavailable:
            # Every window was rejected: a "finished" meeting with no transcript would read as
            # silence. Fail with the last cause instead.
            raise RuntimeError(f"nothing could be transcribed: {self.last_error}")
        return spans, seams

    def _replay(self, saved: dict, meeting_id: str, session_id: str, spans: list, history: list) -> None:
        """Rebuild a saved segment under this meeting's ids; no audio is streamed."""
        for item in saved["spans"]:
            spans.append(
                Span(
                    id=f"{meeting_id}-{session_id}-{len(spans)}",
                    meeting_id=meeting_id,
                    kind=item.get("kind") or "speech",
                    start_ms=item.get("start_ms") or 0,
                    end_ms=item.get("end_ms") or 0,
                    raw_text=item.get("raw_text") or "",
                    coarse=bool(item.get("coarse")),
                    session_id=session_id,
                    speaker_hypothesis_id=item.get("speaker_hypothesis_id"),
                    overlap=bool(item.get("overlap")),
                )
            )
        history.extend(text for text in saved.get("history") or [] if isinstance(text, str))
        print(f"sonic {session_id}: replayed {len(saved['spans'])} saved lines", file=sys.stderr, flush=True)

    def _attempt(self, pcm, prompt, history, context, session_id, lo, hi, meeting_id, speech_spans, table, spans, *, tries):
        """Run one window up to `tries` times. Returns True when it completed; leaves no partial text on failure.

        An HTTP 401/403 gets one extra attempt after the credentials are re-read, because long recordings
        outlive session credentials. If the sign-in itself has lapsed the retry fails the same way and the
        meeting fails with an actionable message.
        """
        refreshed = False
        attempt = 0
        while attempt < tries:
            mark, history_mark = len(spans), len(history)
            try:
                self._run_session(
                    pcm, prompt, history, context, session_id, lo, hi, meeting_id, speech_spans, table, spans
                )
                return True
            except _RECOVERABLE as error:
                del spans[mark:]
                del history[history_mark:]
                if _permanent(error):
                    if self.refresh_credentials is not None and not refreshed and "HTTP 40" in str(error):
                        refreshed = True
                        self.refresh_credentials()
                        print(f"sonic {session_id}: credentials re-read after {str(error)[:40]}", file=sys.stderr, flush=True)
                        continue  # same attempt number: the refresh buys one extra try
                    raise
                print(
                    f"sonic {session_id} [{lo // 16000}s-{hi // 16000}s] attempt {attempt + 1} failed after "
                    f"{len(spans) - mark} texts: {type(error).__name__}: {str(error)[:160]}",
                    file=sys.stderr,
                    flush=True,
                )
                self.last_error = str(error)[:200]
                attempt += 1
                if "content filter" in str(error).lower():
                    return False
        return False

    def _mark_untranscribed(self, spans, meeting_id, session_id, lo, hi, table):
        self.unavailable.append((f"{session_id}@{lo // 16000}s", self.last_error))
        spans.append(
            Span(
                id=f"{meeting_id}-{session_id}-untranscribed-{lo // 16000}",
                meeting_id=meeting_id,
                kind="untranscribed",
                start_ms=_safe_ms(lo, table),
                end_ms=max(_safe_ms(hi, table), _safe_ms(lo, table) + 1),
                raw_text="",
                coarse=True,
                session_id=session_id,
            )
        )

    def _run_session(
        self, pcm, prompt, history, context, session_id, sample_lo, sample_hi,
        meeting_id, speech_spans, table, spans,
    ):
        session = self.transport.open(model_id=SONIC_MODEL, region=SONIC_REGION)
        try:
            for event in self._preamble(prompt.body, history, context, session_id):
                session.send(event)
            cursor = sample_lo
            pending = sample_lo
            chunk = pcm[sample_lo * 2 : sample_hi * 2]
            # Pace against elapsed wall time so network and event handling
            # time count toward the audio clock instead of extending it.
            next_frame_at = self.clock()
            for frame_index, frame in enumerate(iter_frames(chunk)):
                if self.should_stop is not None and self.should_stop():
                    raise AnalysisCancelled()
                responses = session.send(self._audio_frame(session_id, frame_index, frame))
                cursor += len(frame) // 2
                pending = self._collect(
                    responses, pending, cursor, meeting_id, session_id, speech_spans, table, spans, history
                )
                next_frame_at += SONIC_FRAME_SECONDS
                delay = next_frame_at - self.clock()
                if delay > 0:
                    self.sleep(delay)
            session.send(
                {"event": {"contentEnd": {"promptName": session_id, "contentName": f"{session_id}-audio"}}}
            )
            session.send({"event": {"promptEnd": {"promptName": session_id}}})
            session.send({"event": {"sessionEnd": {}}})
            pending = self._collect(
                session.close(),
                pending,
                cursor,
                meeting_id,
                session_id,
                speech_spans,
                table,
                spans,
                history,
            )
        finally:
            closer = getattr(session, "release", None)
            if closer:
                closer()

    def _collect(self, responses, pending, cursor, meeting_id, session_id, speech_spans, table, spans, history):
        for response in responses or []:
            text = transcript_text(response)
            if text is None:
                continue
            if cursor <= pending:
                continue
            bound = bind_samples(pending, cursor, speech_spans, table)
            spans.append(
                Span(
                    id=f"{meeting_id}-{session_id}-{len(spans)}",
                    meeting_id=meeting_id,
                    kind="speech",
                    start_ms=bound["start_ms"],
                    end_ms=bound["end_ms"],
                    raw_text=text,
                    coarse=bound["coarse"],
                    session_id=session_id,
                    speaker_hypothesis_id=bound["speaker_hypothesis_id"],
                    overlap=bound["overlap"],
                )
            )
            history.append(text)
            pending = cursor
        return pending

    def _preamble(self, body: str, history: list[str], context: str | None, session_id: str) -> list[dict]:
        prompt_name = session_id
        # Bugs vs Fixes
        # Bug: An empty sessionStart is rejected by Nova 2.5 Sonic as invalid input,
        # so the bidirectional stream dies before any audio is accepted.
        # Fix: Send the required inference configuration. This cap is the Sonic
        # session limit, not the reasoning-model output ceiling.
        events = [
            {
                "event": {
                    "sessionStart": {
                        "inferenceConfiguration": {
                            "maxTokens": 1024,
                            "topP": 0.9,
                            "temperature": 0.7,
                        }
                    }
                }
            },
            {
                "event": {
                    "promptStart": {
                        "promptName": prompt_name,
                        "textOutputConfiguration": {"mediaType": "text/plain"},
                        "audioOutputConfiguration": {
                            "mediaType": "audio/lpcm",
                            "sampleRateHertz": 24000,
                            "sampleSizeBits": 16,
                            "channelCount": 1,
                            "voiceId": "matthew",
                            "encoding": "base64",
                            "audioType": "SPEECH",
                        },
                    }
                }
            },
        ]
        events.extend(_content(prompt_name, f"{session_id}-system", "SYSTEM", body, "system"))
        for ordinal, prior in enumerate(history):
            events.extend(_content(prompt_name, f"{session_id}-history-{ordinal}", "USER", prior, "history"))
        if context is not None:
            events.extend(_content(prompt_name, f"{session_id}-context", "USER", context, "context"))
        events.append(
            {
                "event": {
                    "contentStart": {
                        "promptName": prompt_name,
                        "contentName": f"{session_id}-audio",
                        "type": "AUDIO",
                        "interactive": True,
                        "role": "USER",
                        "audioInputConfiguration": {
                            "mediaType": "audio/lpcm",
                            "sampleRateHertz": 16000,
                            "sampleSizeBits": 16,
                            "channelCount": 1,
                            "audioType": "SPEECH",
                            "encoding": "base64",
                        },
                    }
                }
            }
        )
        return events

    def _audio_frame(self, session_id: str, frame_index: int, frame: bytes) -> dict:
        return {
            "event": {
                "audioInput": {
                    "promptName": session_id,
                    "contentName": f"{session_id}-audio",
                    "content": base64.b64encode(frame).decode("ascii"),
                }
            }
        }


def _real_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
