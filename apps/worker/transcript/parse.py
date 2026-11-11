# Motivation vs Logic
# Motivation: A person may already hold the words of a meeting: a caption file (SRT, VTT), an export from Teams,
# Zoom or Otter, notes in Markdown, a Word or PDF minute. Those files differ in everything except that they are
# text, so each one has to become the same thing: an ordered list of utterances (who, when, what) that the
# analysis can treat like a transcribed recording.
# Logic: Read the file to plain text by format (captions by cue, DOCX from its XML, PDF with pypdf, the rest as
# text with encoding detection). Then find speaker turns with a small set of line shapes ("Name [00:12]: text",
# "[00:12] Name: text", "00:12 Name: text", "Name: text", a name line followed by text, "<v Name>" voice tags).
# A document with no speakers becomes paragraphs with no named voice. Long turns are cut at sentence ends so each
# span stays small enough to cite. Times are exact when the file has them and estimated from word count when it
# does not, and the result says which, so a chart never presents an invented time as a fact.

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

CAPTION_EXTENSIONS = frozenset({".srt", ".vtt"})
TEXT_EXTENSIONS = frozenset({".txt", ".md", ".markdown", ".text", ".log"})
DOCUMENT_EXTENSIONS = frozenset({".docx", ".pdf", ".html", ".htm", ".rtf", ".json"})
TRANSCRIPT_EXTENSIONS = CAPTION_EXTENSIONS | TEXT_EXTENSIONS | DOCUMENT_EXTENSIONS

MAX_CHARS = 2_000_000
MAX_PDF_PAGES = 2000
MAX_SPAN_CHARS = 700
WORDS_PER_SECOND = 2.5  # about 150 words a minute
MIN_UTTERANCE_MS = 1200
TURN_GAP_MS = 350
# Utterances that must carry a time before the file counts as timed.
TIMED_SHARE = 0.6


class TranscriptError(RuntimeError):
    """The file could not be read as a transcript; the message is safe to show a person."""


@dataclass
class Utterance:
    speaker: str | None
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    heading: bool = False


@dataclass
class Transcript:
    utterances: list[Utterance]
    timed: bool
    format: str
    title: str | None = None
    date_text: str | None = None
    speakers: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def duration_ms(self) -> int:
        return max((u.end_ms or 0 for u in self.utterances), default=0)


# ---------------------------------------------------------------------------------------------------------------
# Reading a file into text


def is_transcript_name(name: str) -> bool:
    return Path(name).suffix.lower() in TRANSCRIPT_EXTENSIONS


