# Motivation vs Logic
# Motivation: The model emits a verbatim quote and does not emit character offsets.
# Logic: Exactly one contiguous hit in this meeting's span text writes the offsets. Zero or many hits stay unresolved.

from dataclasses import dataclass

from graph.span import Span


@dataclass(frozen=True)
class Resolution:
    status: str
    hits: int
    span_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    coarse: bool = False
    overlap: bool = False


def resolve_quote(quote: str, spans: list[Span], *, meeting_id: str, duration_ms: int) -> Resolution:
    if not quote:
        return Resolution(status="unresolved", hits=0)
    hits: list[tuple[Span, int]] = []
    for span in spans:
        if span.meeting_id != meeting_id:
            continue
        if span.start_ms < 0 or span.end_ms > duration_ms or span.start_ms >= span.end_ms:
            continue
        start = 0
        while True:
            index = span.text.find(quote, start)
            if index < 0:
                break
            hits.append((span, index))
            start = index + 1
    if len(hits) != 1:
        return Resolution(status="unresolved", hits=len(hits))
    span, index = hits[0]
    char_end = index + len(quote)
    if span.text[index:char_end] != quote:
        return Resolution(status="unresolved", hits=0)
    return Resolution(
        status="resolved",
        hits=1,
        span_id=span.id,
        char_start=index,
        char_end=char_end,
        start_ms=span.start_ms,
        end_ms=span.end_ms,
        coarse=span.coarse,
        overlap=span.overlap,
    )
