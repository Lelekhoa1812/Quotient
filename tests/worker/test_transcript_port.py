"""A transcript meeting through the Port: submit checks, no audio steps, names from the file, no playback."""

import json
from pathlib import Path

import pytest

from bedrock import nim
from quotient.port import Port, PortError

MARKDOWN = """# Pilot review

**Maya Chen** *[00:00]*: We agreed to ship the pilot in March.
**Jon Park** *[00:20]*: I will own the budget paper by Friday.
**Maya Chen** *[01:05]*: Good. Budget risk is the open issue.
"""


@pytest.fixture(autouse=True)
def clean_nim(monkeypatch):
    for index in range(1, 10):
        monkeypatch.delenv(f"NVIDIA_NIM_API_KEY_{index}", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEYS", raising=False)
    monkeypatch.delenv("NIM_SECRET_ARN", raising=False)
    monkeypatch.delenv("QUOTIENT_MODEL_PROVIDER", raising=False)
    nim.reset_keys_for_tests()
    yield
    nim.reset_keys_for_tests()


def make_port(tmp_path):
    return Port(None, None, None, None, state_path=tmp_path / "state.json")


def submit(port, **extra):
    port._enqueue_analysis = lambda meeting_id: None  # do not start the model pipeline
    return port.submit(subject="me", object_key="uploads/t1/sync.md", context_names=(), idempotency_key=None, **extra)


def test_default_provider_is_bedrock_and_is_recorded(tmp_path):
    port = make_port(tmp_path)
    row = port._rows[submit(port)]
    assert row["model_provider"] == "bedrock" and row["model_overrides"] == {}


def test_nim_is_refused_when_the_server_has_no_keys(tmp_path):
    with pytest.raises(PortError, match="NVIDIA NIM is not set up"):
        submit(make_port(tmp_path), model_provider="nim")


def test_nim_is_recorded_with_only_proven_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_NIM_API_KEY_1", "nvapi-test")
    nim.reset_keys_for_tests()
    port = make_port(tmp_path)
    row = port._rows[submit(port, model_provider="NIM", model_overrides={"slm": "poolside/laguna-xs-2.1", "llm": "not/a-model"})]
    assert row["model_provider"] == "nim" and row["model_overrides"] == {"slm": "poolside/laguna-xs-2.1"}


def test_unknown_provider_is_rejected(tmp_path):
    with pytest.raises(PortError, match="bedrock or nim"):
        submit(make_port(tmp_path), model_provider="openai")


def test_transcript_ingest_builds_the_ledger_and_records_source_and_names(tmp_path, monkeypatch):
    path = tmp_path / "sync.md"
    path.write_text(MARKDOWN, encoding="utf-8")
    import loop.ingest as ingest

    monkeypatch.setattr(ingest, "open_source", lambda key: (path, None))
    port = make_port(tmp_path)
    meeting_id = submit(port)
    ledger = port._ingest_transcript(meeting_id, "uploads/t1/sync.md")
    row = port._rows[meeting_id]
    assert ledger.kind == "transcript" and len([s for s in ledger.spans if s.kind == "speech"]) == 3
    assert row["source"]["kind"] == "transcript" and row["source"]["timings"] == "exact" and row["source"]["speakers"] == 2
    assert row["speaker_names"] == {"spk_0": "Maya Chen", "spk_1": "Jon Park"}


def test_a_name_a_person_typed_is_not_replaced_by_the_file(tmp_path, monkeypatch):
    path = tmp_path / "sync.md"
    path.write_text(MARKDOWN, encoding="utf-8")
    import loop.ingest as ingest

    monkeypatch.setattr(ingest, "open_source", lambda key: (path, None))
    port = make_port(tmp_path)
    meeting_id = submit(port)
    port._rows[meeting_id]["speaker_names"] = {"spk_0": "Maya C."}
    port._ingest_transcript(meeting_id, "uploads/t1/sync.md")
    assert port._rows[meeting_id]["speaker_names"]["spk_0"] == "Maya C."


def test_a_transcript_meeting_has_no_playback_url(tmp_path):
    port = make_port(tmp_path)
    meeting_id = submit(port)
    row = port._rows[meeting_id]
    row["status"] = "ready"
    row["source"] = {"kind": "transcript", "timings": "exact"}
    assert port.media_url(meeting_id, "me") is None


def test_unreadable_transcript_gets_a_plain_failure_message(tmp_path):
    from quotient.port import _public_failure
    from transcript.parse import TranscriptError

    assert _public_failure(TranscriptError("This PDF is password-protected.")) == "This PDF is password-protected."


def test_model_options_lists_both_providers_and_the_proven_models(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_NIM_API_KEY_1", "nvapi-test")
    nim.reset_keys_for_tests()
    options = make_port(tmp_path).model_options()
    assert [p["id"] for p in options["providers"]] == ["bedrock", "nim"]
    assert options["providers"][1]["available"] is True and options["default"] == "bedrock"
    ids = {m["id"] for m in options["nim_models"]}
    assert "nvidia/nemotron-3-ultra-550b-a55b" in ids and not any("deepseek" in i for i in ids)
    assert json.dumps(options)  # plain data


def test_reindex_of_a_transcript_never_borrows_another_meetings_voices(tmp_path):
    port = make_port(tmp_path)
    meeting_id = submit(port)
    row = port._rows[meeting_id]
    row["source"] = {"kind": "transcript"}
    row["spans"] = [{"span_id": "a", "kind": "speech", "start_ms": 0, "end_ms": 5000, "raw_text": "hello there", "text": "hello there"}]
    called = []
    port._find_cached_turns = lambda *a, **k: called.append(1) or [(0, 5000, "spk_0")]
    ledger = port._reconstruct_ledger(meeting_id, row)
    assert not called and ledger.kind == "transcript" and ledger.turns == []


def test_transcripts_do_not_wait_behind_a_recording_on_the_local_queue(tmp_path, monkeypatch):
    import threading

    monkeypatch.delenv("WORK_QUEUE_URL", raising=False)
    monkeypatch.setenv("QUOTIENT_TRANSCRIPT_THREADS", "2")
    port = make_port(tmp_path)
    started = threading.Event()
    port._analyze = lambda meeting_id: started.set()
    port._rows["t"] = {"meeting_id": "t", "subject": "me", "object_key": "uploads/x/notes.vtt", "status": "queued"}
    port._rows["r"] = {"meeting_id": "r", "subject": "me", "object_key": "uploads/x/call.mp4", "status": "queued"}
    port._active_analysis = "r"  # a long recording is being analysed
    port._enqueue_analysis("t")
    assert started.wait(5), "the transcript waited behind the recording"
    assert port._work_queue.empty()
    port._enqueue_analysis("r")
    assert port._work_queue.get_nowait() == "r"
