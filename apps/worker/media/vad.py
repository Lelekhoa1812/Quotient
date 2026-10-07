# Motivation vs Logic
# Motivation: Speech and silence spans are numeric evidence. The model does not invent the timeline.
# Logic: Silero accepts 16 kHz only, in 512-sample (32 ms) windows. Contiguous probabilities become spans.

from __future__ import annotations

from dataclasses import dataclass

SAMPLE_RATE = 16000
WINDOW_SAMPLES = 512
WINDOW_MS = 32


@dataclass(frozen=True)
class VadSpan:
    id: str
    kind: str
    start_ms: int
    end_ms: int


def iter_windows(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> list[bytes]:
    if sample_rate != SAMPLE_RATE:
        raise ValueError("Silero VAD accepts 16 kHz only")
    frame = WINDOW_SAMPLES * 2
    if len(pcm) % 2:
        raise ValueError("PCM byte length is not a whole number of 16-bit samples")
    return [pcm[i : i + frame] for i in range(0, len(pcm) - frame + 1, frame)]


def spans_from_probabilities(
    probabilities: list[float],
    *,
    threshold: float = 0.5,
    meeting_prefix: str = "vad",
) -> list[VadSpan]:
    if not probabilities:
        return []
    spans: list[VadSpan] = []
    start = 0
    current = "speech" if probabilities[0] >= threshold else "silence"
    for index, probability in enumerate(probabilities + [None]):
        kind = None if probability is None else ("speech" if probability >= threshold else "silence")
        if kind == current:
            continue
        spans.append(
            VadSpan(
                id=f"{meeting_prefix}-{len(spans)}",
                kind=current,
                start_ms=start * WINDOW_MS,
                end_ms=index * WINDOW_MS,
            )
        )
        start = index
        current = kind or current
    return spans


def probabilities_from_model(pcm: bytes, model) -> list[float]:
    """model maps one 512-sample window (bytes) to a speech probability."""
    return [float(model(window)) for window in iter_windows(pcm)]
