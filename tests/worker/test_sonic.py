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


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_sessions_hand_off_at_six_minutes():
    assert SONIC_HANDOFF_SAMPLES == 6 * 60 * 16000
    assert plan_sessions(SONIC_HANDOFF_SAMPLES) == [(0, SONIC_HANDOFF_SAMPLES)]
    assert plan_sessions(SONIC_HANDOFF_SAMPLES + 512)[1][0] == SONIC_HANDOFF_SAMPLES


def test_one_open_span_is_not_coarse_and_raw_text_is_immutable():
    clock = FakeClock()
    client = SonicClient(registry(), Transport(["alpha"]), sleep=clock.sleep, clock=clock.monotonic, handoff_samples=512)
    pcm = b"\x00\x01" * 512
    speech = [Span(id="v0", meeting_id="m", kind="speech", start_ms=0, end_ms=32, raw_text="", speaker_hypothesis_id="h9")]
    table = build_table(32, [])
    spans, seams = client.transcribe(pcm, meeting_id="m", speech_spans=speech, table=table, context="Ada Lovelace")
    assert seams == []
    assert clock.sleeps == [0.032]
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
    clock = FakeClock()
    transport = Transport(["alpha", "beta"])
    client = SonicClient(registry(), transport, sleep=clock.sleep, clock=clock.monotonic, handoff_samples=512)
    pcm = b"\x00\x01" * 1024
    speech = [Span(id="v0", meeting_id="m", kind="speech", start_ms=0, end_ms=64, raw_text="")]
    table = build_table(64, [])
    spans, seams = client.transcribe(pcm, meeting_id="m", speech_spans=speech, table=table)
    assert len(seams) == 1
    assert seams[0].sample_start == 512
    assert seams[0].source_start_ms == 32
    assert [span.raw_text for span in spans] == ["alpha", "beta"]
    assert clock.sleeps == [0.032, 0.032]
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


def test_a_continuous_long_vad_region_uses_the_sample_clock_for_local_bounds():
    speech = [Span(id="whole", meeting_id="m", kind="speech", start_ms=0, end_ms=1_200_000, raw_text="")]
    table = build_table(1_200_000, [])
    bound = bind_samples(16_000 * 600, 16_000 * 600 + 512, speech, table)
    assert (bound["start_ms"], bound["end_ms"]) == (600_000, 600_032)
    assert bound["coarse"] is True


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


class RejectingTransport:
    """Rejects the audio of selected session numbers with a provider-style error."""

    def __init__(self, reject, texts):
        self.reject = set(reject)
        self.texts = list(texts)
        self.opened = 0

    def open(self, *, model_id, region):
        number = self.opened
        self.opened += 1
        if number in self.reject:
            return RejectingSession()
        return Session([], self.texts.pop(0) if self.texts else None)


class RejectingSession:
    def send(self, event):
        if "audioInput" in json.dumps(event):
            raise RuntimeError("validationException: This request has been blocked by our content filters.")
        return []

    def close(self):
        return []


def _client(transport, handoff):
    clock = FakeClock()
    return SonicClient(registry(), transport, sleep=clock.sleep, handoff_samples=handoff, clock=clock.monotonic)


def test_a_rejected_segment_is_retried_then_recorded_and_later_segments_still_run():
    handoff = 16000 * 2
    pcm = b"\x01\x00" * (handoff * 3)
    table = build_table(6000, [])
    transport = RejectingTransport(reject={1, 2}, texts=["first segment", "third segment"])
    client = _client(transport, handoff)
    spans, seams = client.transcribe(pcm, meeting_id="m", speech_spans=[], table=table)
    kinds = [span.kind for span in spans]
    assert kinds.count("untranscribed") == 1
    assert [span.raw_text for span in spans if span.kind == "speech"] == ["first segment", "third segment"]
    assert client.unavailable and client.unavailable[0][0].startswith("sonic-1")
    assert transport.opened == 4  # segment 1 once, segment 2 twice (retry), segment 3 once
    assert len(seams) == 2


def test_a_transient_rejection_succeeds_on_the_retry_without_duplicate_text():
    handoff = 16000 * 2
    pcm = b"\x01\x00" * (handoff * 2)
    transport = RejectingTransport(reject={1}, texts=["first", "second"])
    client = _client(transport, handoff)
    spans, _ = client.transcribe(pcm, meeting_id="m", speech_spans=[], table=build_table(4000, []))
    assert [span.raw_text for span in spans] == ["first", "second"]
    assert client.unavailable == []