def read_text(path: Path) -> str:
    raw = path.read_bytes()[: MAX_CHARS * 4]
    for bom, encoding in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            return raw.decode(encoding, errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(path: Path) -> str:
    """Paragraph text of a Word file, read straight from its XML (no third-party code on the file)."""
    from context.convert import ConversionFailed, _zip_guard

    try:
        _zip_guard(path)
    except ConversionFailed as exc:
        raise TranscriptError("This Word file could not be read. It may be damaged or too large.") from exc
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise TranscriptError("This Word file could not be read. It may be damaged or password-protected.") from exc
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise TranscriptError("This Word file could not be read. It may be damaged.") from exc
    lines: list[str] = []
    for paragraph in root.iter(f"{_W}p"):
        parts: list[str] = []
        style = paragraph.find(f"{_W}pPr/{_W}pStyle")
        level = ""
        if style is not None:
            value = style.get(f"{_W}val") or ""
            match = re.match(r"(?i)heading\s*(\d)", value)
            if match or value.lower() == "title":
                level = "#" * (int(match.group(1)) if match else 1) + " "
        for node in paragraph.iter():
            if node.tag == f"{_W}t" and node.text:
                parts.append(node.text)
            elif node.tag in (f"{_W}tab",):
                parts.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
        line = "".join(parts).strip()
        if line:
            lines.append(level + line)
    return "\n".join(lines)


def pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return _converted(path)
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise TranscriptError("This PDF is password-protected.") from exc
        pages = []
        for index, page in enumerate(reader.pages):
            if index >= MAX_PDF_PAGES:
                break
            pages.append(page.extract_text() or "")
    except TranscriptError:
        raise
    except Exception as exc:  # noqa: BLE001 - any parser failure is one unreadable file
        raise TranscriptError("This PDF could not be read. It may be damaged.") from exc
    text = "\n".join(pages)
    if not text.strip():
        raise TranscriptError("No text was found in this PDF. A scanned PDF needs OCR first.")
    return text


def _converted(path: Path) -> str:
    from context.convert import ConversionFailed, ConverterUnavailable, to_markdown

    try:
        return to_markdown(path)[0]
    except (ConversionFailed, ConverterUnavailable) as exc:
        raise TranscriptError(str(exc)) from exc


def file_text(path: Path) -> str:
    extension = path.suffix.lower()
    if extension == ".docx":
        return docx_text(path)
    if extension == ".pdf":
        return pdf_text(path)
    if extension in {".html", ".htm"}:
        return _converted(path)
    if extension == ".rtf":
        return _rtf_text(read_text(path))
    if extension == ".json":
        return _json_text(read_text(path))
    return read_text(path)


def _rtf_text(raw: str) -> str:
    text = re.sub(r"\\par[d]?\s?", "\n", raw)
    text = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "replace"), text)
    text = re.sub(r"\{\\\*[^{}]*\}", "", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
    return re.sub(r"[{}]", "", text)


def _json_text(raw: str) -> str:
    """A JSON transcript export: a list (or {"segments"|"utterances"|"transcript": [...]}) of turns."""
    import json

    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise TranscriptError("This JSON file could not be read.") from exc
    if isinstance(data, dict):
        for key in ("segments", "utterances", "transcript", "results", "turns", "entries"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise TranscriptError("This JSON file does not look like a transcript.")
    lines = []
    for item in data:
        if isinstance(item, str):
            lines.append(item)
            continue
        if not isinstance(item, dict):
            continue
        text = next((item[k] for k in ("text", "content", "transcript", "message", "words") if isinstance(item.get(k), str)), "")
        if not text.strip():
            continue
        who = next((item[k] for k in ("speaker", "speaker_name", "name", "participant", "user") if isinstance(item.get(k), str)), "")
        start = next((item[k] for k in ("start", "start_time", "startTime", "offset", "timestamp") if isinstance(item.get(k), (int, float))), None)
        stamp = f"[{_clock(start)}] " if start is not None else ""
        lines.append(f"{stamp}{who}: {text}" if who else f"{stamp}{text}")
    return "\n".join(lines)


def _clock(seconds: float) -> str:
    seconds = int(seconds / 1000) if seconds > 100_000 else int(seconds)  # milliseconds or seconds
    return f"{seconds // 3600:d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


# ---------------------------------------------------------------------------------------------------------------
# Time stamps

_TS = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
_TS_RE = re.compile(_TS)


def parse_clock(value: str) -> int | None:
    parts = value.strip().replace(",", ".").split(":")
    try:
        if len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            seconds = int(parts[0]) * 60 + float(parts[1])
        else:
            return None
    except ValueError:
        return None
    return int(round(seconds * 1000))


# ---------------------------------------------------------------------------------------------------------------
# Captions

_CUE_TIME = re.compile(rf"^\s*(?P<a>{_TS})\s*-->\s*(?P<b>{_TS})")
_CUE_TAG = re.compile(r"<[^>]+>|\{\\[^}]*\}")
_VOICE = re.compile(r"<v(?:\.[\w.]+)?\s+([^>]+)>", re.IGNORECASE)
_BRACKET_NAME = re.compile(r"^\s*[\[(]([^\]\)]{2,40})[\])]\s*[:\-]?\s*(.*)$", re.DOTALL)
_NAME_COLON = re.compile(r"^\s*(?:>>\s*)?([A-Z][^:\n]{0,40}?):\s+(.+)$", re.DOTALL)
_NON_SPEECH = re.compile(r"^\s*[\[(♪][^\])]*[\])♪]\s*$")


def parse_captions(text: str) -> list[Utterance]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    blocks = re.split(r"\n{2,}", text)
    cues: list[Utterance] = []
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        for index, line in enumerate(lines):
            match = _CUE_TIME.match(line)
            if not match:
                continue
            start, end = parse_clock(match.group("a")), parse_clock(match.group("b"))
            body = "\n".join(lines[index + 1 :])
            if start is None or end is None or not body.strip():
                break
            speaker = None
            voice = _VOICE.search(body)
            if voice:
                speaker = voice.group(1).strip()
            body = " ".join(_CUE_TAG.sub("", body).split())
            if not body or _NON_SPEECH.match(body):
                break
            if speaker is None:
                found = _NAME_COLON.match(body) or _BRACKET_NAME.match(body)
                if found and _plausible_name(found.group(1)):
                    speaker, body = found.group(1).strip(), found.group(2).strip()
            cues.append(Utterance(speaker=speaker, text=body, start_ms=start, end_ms=max(end, start + 1)))
            break
    return _merge_cues(_drop_rolling(cues))


def _drop_rolling(cues: list[Utterance]) -> list[Utterance]:
    """Auto-captions repeat the previous line as the start of the next cue, or roll it forward one line.
    Keep each stretch of words once."""
    kept: list[Utterance] = []
    for cue in cues:
        if kept and cue.speaker == kept[-1].speaker:
            previous = kept[-1]
            if cue.text == previous.text or previous.text.startswith(cue.text):
                previous.end_ms = max(previous.end_ms or 0, cue.end_ms or 0)
                continue
            if cue.text.startswith(previous.text):
                previous.text = cue.text
                previous.end_ms = max(previous.end_ms or 0, cue.end_ms or 0)
                continue
            shared = _shared_words(previous.text, cue.text)
            if shared:
                cue = Utterance(cue.speaker, " ".join(cue.text.split()[shared:]), cue.start_ms, cue.end_ms)
                if not cue.text:
                    continue
        kept.append(cue)
    return kept


def _shared_words(previous: str, current: str) -> int:
    """How many words at the end of `previous` are the same as the start of `current` (at least three)."""
    a, b = previous.split(), current.split()
    for size in range(min(len(a), len(b)) - 1, 2, -1):
        if a[-size:] == b[:size]:
            return size
    return 0


def _merge_cues(cues: list[Utterance]) -> list[Utterance]:
    """A cue is a few seconds long. Cues from one voice that follow each other become one turn."""
    merged: list[Utterance] = []
    for cue in cues:
        last = merged[-1] if merged else None
        if (
            last is not None
            and last.speaker == cue.speaker
            and (cue.start_ms or 0) - (last.end_ms or 0) <= 1500
            and (cue.end_ms or 0) - (last.start_ms or 0) <= 60_000
            and len(last.text) + len(cue.text) < 1200
            and not (cue.speaker is None and re.search(r"[.?!]$", last.text) and len(last.text) > 160)
        ):
            last.text = f"{last.text} {cue.text}"
            last.end_ms = cue.end_ms
        else:
            merged.append(Utterance(cue.speaker, cue.text, cue.start_ms, cue.end_ms))
    return merged


# ---------------------------------------------------------------------------------------------------------------
# Free text: Markdown, plain text, Word and PDF

_EMPHASIS = re.compile(r"(\*\*|__|\*|_|`)")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s*([-*_=]\s*){3,}$")
_META = re.compile(r"^\s*(?:meeting\s+)?(date|time|location|attendees|participants|duration|recorded|subject|agenda|venue)\b\s*[:\-]\s*(.*)$", re.IGNORECASE)
_GENERIC_SPEAKER = re.compile(r"^(speaker|spk|participant|guest|unknown|host|moderator|interviewer|interviewee|q|a|male|female|man|woman|voice)[\s_\-]*\d*[A-Za-z]?$", re.IGNORECASE)

_LINE_PATTERNS = (
    # Name [00:12]: text   or   Name (00:12): text   or a bare "Name  0:12" line
    re.compile(rf"^(?P<name>[^\[\]():]{{1,60}}?)\s*[\[(]\s*(?P<ts>{_TS})\s*[\])]\s*[:\-–—]?\s*(?P<text>.*)$"),
    # [00:12] Name: text   or   (00:12) Name: text
    re.compile(rf"^[\[(]\s*(?P<ts>{_TS})\s*[\])]\s*[-–—]?\s*(?P<name>[^:\[\]]{{1,60}}?)\s*:\s*(?P<text>.*)$"),
    # 00:12 Name: text   or   00:12 - Name: text
    re.compile(rf"^(?P<ts>{_TS})\s*[-–—]?\s*(?P<name>[^:]{{1,60}}?)\s*:\s+(?P<text>.*)$"),
    # Name 00:12: text  /  Name - 00:12: text
    re.compile(rf"^(?P<name>[^:\d]{{1,60}}?)\s*[-–—]?\s+(?P<ts>{_TS})\s*:?\s*(?P<text>.*)$"),
)
_UNTIMED_LINE = re.compile(r"^(?:>>\s*)?(?P<name>[^:\n]{1,50}?)\s*:\s+(?P<text>\S.*)$")
_BARE_TS_LINE = re.compile(rf"^[\[(]?\s*(?P<ts>{_TS})\s*[\])]?\s*(?P<text>.*)$")


_LABEL_WORDS = frozenset({
    "note", "notes", "action", "action item", "action items", "decision", "decisions", "agenda", "summary", "todo", "to do", "next steps",
    "attendees", "participants", "question", "answer", "topic", "update", "risk", "risks", "issue", "owner", "due", "status", "re", "fyi", "ps",
    "warning", "important", "example", "source", "sources", "background", "context", "goal", "goals", "objective", "outcome", "outcomes",
    "follow up", "follow-up", "recap", "key points", "takeaways", "discussion", "location", "time", "date", "subject", "title", "description",
})


def _plausible_name(raw: str) -> bool:
    name = raw.strip()
    if _GENERIC_SPEAKER.match(name):
        return True
    if not name or len(name) > 50 or len(name.split()) > 5:
        return False
    if name.casefold() in _LABEL_WORDS:
        return False
    if re.search(r"[0-9@/\\=<>{}]|https?:|\.com", name):
        return False
    if not name[0].isalpha():
        return False
    if re.search(r"[.!?;]$", name):
        return False
    return True


def _normalise(line: str) -> str:
    line = line.replace("\t", " ").replace("\u00a0", " ")
    line = re.sub(r"^\s*>+\s*", "", line)
    line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+(?=[^\s].*:)", "", line)
    return _EMPHASIS.sub("", line).strip()


def parse_text(text: str) -> tuple[list[Utterance], str | None, str | None, bool]:
    """Utterances plus the document title and date text, and whether any speaker was recognised."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = text.split("\n")
    title: str | None = None
    date_text: str | None = None

    # First pass: how often does each candidate "Name:" occur? A lone "Note: ..." is prose, "Madison: ..." repeats.
    counts: dict[str, int] = {}
    for raw in raw_lines:
        line = _normalise(raw)
        match = _UNTIMED_LINE.match(line)
        if match and _plausible_name(match.group("name")):
            key = match.group("name").strip().casefold()
            counts[key] = counts.get(key, 0) + 1
    distinct_repeating = {name for name, n in counts.items() if n >= 2}
    content_lines = sum(
        1 for raw in raw_lines if raw.strip() and not _RULE.match(raw.strip()) and not _HEADING.match(raw) and not _META.match(_normalise(raw))
    )
    # When nearly every line is "Name: text" with two or more different names, the document is a dialogue, even a short one.
    dominant = len(counts) >= 2 and sum(counts.values()) >= 0.6 * max(1, content_lines)

    def untimed_speaker(name: str) -> bool:
        key = name.strip().casefold()
        return key in distinct_repeating or dominant or (bool(_GENERIC_SPEAKER.match(name.strip())) and len(counts) >= 2)

    utterances: list[Utterance] = []
    current: Utterance | None = None
    pending_heading: str | None = None

    def flush() -> None:
        nonlocal current
        if current is not None and current.text.strip():
            utterances.append(current)
        current = None

    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped or _RULE.match(stripped):
            if not stripped and current is not None and current.speaker is None and not current.heading:
                flush()  # a blank line ends an unattributed paragraph
            continue
        heading = _HEADING.match(raw)
        if heading:
            flush()
            label = _EMPHASIS.sub("", heading.group(2)).strip()
            if title is None and len(heading.group(1)) == 1:
                title = label
            elif label:
                pending_heading = label
            continue
        line = _normalise(raw)
        if not line:
            continue
        meta = _META.match(line)
        if meta and current is None:
            if meta.group(1).lower() in {"date", "meeting date", "recorded"} and date_text is None:
                date_text = meta.group(2).strip()
            continue

        speaker: str | None = None
        stamp: int | None = None
        body = ""
        matched = False
        for pattern in _LINE_PATTERNS:
            match = pattern.match(line)
            if match and _plausible_name(match.groupdict().get("name") or "x"):
                ts = parse_clock(match.group("ts"))
                if ts is None:
                    continue
                speaker, stamp, body, matched = match.group("name").strip(), ts, match.group("text").strip(), True
                break
        if not matched:
            match = _UNTIMED_LINE.match(line)
            if match and _plausible_name(match.group("name")) and untimed_speaker(match.group("name")):
                speaker, body, matched = match.group("name").strip(), match.group("text").strip(), True
        if not matched:
            bare = _BARE_TS_LINE.match(line)
            if bare and bare.group("text") and parse_clock(bare.group("ts")) is not None:
                # "00:12 some words": a time with no name.
                stamp, body, matched = parse_clock(bare.group("ts")), bare.group("text").strip(), True

        if matched:
            flush()
            if pending_heading and speaker is None:
                utterances.append(Utterance(None, pending_heading, heading=True))
            pending_heading = None
            current = Utterance(speaker=speaker, text=body, start_ms=stamp)
            continue

        # A continuation of the current turn, or a new unattributed paragraph.
        if current is not None and (current.speaker is not None or current.start_ms is not None):
            current.text = f"{current.text} {line}".strip()
        elif current is not None:
            current.text = f"{current.text} {line}".strip()
        else:
            if pending_heading:
                utterances.append(Utterance(None, pending_heading, heading=True))
                pending_heading = None
            current = Utterance(speaker=None, text=line)
    flush()

    has_speakers = any(u.speaker for u in utterances)
    # A paragraph that is only a name followed later by text ("Madison Schumann 00:00" alone) gets its text on the next lines;
    # drop name-only turns that never received text.
    utterances = [u for u in utterances if u.text.strip() or u.heading]
    return utterances, title, date_text, has_speakers


# ---------------------------------------------------------------------------------------------------------------
# Shaping


def _sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])", text.strip())
    return [piece for piece in pieces if piece.strip()]


def split_long(utterance: Utterance) -> list[Utterance]:
    """Cut a long turn at sentence ends so one span stays small. Times are shared out by length."""
    if len(utterance.text) <= MAX_SPAN_CHARS or utterance.heading:
        return [utterance]
    chunks: list[str] = []
    buffer = ""
    for sentence in _sentences(utterance.text) or [utterance.text]:
        while len(sentence) > MAX_SPAN_CHARS * 1.5:  # a wall of text with no sentence ends
            cut = sentence.rfind(" ", 0, MAX_SPAN_CHARS)
            cut = cut if cut > MAX_SPAN_CHARS // 2 else MAX_SPAN_CHARS
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if buffer and len(buffer) + 1 + len(sentence) > MAX_SPAN_CHARS:
            chunks.append(buffer)
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}".strip()
    if buffer:
        chunks.append(buffer)
    if len(chunks) <= 1:
        return [utterance]
    total = sum(len(c) for c in chunks) or 1
    pieces: list[Utterance] = []
    start, end = utterance.start_ms, utterance.end_ms
    cursor = start
    for index, chunk in enumerate(chunks):
        piece_start = cursor
        piece_end = end
        if start is not None and end is not None:
            share = int((end - start) * len(chunk) / total)
            piece_end = end if index == len(chunks) - 1 else piece_start + share
            cursor = piece_end
        elif start is not None:
            piece_end = None
            cursor = None if index else start
        pieces.append(Utterance(utterance.speaker, chunk, piece_start if start is not None else None, piece_end))
        if start is not None and end is None and index == 0:
            cursor = None
    if start is not None and end is None:
        # only the first piece keeps the stamp; the rest are placed by word count later
        for piece in pieces[1:]:
            piece.start_ms = None
    return pieces


def _estimate_ms(text: str) -> int:
    words = max(1, len(text.split()))
    return max(MIN_UTTERANCE_MS, int(words / WORDS_PER_SECOND * 1000))


def is_timed(utterances: list[Utterance]) -> bool:
    """Enough turns carry a time in the file for its times to be believed. Decided before long turns are cut."""
    body = [u for u in utterances if not u.heading]
    stamped = [u for u in body if u.start_ms is not None]
    return bool(body) and len(stamped) >= max(1, int(len(body) * TIMED_SHARE))


def place_in_time(utterances: list[Utterance], timed: bool) -> bool:
    """Give every utterance a start and end. `timed` says the file's own times are used. Returns it."""
    if not timed:
        cursor = 0
        for u in utterances:
            span = _estimate_ms(u.text) if not u.heading else MIN_UTTERANCE_MS
            u.start_ms, u.end_ms = cursor, cursor + span
            cursor += span + TURN_GAP_MS
        return False

    # A turn that has its own start and end (captions) keeps both. Otherwise a stamped turn, with the pieces cut from it
    # and any unstamped turns that follow, shares the time up to the next stamp, in proportion to their words.
    groups: list[list[Utterance]] = []
    for u in utterances:
        if u.start_ms is not None and (u.end_ms is not None or not groups or u.start_ms is not None):
            groups.append([u])
        elif groups:
            groups[-1].append(u)
        else:
            groups.append([u])
    previous_end = 0
    for index, group in enumerate(groups):
        first = group[0]
        if first.start_ms is None:
            first.start_ms = previous_end
        start = max(first.start_ms, 0)
        if len(group) == 1 and first.end_ms is not None:
            previous_end = max(previous_end, first.end_ms)
            continue
        following = next((g[0].start_ms for g in groups[index + 1 :] if g[0].start_ms is not None), None)
        weights = [_estimate_ms(u.text) if not u.heading else MIN_UTTERANCE_MS for u in group]
        wanted = sum(weights)
        total = wanted
        if following is not None and following > start:
            total = min(following - start, int(wanted * 1.6) + 2000)
        scale = total / wanted if wanted else 1.0
        cursor = start
        for u, weight in zip(group, weights):
            share = max(1, int(weight * scale))
            u.start_ms, u.end_ms = cursor, cursor + share
            cursor += share
        previous_end = max(previous_end, cursor)
    return True


def parse_transcript(path: Path) -> Transcript:
    """Read any supported file into a Transcript. Raises TranscriptError with a plain message."""
    extension = path.suffix.lower()
    if extension not in TRANSCRIPT_EXTENSIONS:
        raise TranscriptError("This file type is not supported as a transcript.")
    text = file_text(path)
    truncated = len(text) > MAX_CHARS
    text = text[:MAX_CHARS]
    if not text.strip():
        raise TranscriptError("No readable text was found in this file.")

    title = date_text = None
    if extension in CAPTION_EXTENSIONS or (extension != ".docx" and _CUE_TIME.search(text) and "-->" in text[:4000]):
        utterances = parse_captions(text)
        fmt = extension.lstrip(".") if extension in CAPTION_EXTENSIONS else "captions"
        if not utterances:
            raise TranscriptError("No caption cues were found in this file.")
    else:
        utterances, title, date_text, _speakers = parse_text(text)
        fmt = extension.lstrip(".") or "text"
    utterances = [u for u in utterances if u.text.strip()]
    if not any(not u.heading for u in utterances):
        raise TranscriptError("No spoken or written content was found in this file.")

    timed = is_timed(utterances)
    pieces: list[Utterance] = []
    for u in utterances:
        pieces.extend(split_long(u))
    place_in_time(pieces, timed)

    seen: list[str] = []
    for u in pieces:
        if u.speaker and u.speaker not in seen:
            seen.append(u.speaker)
    return Transcript(pieces, timed, fmt, title=title, date_text=date_text, speakers=seen, truncated=truncated)
