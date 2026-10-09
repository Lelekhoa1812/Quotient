from types import SimpleNamespace

import pytest

from errors import NoSpeech
from loop.quality import _require_speech
from quotient.port import Port, PortError, _public_failure


def _span(kind, text=""):
    return SimpleNamespace(kind=kind, text=text, raw_text=text)


def test_a_long_recording_with_nothing_transcribed_fails_instead_of_publishing_as_ready():
    with pytest.raises(NoSpeech):
        _require_speech(SimpleNamespace(duration_ms=600_000, spans=[]))
    with pytest.raises(NoSpeech):
        _require_speech(SimpleNamespace(duration_ms=600_000, spans=[_span("speech", "  "), _span("silence")]))
    assert "No speech could be transcribed" in _public_failure(NoSpeech("x"))


def test_speech_a_named_gap_or_a_short_clip_is_not_a_failure():
    _require_speech(SimpleNamespace(duration_ms=600_000, spans=[_span("speech", "hello there")]))
    _require_speech(SimpleNamespace(duration_ms=600_000, spans=[_span("untranscribed")]))  # the provider refused it: a stated gap
    _require_speech(SimpleNamespace(duration_ms=10_000, spans=[]))  # too short to judge


@pytest.fixture()
def port(tmp_path, monkeypatch):
    port = Port(None, None, None, None, tmp_path / "state.json")
    monkeypatch.setattr(port, "_analyze", lambda meeting_id: None)
    return port


def test_cancel_refuses_a_meeting_that_already_finished(port):
    meeting = port.submit(subject="a", object_key="uploads/t/x.mp4", context_names=(), idempotency_key=None)
    for finished in ("ready", "needs_review", "failed"):
        port._rows[meeting]["status"] = finished
        with pytest.raises(PortError, match="already finished"):
            port.cancel(meeting, "a")
        assert port.meeting(meeting, "a")["status"] == finished
    port._rows[meeting]["status"] = "working"
    assert port.cancel(meeting, "a")["status"] == "cancelled"


def test_a_submission_that_could_not_be_stored_is_not_remembered_as_submitted(port, monkeypatch):
    first = port.submit(subject="a", object_key="uploads/t/x.mp4", context_names=(), idempotency_key="k1")
    monkeypatch.setattr(port, "_save_locked", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        port.submit(subject="a", object_key="uploads/t/y.mp4", context_names=(), idempotency_key="k2")
    assert ("a", "k2") not in port._idempotency and len(port._rows) == 1 and first in port._rows
    monkeypatch.undo()
    monkeypatch.setattr(port, "_analyze", lambda meeting_id: None)
    retry = port.submit(subject="a", object_key="uploads/t/y.mp4", context_names=(), idempotency_key="k2")
    assert retry != first and retry in port._rows


def test_a_retry_after_a_failure_or_cancellation_is_a_new_attempt_but_a_live_one_is_returned(port):
    first = port.submit(subject="a", object_key="uploads/t/x.mp4", context_names=(), idempotency_key="k")
    assert port.submit(subject="a", object_key="uploads/t/x.mp4", context_names=(), idempotency_key="k") == first  # still queued
    for dead in ("failed", "cancelled"):
        port._rows[first]["status"] = dead
        again = port.submit(subject="a", object_key="uploads/t/x.mp4", context_names=(), idempotency_key="k")
        assert again != first and port._rows[again]["status"] == "queued"
        assert port.submit(subject="a", object_key="uploads/t/x.mp4", context_names=(), idempotency_key="k") == again
        port._rows[again]["status"] = "ready"
        first = again  # the next round retries from the new row's key mapping
        port._rows[first]["status"] = "queued"


def test_a_second_process_cannot_open_the_same_meeting_store(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    store = tmp_path / "state.json"
    first = Port(None, None, None, None, store)
    worker = Path(__file__).resolve().parents[2] / "apps" / "worker"
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from quotient.port import Port; from pathlib import Path\n"
        "try:\n    Port(None, None, None, None, Path(sys.argv[2])); print('opened')\n"
        "except RuntimeError as exc:\n    print('refused:', exc)\n"
    )
    other = subprocess.run([sys.executable, "-I", "-c", code, str(worker), str(store)], capture_output=True, text=True, timeout=60)
    assert "refused: Another Quotient process is already using this meeting store" in other.stdout, other.stdout + other.stderr
    first._lock_file.close()  # released when the owner goes (here, explicitly)
    again = subprocess.run([sys.executable, "-I", "-c", code, str(worker), str(store)], capture_output=True, text=True, timeout=60)
    assert "opened" in again.stdout
    assert Port(None, None, None, None, None) is not None  # no store, nothing to claim


def test_text_a_person_corrected_survives_a_re_analysis_and_unknown_spans_are_ignored():
    from quotient.port import apply_text_edits

    row = {"revisions": [
        {"span_id": "a", "text": "first fix"},
        {"span_id": "a", "text": "second fix"},
        {"span_id": "gone", "text": "orphan"},
        {"span_id": "b", "scope": "hypothesis", "display_name": "Priya"},  # a speaker rename has no text
        {"span_id": 5, "text": "bad"},
    ]}
    spans = [{"span_id": "a", "text": "model words"}, {"span_id": "b", "text": "untouched"}]
    apply_text_edits(row, spans)
    assert [s["text"] for s in spans] == ["second fix", "untouched"]