class FilteringTransport:
    """Rejects any session whose audio contains the marker bytes, like a deterministic content filter."""

    def __init__(self):
        self.opened = 0
        self.windows = []

    def open(self, *, model_id, region):
        self.opened += 1
        owner = self
        record = {"bad": False, "frames": 0}
        self.windows.append(record)

        class FilteringSession:
            def send(self, event):
                body = event.get("event", {}).get("audioInput")
                if body:
                    record["frames"] += 1
                    if b"\x7f\x7f" in base64.b64decode(body["content"]):
                        record["bad"] = True
                        raise RuntimeError("validationException: This request has been blocked by our content filters.")
                return []

            def close(self):
                return [{"event": {"textOutput": {"role": "USER", "content": f"window {owner.opened}"}}}]

        return FilteringSession()


def test_a_content_filtered_segment_loses_only_the_rejected_window():
    sec = 16000
    pcm = bytearray(b"\x01\x00" * (sec * 180))
    pcm[sec * 2 * 100 : sec * 2 * 110] = b"\x7f\x7f" * (sec * 10)  # a bad stretch inside the second 90 s window
    transport = FilteringTransport()
    client = _client(transport, handoff=sec * 180)
    spans, _ = client.transcribe(bytes(pcm), meeting_id="m", speech_spans=[], table=build_table(180000, []))
    gaps = [span for span in spans if span.kind == "untranscribed"]
    speech = [span for span in spans if span.kind == "speech"]
    assert len(gaps) == 1
    assert (gaps[0].start_ms, gaps[0].end_ms) == (90000, 180000)
    assert len(speech) == 1  # the clean first window was recovered
    assert [w["bad"] for w in transport.windows] == [True, False, True]  # full segment, window 1, window 2


def test_a_configuration_failure_fails_the_meeting_instead_of_becoming_untranscribed():
    import pytest

    from errors import NotInvocable

    class Denied:
        def open(self, *, model_id, region):
            raise NotInvocable(model_id, "ResourceNotFoundException")

    client = _client(Denied(), 16000 * 2)
    with pytest.raises(NotInvocable):
        client.transcribe(b"\x01\x00" * 16000 * 2, meeting_id="m", speech_spans=[], table=build_table(2000, []))

    class Forbidden:
        def open(self, *, model_id, region):
            raise RuntimeError("sonic HTTP 403: check the configured AWS identity")

    with pytest.raises(RuntimeError, match="403"):
        _client(Forbidden(), 16000 * 2).transcribe(b"\x01\x00" * 16000 * 2, meeting_id="m", speech_spans=[], table=build_table(2000, []))


def test_cancelling_stops_the_audio_stream_immediately():
    import pytest

    from errors import AnalysisCancelled

    transport = Transport(["never used"])
    client = _client(transport, 16000 * 6)
    sent = {"frames": 0}
    original = client._audio_frame

    def counting(session_id, index, frame):
        sent["frames"] += 1
        return original(session_id, index, frame)

    client._audio_frame = counting
    client.should_stop = lambda: sent["frames"] >= 3
    with pytest.raises(AnalysisCancelled):
        client.transcribe(b"\x01\x00" * 16000 * 6, meeting_id="m", speech_spans=[], table=build_table(6000, []))
    assert sent["frames"] == 3


def test_a_transient_non_filter_error_is_retried_on_the_same_window_not_split():
    handoff = 16000 * 2
    transport = RejectingTransport(reject={0}, texts=["recovered"])
    client = _client(transport, handoff)
    spans, _ = client.transcribe(b"\x01\x00" * handoff, meeting_id="m", speech_spans=[], table=build_table(2000, []))
    assert [span.raw_text for span in spans] == ["recovered"]
    assert transport.opened == 2  # one failed open, one retry of the whole segment


def test_rejection_message_decides_retry_so_only_a_content_filter_skips_it():
    class Hiccup:
        def __init__(self):
            self.opened = 0

        def open(self, *, model_id, region):
            self.opened += 1
            raise RuntimeError("modelStreamErrorException: unexpected error")

    import pytest

    transport = Hiccup()
    client = _client(transport, 16000 * 2)
    with pytest.raises(RuntimeError, match="nothing could be transcribed"):
        client.transcribe(b"\x01\x00" * 16000 * 2, meeting_id="m", speech_spans=[], table=build_table(2000, []))
    # whole segment twice, then one sub-window once
    assert transport.opened == 3


def test_a_meeting_where_every_window_is_rejected_fails_instead_of_looking_silent():
    import pytest

    transport = RejectingTransport(reject=set(range(20)), texts=[])
    client = _client(transport, 16000 * 2)
    with pytest.raises(RuntimeError, match="nothing could be transcribed"):
        client.transcribe(b"\x01\x00" * 16000 * 4, meeting_id="m", speech_spans=[], table=build_table(4000, []))


