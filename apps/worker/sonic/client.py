# Motivation vs Logic
# Motivation: USER and FINAL text have no timestamps. Source time is samples sent, mapped through compaction.
# Logic: Pace 512-sample frames at 32 ms, open a new Tokyo session at 6 minutes, and bind each text event to the open VAD span.

from __future__ import annotations

import base64
from dataclasses import dataclass

from bedrock.limits import (
    SONIC_FRAME_SAMPLES,
    SONIC_FRAME_SECONDS,
    SONIC_HANDOFF_SAMPLES,
    SONIC_MODEL,
    SONIC_REGION,
)
from graph.span import Span
from media.clock import map_sample_range
from registry.ids import SONIC


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
    def __init__(self, registry, transport, sleep=None, handoff_samples: int = SONIC_HANDOFF_SAMPLES):
        self.registry = registry
        self.transport = transport
        self.sleep = sleep if sleep is not None else _real_sleep
        self.handoff_samples = handoff_samples

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
            session = self.transport.open(model_id=SONIC_MODEL, region=SONIC_REGION)
            try:
                for event in self._preamble(prompt.body, history, context, session_id):
                    session.send(event)
                cursor = sample_lo
                pending = sample_lo
                chunk = pcm[sample_lo * 2 : sample_hi * 2]
                for frame_index, frame in enumerate(iter_frames(chunk)):
                    self.sleep(SONIC_FRAME_SECONDS)
                    responses = session.send(self._audio_frame(session_id, frame_index, frame))
                    cursor += len(frame) // 2
                    pending = self._collect(
                        responses, pending, cursor, meeting_id, session_id, speech_spans, table, spans, history
                    )
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
        return spans, seams

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
