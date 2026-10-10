# Motivation vs Logic
# Motivation: A screen reaches the portal as copied text and a layout paragraph. Neither says what the
# screen was for while people were talking, and a layout paragraph reads as if it were the point.
# Logic: Build one payload per batch of screens: clipped screen text (the heading and the tail, where
# totals sit) plus the speech that overlaps the screen, sampled from both ends when the stretch is
# long. A model writes one reading per screen id. A reading is kept only when its id was sent, every
# cited line was in that screen's sample, and every quantity occurs in the screen text or those lines.
# A difference sentence is dropped on its own when it fails those checks; the reading can remain.

from __future__ import annotations

import re
import sys

from graph.digest import _clock
from graph.numbers import grounded
from registry.ids import SCREEN_USE

BATCH = 8
PAD_BEFORE_MS = 20_000
PAD_AFTER_MS = 8_000
MAX_LINES = 160
MAX_SAID_CHARS = 7000
MAX_LINE = 320
MAX_TEXT = 1800
HEAD = 700
_LEAK = re.compile(r"\bspan_ids?\b", re.IGNORECASE)
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)


def _clip(text: str) -> str:
    """Heading plus the tail. Totals on a record sit after the rows, so a head-only cut hides them."""
    kept = [line.strip() for line in (text or "").splitlines() if line.strip() and not _URL.search(line)]
    body = "\n".join(kept).strip()
    if len(body) <= MAX_TEXT:
        return body
    tail = MAX_TEXT - HEAD - 5
    return body[:HEAD].rstrip() + "\n...\n" + body[-tail:].lstrip()


def _sample(rows: list, limit: int) -> list:
    if len(rows) <= limit:
        return rows
    head = tail = 3
    if limit <= head + tail:
        step = len(rows) / limit
        return [rows[min(len(rows) - 1, int(index * step))] for index in range(limit)]
    middle = rows[head:len(rows) - tail]
    slots = limit - head - tail
    step = len(middle) / slots if middle else 1
    picked = [middle[min(len(middle) - 1, int(index * step))] for index in range(slots)] if middle else []
    return rows[:head] + picked + rows[-tail:]


def _line(span) -> dict:
    return {
        "id": span.id,
        "t": _clock(span.start_ms),
        "speaker": span.speaker_hypothesis_id or "unknown",
        "text": (span.text or "").strip()[:MAX_LINE],
    }


def _window(screen, speech: list) -> list:
    start, end = screen.start_ms - PAD_BEFORE_MS, screen.end_ms + PAD_AFTER_MS
    rows = [
        span for span in speech
        if span.start_ms is not None and span.start_ms < end and (span.end_ms or span.start_ms) > start
    ]
    # Lines in these recordings are short fragments. A line cap of a few dozen kept only the
    # start and end of a screen that stayed up for minutes, and dropped the stretch being explained.
    if len(rows) <= MAX_LINES and sum(len(span.text or "") for span in rows) <= MAX_SAID_CHARS:
        return rows
    limit = min(MAX_LINES, len(rows))
    while limit > 12 and sum(len(span.text or "") for span in _sample(rows, limit)) > MAX_SAID_CHARS:
        limit = int(limit * 0.75)
    return _sample(rows, limit)


def batches(screens: list, spans: list) -> list[dict]:
    """Payloads of at most BATCH screens, each with the lines the model is allowed to cite."""
    speech = sorted(
        (span for span in spans if getattr(span, "kind", None) == "speech" and (getattr(span, "text", "") or "").strip() and span.start_ms is not None),
        key=lambda span: span.start_ms,
    )
    ordered = sorted(screens, key=lambda screen: screen.start_ms)
    packs = []
    for offset in range(0, len(ordered), BATCH):
        group = ordered[offset:offset + BATCH]
        rows = []
        for screen in group:
            said = [_line(span) for span in _window(screen, speech)]
            rows.append({
                "id": screen.id,
                "t": _clock(screen.start_ms),
                "end": _clock(screen.end_ms),
                "kind": screen.kind,
                "title": (screen.title or "")[:200],
                "text": _clip(screen.text),
                "said": said,
            })
        packs.append({"screens": rows, "full": {screen.id: screen.text or "" for screen in group}, "spans": {span.id: span.text or "" for span in speech}})
    return packs


def ground_screen_uses(raw: dict | None, pack: dict) -> list[dict]:
    """Keep a reading only when its screen was in this pack, its citations were shown, and its figures occur there."""
    if not isinstance(raw, dict):
        return []
    sent = {row["id"]: row for row in pack["screens"]}
    full = pack["full"]
    span_text = pack["spans"]
    kept: list[dict] = []
    seen: set[str] = set()
    for item in raw.get("readings") or []:
        if not isinstance(item, dict):
            continue
        screen_id = item.get("id")
        reading = item.get("reading")
        row = sent.get(screen_id)
        if row is None or screen_id in seen or not isinstance(reading, str) or not reading.strip() or _LEAK.search(reading):
            continue
        shown = {line["id"] for line in row["said"]}
        cited = [span_id for span_id in (item.get("span_ids") or []) if isinstance(span_id, str) and span_id in shown]
        evidence = full.get(screen_id, "") + "\n" + "\n".join(span_text.get(span_id, "") for span_id in cited)
        text = reading.strip()
        if not grounded(text, evidence):
            continue
        differs = item.get("differs")
        differs = differs.strip() if isinstance(differs, str) and differs.strip() and not _LEAK.search(differs) else None
        if differs is not None:
            both = full.get(screen_id, "") + "\n" + "\n".join(span_text.get(span_id, "") for span_id in shown)
            if not cited or not grounded(differs, both):
                differs = None
        seen.add(screen_id)
        kept.append({"id": screen_id, "reading": text[:500], "span_ids": cited[:4], "differs": differs, "start_ms": _start_ms(row["t"])})
    return kept


def _start_ms(clock: str) -> int | None:
    parts = clock.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    return (int(parts[0]) * 60 + int(parts[1])) * 1000


def read_screens(screens: list, spans: list, call) -> list[dict]:
    """One checked reading per screen. A failed batch leaves the others; a failed pass leaves none from it."""
    if not screens:
        return []
    from loop.pool import map_ordered

    def one(pack: dict) -> list[dict]:
        try:
            turn = call(SCREEN_USE, {"screens": pack["screens"]})
        except Exception as exc:  # one batch failing must not drop the walkaway
            print(f"screen use skipped: {type(exc).__name__}", file=sys.stderr, flush=True)
            return []
        output = getattr(turn, "output", None) if turn is not None else None
        return ground_screen_uses(output if isinstance(output, dict) else None, pack)

    rows: list[dict] = []
    for group in map_ordered(one, batches(screens, spans)):
        rows.extend(group)
    return rows
