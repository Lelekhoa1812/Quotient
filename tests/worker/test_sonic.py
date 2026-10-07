import base64
import json

from bedrock.limits import SONIC_HANDOFF_SAMPLES, SONIC_MODEL, SONIC_REGION
from support import registry
from graph.span import Span
from media.clock import build_table
from sonic.client import SonicClient, bind_samples, plan_sessions, transcript_text


class Session:
    def __init__(self, sink, text):
        self.sink = sink
        self.text = text

    def send(self, event):
        self.sink.append(event)
        return []

    def close(self):
        events = []
        if self.text:
            events.append({"event": {"audioOutput": {"content": "AAAA"}}})
            events.append({"event": {"textOutput": {"role": "ASSISTANT", "content": "ignore me"}}})
            events.append({"event": {"textOutput": {"role": "USER", "content": self.text}}})
        return events


class Transport:
    def __init__(self, texts):
        self.texts = list(texts)
        self.sessions = []

    def open(self, *, model_id, region):
        assert model_id == SONIC_MODEL
        assert region == SONIC_REGION
        sink = []
        self.sessions.append(sink)
        text = self.texts.pop(0) if self.texts else None
        return Session(sink, text)


def test_sessions_hand_off_at_six_minutes():
    assert SONIC_HANDOFF_SAMPLES == 6 * 60 * 16000
    assert plan_sessions(SONIC_HANDOFF_SAMPLES) == [(0, SONIC_HANDOFF_SAMPLES)]
    assert plan_sessions(SONIC_HANDOFF_SAMPLES + 512)[1][0] == SONIC_HANDOFF_SAMPLES


def test_one_open_span_is_not_coarse_and_raw_text_is_immutable():
    sleeps = []
    client = SonicClient(registry(), Transport(["alpha"]), sleep=sleeps.append, handoff_samples=512)
    pcm = b"\x00\x01" * 512
    speech = [Span(id="v0", meeting_id="m", kind="speech", start_ms=0, end_ms=32, raw_text="", speaker_hypothesis_id="h9")]
    table = build_table(32, [])
    spans, seams = client.transcribe(pcm, meeting_id="m", speech_spans=speech, table=table, context="Ada Lovelace")
    assert seams == []
    assert sleeps == [0.032]
    assert len(spans) == 1
    assert spans[0].raw_text == "alpha"
    assert spans[0].text == "alpha"
    assert spans[0].coarse is False
    assert (spans[0].start_ms, spans[0].end_ms) == (0, 32)
    assert spans[0].speaker_hypothesis_id == "h9"
    spans[0].edit_text("edited")
    assert spans[0].text == "edited"
    assert spans[0].raw_text == "alpha"
    with pytest_raises_immutable():
        spans[0].raw_text = "nope"
    blob = json.dumps(client.transport.sessions[0])
    assert '"maxTokens": 1024' in blob
    assert "131072" not in blob
    assert "Ada Lovelace" in blob
    system = [
        event["event"]["textInput"]["content"]
        for event in client.transport.sessions[0]
        if "textInput" in event.get("event", {})
    ]
    assert registry().prompt("meeting.sonic.v1").body in system


def test_handoff_writes_a_seam_and_carries_text_history():
    sleeps = []
    transport = Transport(["alpha", "beta"])
    client = SonicClient(registry(), transport, sleep=sleeps.append, handoff_samples=512)
    pcm = b"\x00\x01" * 1024
    speech = [Span(id="v0", meeting_id="m", kind="speech", start_ms=0, end_ms=64, raw_text="")]
    table = build_table(64, [])
    spans, seams = client.transcribe(pcm, meeting_id="m", speech_spans=speech, table=table)
    assert len(seams) == 1
    assert seams[0].sample_start == 512
    assert seams[0].source_start_ms == 32
    assert [span.raw_text for span in spans] == ["alpha", "beta"]
    assert sleeps == [0.032, 0.032]
    history = [
        event["event"]["textInput"]["content"]
        for event in transport.sessions[1]
        if "textInput" in event.get("event", {}) and event["event"]["textInput"]["content"] == "alpha"
    ]
    assert history == ["alpha"]


def test_text_covering_two_vad_spans_is_coarse():
    speech = [
        Span(id="a", meeting_id="m", kind="speech", start_ms=0, end_ms=1000, raw_text=""),
        Span(id="b", meeting_id="m", kind="speech", start_ms=2000, end_ms=3000, raw_text="", overlap=True),
    ]
    table = build_table(5000, [(1000, 2000)])
    bound = bind_samples(0, 32000, speech, table)
    assert bound["coarse"] is True
    assert bound["start_ms"] == 0
    assert bound["end_ms"] == 3000
    assert bound["overlap"] is True


def test_partial_and_assistant_audio_are_not_transcript():
    assert transcript_text({"event": {"audioOutput": {"content": "AAAA"}}}) is None
    assert transcript_text({"event": {"textOutput": {"role": "ASSISTANT", "content": "hi"}}}) is None
    assert transcript_text({"event": {"textOutput": {"role": "USER", "stage": "PARTIAL", "content": "hi"}}}) is None
    assert transcript_text({"event": {"textOutput": {"role": "FINAL", "content": "done"}}}) == "done"
    assert base64.b64encode(b"\x00").decode()


def pytest_raises_immutable():
    import pytest
    from errors import ImmutableRawText

    return pytest.raises(ImmutableRawText)
