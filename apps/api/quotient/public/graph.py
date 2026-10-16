"""Partner graph body: spans, speakers, screens, and times.

Motivation vs Logic
Motivation: an HTTP client needs the clock and the speaker on each line, and
the screen rows, without a media URL.
Logic: copy those fields off the projected graph. Playback and upload fields
are left out. A screen time uses kind screen so a caller can store it beside
a speech span.
"""

from __future__ import annotations


def partner_graph(job_id: str, status: str, graph: dict) -> dict:
    spans: list[dict] = []
    speakers: dict[str, dict] = {}
    times: list[dict] = []
    for span in graph.get("spans") or []:
        if not isinstance(span, dict):
            continue
        row = {
            "span_id": span.get("span_id"),
            "kind": span.get("kind"),
            "start_ms": span.get("start_ms"),
            "end_ms": span.get("end_ms"),
            "speaker_hypothesis_id": span.get("speaker_hypothesis_id"),
            "raw_text": span.get("raw_text") if isinstance(span.get("raw_text"), str) else "",
            "text": span.get("text") if isinstance(span.get("text"), str) else "",
        }
        spans.append(row)
        times.append(
            {
                "id": row["span_id"],
                "kind": row["kind"] if isinstance(row["kind"], str) else "speech",
                "start_ms": row["start_ms"],
                "end_ms": row["end_ms"],
            }
        )
        speaker = row["speaker_hypothesis_id"]
        if isinstance(speaker, str) and speaker and speaker not in speakers:
            name = span.get("speaker_identity")
            speakers[speaker] = {
                "speaker_hypothesis_id": speaker,
                "name": name if isinstance(name, str) and name.strip() else None,
            }
    screens: list[dict] = []
    for screen in graph.get("screens") or []:
        if not isinstance(screen, dict):
            continue
        row = {
            "id": screen.get("id"),
            "kind": screen.get("kind"),
            "title": screen.get("title") if isinstance(screen.get("title"), str) else "",
            "text": screen.get("text") if isinstance(screen.get("text"), str) else "",
            "start_ms": screen.get("start_ms"),
            "end_ms": screen.get("end_ms"),
        }
        screens.append(row)
        times.append(
            {
                "id": row["id"],
                "kind": "screen",
                "start_ms": row["start_ms"],
                "end_ms": row["end_ms"],
            }
        )
    meeting_id = graph.get("meeting_id")
    return {
        "job_id": job_id,
        "meeting_id": meeting_id if isinstance(meeting_id, str) else None,
        "status": status,
        "spans": spans,
        "speakers": list(speakers.values()),
        "screens": screens,
        "times": times,
    }
