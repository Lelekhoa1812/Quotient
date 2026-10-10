import json

from errors import SchemaRejected
from media.artifacts import ArtifactCache
from pegasus.client import PegasusClient, classify_screens
from pegasus.parts import Part, window_parts
from support import registry


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)

    def invoke(self, *, model_id, region, body):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def reply(**data):
    return {"finishReason": "stop", "message": json.dumps(data)}


def test_windows_cover_the_recording_and_fold_a_short_tail():
    minute = 60_000
    parts = window_parts(20 * minute)
    assert parts[0].source_start_ms == 0 and parts[-1].source_end_ms == 20 * minute
    assert all(a.source_end_ms == b.source_start_ms for a, b in zip(parts, parts[1:]))
    assert all(part.duration_ms <= 3 * minute + 45_000 for part in parts)
    tail = window_parts(3 * minute + 20_000)
    assert len(tail) == 1  # a 20 second tail joins the window before it
    assert window_parts(0) == []
    long = window_parts(120 * minute)
    assert all(part.duration_ms <= 50 * minute for part in long)


def test_screens_and_people_become_absolute_times_and_bad_ones_are_dropped():
    part = Part(2, 360_000, 540_000)
    screens, sightings = classify_screens(
        {
            "screens": [
                {"kind": "Slide", "title": "Q3 plan", "text": "Revenue $2M", "details": "bar chart", "start_ms": 1000, "end_ms": 90_000},
                {"kind": "weird", "text": "x", "start_ms": 0, "end_ms": 999_999},  # outside the window
                {"kind": "ui", "start_ms": 0, "end_ms": 1000},  # nothing on it
                "junk",
            ],
            "people": [
                {"name": " Maddy ", "speaking": True, "cue": "Highlight", "start_ms": 0, "end_ms": 5000},
                {"name": "", "start_ms": 0, "end_ms": 1000},
                {"name": "Jason", "speaking": "yes", "start_ms": 5000, "end_ms": 4000},
            ],
        },
        part,
        "m",
    )
    assert [(s.kind, s.start_ms, s.end_ms) for s in screens] == [("slide", 361_000, 450_000)]
    assert screens[0].text == "Revenue $2M"
    assert [(p.name, p.speaking, p.cue, p.start_ms) for p in sightings] == [("Maddy", True, "highlight", 360_000)]


def test_one_unreadable_window_becomes_a_note_and_the_rest_still_count():
    parts = [Part(0, 0, 60_000), Part(1, 60_000, 120_000)]
    transport = Transport(
        [
            SchemaRejected("bad"),
            reply(observations=[{"statement": "a slide", "start_ms": 0, "end_ms": 1000}], screens=[{"kind": "slide", "text": "Hi", "start_ms": 0, "end_ms": 2000}]),
        ]
    )
    result = PegasusClient(registry(), transport).analyze(parts, lambda part: "s3://b/x.mp4", "m")
    assert result.failed_windows == 1
    assert len(result.screens) == 1 and result.screens[0].start_ms == 60_000
    assert any("not available" in note.statement for note in result.notes)
    assert not any("bad" in note.statement for note in result.notes)  # the error text is not copied


def test_strict_mode_still_raises():
    import pytest

    parts = [Part(0, 0, 60_000)]
    with pytest.raises(SchemaRejected):
        PegasusClient(registry(), Transport([SchemaRejected("bad")]), strict=True).analyze(parts, lambda part: "s3://b/x.mp4", "m")


def test_artifact_cache_round_trips_and_isolates_owner_and_audio(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTIENT_TRANSCRIPT_CACHE_DIR", str(tmp_path))
    one = ArtifactCache.for_audio("alice", "diarization", b"audio", "v1")
    assert one.get() is None
    one.put([[0, 1000, "spk_0"]])
    assert ArtifactCache.for_audio("alice", "diarization", b"audio", "v1").get() == [[0, 1000, "spk_0"]]
    assert ArtifactCache.for_audio("bob", "diarization", b"audio", "v1").get() is None
    assert ArtifactCache.for_audio("alice", "diarization", b"other", "v1").get() is None
    assert ArtifactCache.for_audio("alice", "diarization", b"audio", "v2").get() is None
    monkeypatch.setenv("QUOTIENT_TRANSCRIPT_CACHE_DIR", "off")
    assert ArtifactCache.for_audio("alice", "diarization", b"audio", "v1").get() is None
