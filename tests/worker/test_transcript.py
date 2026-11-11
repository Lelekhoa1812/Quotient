"""Transcript files (SRT, VTT, TXT, MD, DOCX, PDF) become the same Ledger a transcribed recording produces."""

import zipfile

import pytest

from transcript.ingest import assemble_transcript, parse_date
from transcript.parse import TranscriptError, parse_captions, parse_clock, parse_transcript, parse_text


def write(tmp_path, name, content, binary=False):
    path = tmp_path / name
    if binary:
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


SRT = """1
00:00:01,000 --> 00:00:04,000
Maya: We should ship the pilot in March.

2
00:00:04,200 --> 00:00:06,000
Maya: Budget is the open question.

3
00:00:07,000 --> 00:00:10,500
Jon: I can own the budget paper by Friday.

4
00:00:11,000 --> 00:00:12,000
[music]
"""

VTT = """WEBVTT

NOTE a comment

00:00:01.000 --> 00:00:03.000
<v Maya Chen>We start with the roadmap.</v>

00:00:03.500 --> 00:00:06.000
<v Jon Park>Agreed, but hiring comes first.</v>
"""

MARKDOWN = """# Weekly sync

**Meeting Date:** 3rd Mar, 2026 - 9:00 AM

---

**Maya Chen** *[00:00]*: Welcome everyone. Let us start with the roadmap.
**Jon Park** *[00:20]*: Hiring comes first. We need two engineers.
**Maya Chen** *[01:05]*: Fine. I will open the roles today.
"""


def test_clock_parsing():
    assert parse_clock("01:02") == 62_000
    assert parse_clock("1:02:03") == 3_723_000
    assert parse_clock("00:00:01,500") == 1_500
    assert parse_clock("nonsense") is None


def test_srt_cues_become_speaker_turns_with_exact_times(tmp_path):
    t = parse_transcript(write(tmp_path, "call.srt", SRT))
    assert t.timed and t.format == "srt"
    assert t.speakers == ["Maya", "Jon"]
    # Two Maya cues one after the other are one turn; the music cue is dropped.
    assert [u.speaker for u in t.utterances] == ["Maya", "Jon"]
    assert t.utterances[0].start_ms == 1000 and t.utterances[0].end_ms == 6000
    assert "pilot" in t.utterances[0].text and "Budget" in t.utterances[0].text


def test_vtt_voice_tags_and_notes(tmp_path):
    t = parse_transcript(write(tmp_path, "call.vtt", VTT))
    assert t.speakers == ["Maya Chen", "Jon Park"]
    assert t.utterances[1].start_ms == 3500


def test_rolling_auto_captions_are_deduplicated():
    cues = "\n\n".join(
        f"{i}\n00:00:0{i},000 --> 00:00:0{i + 1},000\n{text}"
        for i, text in enumerate(["we plan", "we plan to", "we plan to hire two people"], start=1)
    )
    utterances = parse_captions(cues)
    assert len(utterances) == 1
    assert utterances[0].text.count("we plan") == 1


def test_markdown_with_bold_names_and_clock_stamps(tmp_path):
    t = parse_transcript(write(tmp_path, "sync.md", MARKDOWN))
    assert t.timed and t.title == "Weekly sync"
    assert t.speakers == ["Maya Chen", "Jon Park"]
    assert parse_date(t.date_text) == "2026-03-03"
    assert [u.start_ms for u in t.utterances] == [0, 20_000, 65_000]


def test_untimed_plain_text_gets_estimated_times(tmp_path):
    text = "Maya: We need to decide on the vendor today.\nJon: I prefer the cheaper one.\nMaya: Then it is decided, we go with the cheaper one.\nJon: Fine."
    t = parse_transcript(write(tmp_path, "notes.txt", text))
    assert not t.timed
    assert t.speakers == ["Maya", "Jon"]
    starts = [u.start_ms for u in t.utterances]
    assert starts == sorted(starts) and starts[0] == 0
    assert all(u.end_ms > u.start_ms for u in t.utterances)


def test_a_lone_label_in_prose_is_not_a_speaker(tmp_path):
    text = "Note: the budget is tight this quarter.\n\nThe team agreed to revisit it next month.\n\nAction item: send the revised plan."
    t = parse_transcript(write(tmp_path, "minutes.txt", text))
    assert t.speakers == []
    assert len(t.utterances) >= 2


def test_document_without_speakers_keeps_headings_as_structure(tmp_path):
    text = "# Q3 review\n\n## Revenue\n\nRevenue grew twelve percent on strong renewals.\n\n## Risks\n\nTwo key accounts may churn."
    t = parse_transcript(write(tmp_path, "minutes.md", text))
    assert t.speakers == []
    texts = [u.text for u in t.utterances]
    assert "Revenue" in texts and "Risks" in texts
    assert any("grew twelve percent" in x for x in texts)


def test_teams_style_name_and_time_line_then_text(tmp_path):
    text = "Maya Chen  0:05\nLet us begin.\n\nJon Park  0:12\nReady when you are.\n"
    t = parse_transcript(write(tmp_path, "teams.txt", text))
    assert t.speakers == ["Maya Chen", "Jon Park"]
    assert t.utterances[0].text == "Let us begin."
    assert t.utterances[1].start_ms == 12_000


