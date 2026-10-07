# Motivation vs Logic
# Motivation: Visual-idle spans are evidence for compaction. They are not a transcript.
# Logic: A frame is idle when both the absolute frame delta and the histogram distance are under threshold.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IdleSpan:
    id: str
    kind: str
    start_ms: int
    end_ms: int


def idle_spans(
    deltas: list[float],
    distances: list[float],
    *,
    frame_ms: int,
    delta_max: float,
    hist_max: float,
    prefix: str = "idle",
) -> list[IdleSpan]:
    if len(deltas) != len(distances):
        raise ValueError("frame delta and histogram distance sequences differ in length")
    flags = [
        delta < delta_max and distance < hist_max
        for delta, distance in zip(deltas, distances)
    ]
    spans: list[IdleSpan] = []
    index = 0
    while index < len(flags):
        if not flags[index]:
            index += 1
            continue
        end = index + 1
        while end < len(flags) and flags[end]:
            end += 1
        spans.append(
            IdleSpan(
                id=f"{prefix}-{len(spans)}",
                kind="visual-idle",
                start_ms=index * frame_ms,
                end_ms=end * frame_ms,
            )
        )
        index = end
    return spans


def frame_metrics(path: str, step: int = 1) -> tuple[list[float], list[float]]:
    """OpenCV frame-delta and Bhattacharyya histogram distance. Imported only when called."""
    import cv2

    capture = cv2.VideoCapture(path)
    previous = None
    deltas: list[float] = []
    distances: list[float] = []
    ordinal = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if ordinal % step:
                ordinal += 1
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if previous is not None:
                deltas.append(float(cv2.absdiff(gray, previous).mean()))
                hist_a = cv2.calcHist([previous], [0], None, [32], [0, 256])
                hist_b = cv2.calcHist([gray], [0], None, [32], [0, 256])
                cv2.normalize(hist_a, hist_a)
                cv2.normalize(hist_b, hist_b)
                distances.append(float(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_BHATTACHARYYA)))
            previous = gray
            ordinal += 1
    finally:
        capture.release()
    return deltas, distances
