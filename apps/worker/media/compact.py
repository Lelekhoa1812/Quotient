# Motivation vs Logic
# Motivation: Compaction may drop silence and visual idle from model payloads, and must not drop overlap.
# Logic: The timeline index keeps every original start and end. Omission is a flag, not a deletion.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexedSpan:
    id: str
    kind: str
    start_ms: int
    end_ms: int
    overlap: bool = False
    omitted: bool = False


def apply_omissions(spans: list[IndexedSpan], omit_ids: list[str]) -> list[IndexedSpan]:
    requested = set(omit_ids)
    indexed: list[IndexedSpan] = []
    for span in spans:
        # Overlap is protected even when the compaction model lists its id.
        drop = (
            span.id in requested
            and span.kind in {"silence", "visual-idle", "visual_idle"}
            and not span.overlap
            and span.kind != "overlap"
        )
        indexed.append(
            IndexedSpan(
                id=span.id,
                kind=span.kind,
                start_ms=span.start_ms,
                end_ms=span.end_ms,
                overlap=span.overlap,
                omitted=drop,
            )
        )
    return indexed


def payload_duration_ms(spans: list[IndexedSpan]) -> int:
    return sum(span.end_ms - span.start_ms for span in spans if not span.omitted)


def source_duration_ms(spans: list[IndexedSpan]) -> int:
    if not spans:
        return 0
    return max(span.end_ms for span in spans)
