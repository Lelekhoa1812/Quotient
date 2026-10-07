# Motivation vs Logic
# Motivation: Sonic timestamps are samples sent, mapped through the compaction table onto source time.
# Logic: Kept source intervals own a dense sample range. A sample index inverts to the source millisecond.

from __future__ import annotations

from dataclasses import dataclass

from media.pcm import SAMPLE_RATE


@dataclass(frozen=True)
class KeepInterval:
    source_start_ms: int
    source_end_ms: int
    sample_start: int
    sample_end: int


def ms_to_samples(ms: int, sample_rate: int = SAMPLE_RATE) -> int:
    return ms * sample_rate // 1000


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    ordered = sorted((start, end) for start, end in ranges if end > start)
    if not ordered:
        return []
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def build_table(
    duration_ms: int,
    omitted: list[tuple[int, int]],
    sample_rate: int = SAMPLE_RATE,
) -> list[KeepInterval]:
    cursor = 0
    kept: list[tuple[int, int]] = []
    for start, end in _merge(omitted):
        start = max(0, min(duration_ms, start))
        end = max(0, min(duration_ms, end))
        if start > cursor:
            kept.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration_ms:
        kept.append((cursor, duration_ms))
    table: list[KeepInterval] = []
    sample_cursor = 0
    for start, end in kept:
        count = ms_to_samples(end, sample_rate) - ms_to_samples(start, sample_rate)
        table.append(
            KeepInterval(
                source_start_ms=start,
                source_end_ms=end,
                sample_start=sample_cursor,
                sample_end=sample_cursor + count,
            )
        )
        sample_cursor += count
    return table


def source_ms_of_sample(index: int, table: list[KeepInterval], sample_rate: int = SAMPLE_RATE) -> int:
    if not table:
        raise IndexError("compaction table is empty")
    if index == table[-1].sample_end:
        return table[-1].source_end_ms
    for row in table:
        if row.sample_start <= index < row.sample_end:
            offset = index - row.sample_start
            source_sample = ms_to_samples(row.source_start_ms, sample_rate) + offset
            return source_sample * 1000 // sample_rate
    raise IndexError(f"sample {index} is outside the compaction table")


def map_sample_range(
    sample_start: int,
    sample_end: int,
    table: list[KeepInterval],
    sample_rate: int = SAMPLE_RATE,
) -> tuple[int, int]:
    return (
        source_ms_of_sample(sample_start, table, sample_rate),
        source_ms_of_sample(sample_end, table, sample_rate),
    )
