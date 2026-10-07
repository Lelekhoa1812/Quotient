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