class ExpiringTransport:
    """Answers HTTP 403 until its credentials are refreshed, like a session token that ran out mid-meeting."""

    def __init__(self, refreshable):
        self.valid = False
        self.refreshable = refreshable
        self.refreshes = 0

    def refresh(self):
        self.refreshes += 1
        if self.refreshable:
            self.valid = True

    def open(self, *, model_id, region):
        if not self.valid:
            raise RuntimeError("sonic HTTP 403: check the configured AWS identity, Sonic model access, and bidirectional-stream permission")
        return Session([], "after refresh")


def test_expired_credentials_are_re_read_once_and_the_window_then_succeeds():
    transport = ExpiringTransport(refreshable=True)
    client = _client(transport, 16000 * 2)
    client.refresh_credentials = transport.refresh
    spans, _ = client.transcribe(b"\x01\x00" * 16000 * 2, meeting_id="m", speech_spans=[], table=build_table(2000, []))
    assert transport.refreshes == 1
    assert [span.raw_text for span in spans] == ["after refresh"]


def test_a_lapsed_sign_in_fails_after_one_refresh_with_the_real_cause():
    import pytest

    transport = ExpiringTransport(refreshable=False)
    client = _client(transport, 16000 * 2)
    client.refresh_credentials = transport.refresh
    with pytest.raises(RuntimeError, match="403"):
        client.transcribe(b"\x01\x00" * 16000 * 2, meeting_id="m", speech_spans=[], table=build_table(2000, []))
    assert transport.refreshes == 1  # one re-read, not a loop


class CountingTransport:
    """A transport that records how many sessions were opened and can fail from a given one onward."""

    def __init__(self, fail_from=None, text="spoken"):
        self.opened = 0
        self.fail_from = fail_from
        self.text = text

    def open(self, *, model_id, region):
        from errors import NotInvocable

        number = self.opened
        self.opened += 1
        if self.fail_from is not None and number >= self.fail_from:
            raise NotInvocable(model_id, "ResourceNotFoundException")  # permanent: fails the meeting
        return Session([], f"{self.text} {number}")


def test_a_retry_replays_finished_segments_and_streams_only_the_missing_ones(tmp_path):
    import pytest

    from errors import NotInvocable
    from sonic.cache import TranscriptCache, cache_key

    handoff = 16000 * 2
    pcm = b"\x01\x00" * (handoff * 3)
    table = build_table(6000, [])
    key = cache_key("alice", pcm, handoff=handoff, model="m", version=1, context=None)

    first = CountingTransport(fail_from=2)  # crashes on the third segment, like an expired sign-in
    client = _client(first, handoff)
    client.cache = TranscriptCache(tmp_path, key)
    with pytest.raises(NotInvocable):
        client.transcribe(pcm, meeting_id="m1", speech_spans=[], table=table)
    assert first.opened == 3

    second = CountingTransport()
    retry = _client(second, handoff)
    retry.cache = TranscriptCache(tmp_path, key)
    spans, seams = retry.transcribe(pcm, meeting_id="m2", speech_spans=[], table=table)
    assert second.opened == 1  # only the segment that never finished
    assert [span.raw_text for span in spans] == ["spoken 0", "spoken 1", "spoken 0"]
    assert all(span.id.startswith("m2-") for span in spans)  # rebuilt under the new meeting
    assert len(seams) == 2

    third = CountingTransport()
    done = _client(third, handoff)
    done.cache = TranscriptCache(tmp_path, key)
    done.transcribe(pcm, meeting_id="m3", speech_spans=[], table=table)
    assert third.opened == 0  # everything replays


def test_the_cache_is_private_per_owner_audio_context_and_prompt_version(tmp_path):
    from sonic.cache import cache_key

    pcm = b"\x01\x00" * 100
    base = dict(handoff=10, model="m", version=1, context=None)
    keys = {
        cache_key("alice", pcm, **base),
        cache_key("bob", pcm, **base),
        cache_key("alice", pcm + b"\x00\x00", **base),
        cache_key("alice", pcm, **{**base, "version": 2}),
        cache_key("alice", pcm, **{**base, "context": "Ada"}),
    }
    assert len(keys) == 5


def test_segments_that_lost_a_window_are_not_cached_so_a_retry_can_try_again(tmp_path):
    from sonic.cache import TranscriptCache

    handoff = 16000 * 2
    transport = RejectingTransport(reject={0, 1}, texts=[])  # first segment rejected twice, then split windows rejected
    cache = TranscriptCache(tmp_path, "k")
    client = _client(transport, handoff)
    client.cache = cache
    try:
        client.transcribe(b"\x01\x00" * handoff, meeting_id="m", speech_spans=[], table=build_table(2000, []))
    except RuntimeError:
        pass
    assert cache.get("sonic-0", 0, handoff) is None
