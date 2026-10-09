"""Motivation vs Logic

Motivation: Captions are a projection of speech spans onto the source clock,
including spans left out of model payloads.
Logic: WebVTT and SRT cues use start_ms and end_ms. Cue text is the human text
field. No model is asked to rewrite a line. When a cue would still be on screen
as the next one starts, its end is cut to that start so two lines are never
shown at once; cues that start together are left as they are.
A span longer than two caption lines (2 x 42 characters) is split at word
boundaries into several cues; its time is shared by character count, so a
minute-long span never becomes one wall of text. An empty edited text falls back
to the transcript's own wording.
"""

from __future__ import annotations


def webvtt(spans: list[dict]) -> str:
    return _document(spans, separator=".")


def srt(spans: list[dict]) -> str:
    return _document(spans, separator=",")


def _document(spans: list[dict], *, separator: str) -> str:
    cues = []
    for span in _speech(spans):
        source = span.get("text") if isinstance(span.get("text"), str) and span.get("text").strip() else span.get("raw_text")
        text = _cue_text(source if isinstance(source, str) else "")
        if not text:
            continue
        start_ms, end_ms = _bounds(span)
        cues.extend(_split(start_ms, end_ms, text))
    # Bugs vs Fixes
    # Bug: Neighbouring spans overlap (the sample-clock estimate is coarse), so players stacked
    # two captions on screen.
    # Fix: End a cue where the next one begins when they overlap.
    for position in range(len(cues) - 1):
        start_ms, end_ms, text = cues[position]
        next_start = cues[position + 1][0]
        if start_ms < next_start < end_ms:
            cues[position] = (start_ms, next_start, text)
    lines: list[str] = []
    if separator == ".":
        lines.extend(["WEBVTT", ""])
    for index, (start_ms, end_ms, text) in enumerate(cues, start=1):
        lines.append(str(index))
        lines.append(f"{_stamp(start_ms, separator)} --> {_stamp(end_ms, separator)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _speech(spans: list[dict]) -> list[dict]:
    rows = [span for span in spans if isinstance(span, dict) and span.get("kind") == "speech"]
    rows.sort(key=lambda span: (span.get("start_ms") if isinstance(span.get("start_ms"), int) else 0, str(span.get("span_id"))))
    return rows


def _bounds(span: dict) -> tuple[int, int]:
    start = span.get("start_ms") if isinstance(span.get("start_ms"), int) and not isinstance(span.get("start_ms"), bool) else 0
    end = span.get("end_ms") if isinstance(span.get("end_ms"), int) and not isinstance(span.get("end_ms"), bool) else start
    if start < 0:
        start = 0
    if end <= start:
        end = start + 1
    return start, end


def _stamp(milliseconds: int, separator: str) -> str:
    hours, rem = divmod(milliseconds, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


LINE = 42


def _split(start_ms: int, end_ms: int, text: str) -> list[tuple[int, int, str]]:
    """Pack words into lines of at most LINE characters, then pair lines into cues.

    Each cue gets a share of the span's time proportional to its characters. A single word
    longer than LINE stays on its own line rather than being cut.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) > LINE and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) <= 2:
        return [(start_ms, end_ms, "\n".join(lines))]
    chunks = ["\n".join(lines[index : index + 2]) for index in range(0, len(lines), 2)]
    total = sum(len(chunk) for chunk in chunks)
    cues = []
    cursor = start_ms
    for index, chunk in enumerate(chunks):
        stop = end_ms if index == len(chunks) - 1 else cursor + max(1, round((end_ms - start_ms) * len(chunk) / total))
        cues.append((cursor, max(stop, cursor + 1), chunk))
        cursor = stop
    return cues


def _cue_text(value: str) -> str:
    cleaned = value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    cleaned = cleaned.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return " ".join(cleaned.split())