def test_long_turn_is_cut_at_sentence_ends(tmp_path):
    sentence = "This is a fairly ordinary sentence about the plan. "
    text = "[00:00] Maya: " + sentence * 60 + "\n[02:00] Jon: Short reply."
    t = parse_transcript(write(tmp_path, "long.txt", text))
    maya = [u for u in t.utterances if u.speaker == "Maya"]
    assert len(maya) > 3
    assert all(len(u.text) <= 760 for u in maya)
    assert maya[0].start_ms == 0 and maya[-1].end_ms <= 120_000
    assert [u.start_ms for u in maya] == sorted(u.start_ms for u in maya)


def test_docx_is_read_from_its_xml(tmp_path):
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Planning call</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Maya: We ship in March.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Jon: I will draft the plan.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Maya: Good, thank you.</w:t></w:r></w:p>'
        "</w:body></w:document>"
    )
    path = tmp_path / "call.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
        archive.writestr("[Content_Types].xml", "<Types/>")
    t = parse_transcript(path)
    assert t.title == "Planning call"
    assert t.speakers == ["Maya", "Jon"]


def _pdf(lines):
    body = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({line}) '" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(body)} >>\nstream\n{body}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_pdf_text_is_extracted(tmp_path):
    path = write(tmp_path, "call.pdf", _pdf(["Maya: We ship in March.", "Jon: I will draft the plan.", "Maya: Good."]), binary=True)
    t = parse_transcript(path)
    assert t.speakers == ["Maya", "Jon"]


def test_damaged_and_empty_files_give_plain_errors(tmp_path):
    with pytest.raises(TranscriptError, match="PDF"):
        parse_transcript(write(tmp_path, "bad.pdf", b"not a pdf", binary=True))
    with pytest.raises(TranscriptError, match="Word"):
        parse_transcript(write(tmp_path, "bad.docx", b"not a zip", binary=True))
    with pytest.raises(TranscriptError):
        parse_transcript(write(tmp_path, "empty.txt", "   \n  "))
    with pytest.raises(TranscriptError, match="not supported"):
        parse_transcript(write(tmp_path, "data.exe", "x"))


def test_encodings_are_handled(tmp_path):
    path = tmp_path / "latin.txt"
    path.write_bytes("Zoë: Café budget is fine.\nJon: Agreed, Zoë.".encode("cp1252"))
    t = parse_transcript(path)
    assert "Café" in t.utterances[0].text
    bom = tmp_path / "bom.txt"
    bom.write_bytes("﻿Maya: Hello there.\nJon: Hi.".encode("utf-8"))
    assert parse_transcript(bom).speakers == ["Maya", "Jon"]


def test_ledger_is_built_with_voices_names_and_turns(tmp_path):
    ledger, info = assemble_transcript(write(tmp_path, "sync.md", MARKDOWN), "m1")
    assert ledger.kind == "transcript" and ledger.duration_ms >= 65_000
    assert info.timed and info.speakers == 2
    assert info.names == {"spk_0": "Maya Chen", "spk_1": "Jon Park"}
    speech = [s for s in ledger.spans if s.kind == "speech"]
    assert speech and all(s.text and s.speaker_hypothesis_id for s in speech)
    assert ledger.turns[0][2] == "spk_0"
    assert ledger.anchor_date == "2026-03-03"
    assert len(ledger.index) == len(ledger.spans)


def test_first_name_and_full_name_are_one_voice(tmp_path):
    text = "Madison Schumann: Hello team.\nRicardo: Hi.\nMadison: Let us start.\nRicardo: Sure."
    ledger, info = assemble_transcript(write(tmp_path, "t.txt", text), "m2")
    assert info.speakers == 2


def test_generic_speaker_labels_stay_unnamed(tmp_path):
    text = "Speaker 1: Welcome.\nSpeaker 2: Thanks.\nSpeaker 1: Let's go.\nSpeaker 2: Ready."
    ledger, info = assemble_transcript(write(tmp_path, "t.txt", text), "m3")
    assert info.speakers == 2 and info.names == {}


def test_attached_meeting_transcript_if_present():
    from pathlib import Path

    path = Path.home() / "Downloads" / "meeting-10-11.md"
    if not path.exists():
        pytest.skip("sample transcript not on this machine")
    t = parse_transcript(path)
    assert set(t.speakers) == {"Madison Schumann", "Ricardo Costa", "Viktor Tandrup", "Ly Ho", "Richard Celm"}
    assert 33 * 60_000 < t.duration_ms < 35 * 60_000
    assert t.timed


def test_parse_date_formats():
    assert parse_date("10th Nov, 2026 - 2:33 PM") == "2026-11-10"
    assert parse_date("November 10, 2026") == "2026-11-10"
    assert parse_date("2026-11-10") == "2026-11-10"
    assert parse_date("10/11/2026") == "2026-11-10"
    assert parse_date("sometime soon") is None
    assert parse_date("31 Feb 2026") is None
