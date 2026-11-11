# Motivation vs Logic
# Motivation: The analysis (claims, checks, lenses, the walkaway, charts, who-said-what) starts from a Ledger of
# timed speech spans with voice ids. A recording gets that Ledger from transcription and voice separation. A
# transcript file already holds the words, so it has to reach the same Ledger without any audio step.
# Logic: Parse the file (transcript.parse), give every distinct speaker one voice id (spk_0, spk_1, ... in order of
# first appearance, with "Maddy" and "Madison Schumann" sharing one), turn each utterance into a speech span and
# each span into a turn, and return the Ledger plus what the file named. The names are returned apart from the
# Ledger so the caller can store them like a typed name: they come from the file, a person can still correct them.

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from graph.span import Span
from identity.resolve import clean_name, same_person
from loop.quality import Ledger
from media.compact import IndexedSpan
from transcript.parse import _GENERIC_SPEAKER, Transcript, TranscriptError, parse_transcript

_MONTHS = {
    name: index
    for index, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
            ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}


@dataclass
class TranscriptInfo:
    format: str
    timed: bool
    title: str | None
    date_text: str | None
    names: dict[str, str]  # voice id -> name the file gave
    speakers: int
    words: int
    truncated: bool


def parse_date(text: str | None) -> str | None:
    """An ISO date from the text a document carries ("10th Nov, 2026 - 2:33 PM", "2026-11-10", "10/11/2026")."""
    if not text:
        return None
    iso = re.search(r"\b(20\d{2}|19\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    try:
        if iso:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).isoformat()
        named = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", text)
        if named and named.group(2).lower() in _MONTHS:
            return date(int(named.group(3)), _MONTHS[named.group(2).lower()], int(named.group(1))).isoformat()
        us = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text)
        if us and us.group(1).lower() in _MONTHS:
            return date(int(us.group(3)), _MONTHS[us.group(1).lower()], int(us.group(2))).isoformat()
        slash = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", text)
        if slash:  # day first, as written in Australia
            return date(int(slash.group(3)), int(slash.group(2)), int(slash.group(1))).isoformat()
    except ValueError:
        return None
    return None


def _voice_map(transcript: Transcript) -> tuple[dict[str, str], dict[str, str]]:
    """label -> voice id, and voice id -> display name (only for labels that are a name, not 'Speaker 1')."""
    voices: dict[str, str] = {}
    names: dict[str, str] = {}
    for label in transcript.speakers:
        name = None if _GENERIC_SPEAKER.match(label.strip()) else clean_name(label)
        voice = None
        if name:
            for known_voice, known_name in names.items():
                if same_person(name, known_name):
                    voice = known_voice
                    from identity.resolve import longer_form

                    names[known_voice] = longer_form(known_name, name)
                    break
        if voice is None:
            voice = f"spk_{len(set(voices.values()))}"
            if name:
                names[voice] = name
        voices[label] = voice
    return voices, names


def assemble_transcript(path: Path, meeting_id: str, *, progress_callback=None) -> tuple[Ledger, TranscriptInfo]:
    if progress_callback:
        progress_callback("Reading the transcript")
    transcript = parse_transcript(path)
    voices, names = _voice_map(transcript)

    spans: list[Span] = []
    turns: list[tuple[int, int, str]] = []
    words = 0
    for index, utterance in enumerate(transcript.utterances):
        start = int(utterance.start_ms or 0)
        end = max(int(utterance.end_ms or 0), start + 1)
        voice = voices.get(utterance.speaker) if utterance.speaker else None
        words += len(utterance.text.split())
        spans.append(
            Span(
                id=f"{meeting_id}-tx-{index}",
                meeting_id=meeting_id,
                kind="speech",
                start_ms=start,
                end_ms=end,
                raw_text=utterance.text,
                session_id="transcript",
                speaker_hypothesis_id=voice,
            )
        )
        if voice:
            turns.append((start, end, voice))
    if not spans:
        raise TranscriptError("No content was found in this file.")
    duration = max(span.end_ms for span in spans)
    ledger = Ledger(
        meeting_id=meeting_id,
        duration_ms=duration,
        kind="transcript",
        spans=spans,
        index=[IndexedSpan(id=s.id, kind=s.kind, start_ms=s.start_ms, end_ms=s.end_ms, overlap=False) for s in spans],
        turns=turns,
        anchor_date=parse_date(transcript.date_text),
        known_names=dict(names),
    )
    info = TranscriptInfo(
        format=transcript.format,
        timed=transcript.timed,
        title=transcript.title,
        date_text=transcript.date_text,
        names=names,
        speakers=len(set(voices.values())),
        words=words,
        truncated=transcript.truncated,
    )
    return ledger, info
