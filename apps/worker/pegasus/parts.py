# Motivation vs Logic
# Motivation: Pegasus S3 input is limited to one hour. Scene-bounded parts stay under 50 minutes.
# Logic: Split any scene longer than the cap, then pack contiguous pieces without crossing the cap.

from dataclasses import dataclass

from bedrock.limits import PEGASUS_PART_MAX_MS


@dataclass(frozen=True)
class Part:
    index: int
    source_start_ms: int
    source_end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.source_end_ms - self.source_start_ms


def pack_scenes(scenes: list[tuple[int, int]], max_ms: int = PEGASUS_PART_MAX_MS) -> list[Part]:
    atoms: list[tuple[int, int]] = []
    for start, end in scenes:
        cursor = start
        while cursor < end:
            piece_end = min(end, cursor + max_ms)
            atoms.append((cursor, piece_end))
            cursor = piece_end
    if not atoms:
        return []
    packed: list[tuple[int, int]] = []
    part_start, part_end = atoms[0]
    for start, end in atoms[1:]:
        contiguous = start == part_end
        if contiguous and end - part_start <= max_ms:
            part_end = end
        else:
            packed.append((part_start, part_end))
            part_start, part_end = start, end
    packed.append((part_start, part_end))
    return [Part(index, start, end) for index, (start, end) in enumerate(packed)]


def window_parts(duration_ms: int, window_ms: int | None = None, min_tail_ms: int | None = None) -> list[Part]:
    """Contiguous windows of about window_ms covering the whole recording. A tail shorter than min_tail_ms joins
    the window before it, so no call carries a few seconds of video. Every window stays under the vendor cap."""
    from bedrock.limits import PEGASUS_WINDOW_MIN_TAIL_MS, PEGASUS_WINDOW_MS

    window = min(window_ms or PEGASUS_WINDOW_MS, PEGASUS_PART_MAX_MS)
    tail = PEGASUS_WINDOW_MIN_TAIL_MS if min_tail_ms is None else min_tail_ms
    if duration_ms <= 0:
        return []
    edges = list(range(0, duration_ms, window)) + [duration_ms]
    if len(edges) > 2 and edges[-1] - edges[-2] < tail and edges[-1] - edges[-3] <= PEGASUS_PART_MAX_MS:
        del edges[-2]
    return [Part(index, edges[index], edges[index + 1]) for index in range(len(edges) - 1)]
