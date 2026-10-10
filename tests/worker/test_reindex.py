import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from identity.resolve import Identity
from quotient.port import Port, PortError


def _port(tmp_path: Path, status="needs_review") -> Port:
    port = Port(None, None, None, None, tmp_path / "state.json")
    port._rows["m1"] = {
        "meeting_id": "m1", "subject": "me", "status": status, "revisions": [], "object_key": "uploads/x/a.mp4",
        "spans": [
            {"span_id": "a", "speaker_hypothesis_id": "spk_0", "speaker_display": None},
            {"span_id": "b", "speaker_hypothesis_id": "spk_1", "speaker_display": None},
            {"span_id": "c", "speaker_hypothesis_id": "spk_3", "speaker_display": None},
        ],
        "digest": None, "context_names": [],
    }
    return port


def _wait(event: threading.Event):
    assert event.wait(5), "the reindex thread never ran"


def test_a_name_change_makes_the_analysis_stale_until_a_reindex_finishes(tmp_path):
    port = _port(tmp_path)
    row = port.revise_speaker("m1", "me", "a", "hypothesis", "Priya")
    assert row["identity_revision"] == 1 and not row.get("analysed_identity_revision")
    port._project_identity(port._rows["m1"], SimpleNamespace(visual_identities=[], screens=[], sightings=[]), None)
    assert port._rows["m1"]["analysed_identity_revision"] == 1
    assert port._rows["m1"]["identities"]["spk_0"]["source"] == "user"


def test_a_merge_is_remembered_by_voice_id_and_replayed_on_a_new_run(tmp_path):
    port = _port(tmp_path)
    port.merge_speakers("m1", "me", "a", "c", "Priya")  # spk_3 folds into spk_0
    port.merge_speakers("m1", "me", "b", "a", "Priya")  # spk_0 (now spk_1's) folds into spk_1
    merges = port._rows["m1"]["speaker_merges"]
    assert merges == {"spk_3": "spk_0", "spk_0": "spk_1"} or merges == {"spk_3": "spk_1", "spk_0": "spk_1"}
    spans = [SimpleNamespace(speaker_hypothesis_id=voice) for voice in ("spk_0", "spk_1", "spk_3", None)]
    ledger = SimpleNamespace(spans=spans, visual_identities=[Identity("spk_5", "Jason", "visual", 0.9)], known_names={})
    port._apply_identity_state("m1", ledger)
    assert [span.speaker_hypothesis_id for span in spans] == ["spk_1", "spk_1", "spk_1", None]
    assert ledger.known_names["spk_5"] == "Jason" and ledger.known_names["spk_1"] == "Priya"


def test_a_typed_name_outranks_the_picture_in_known_names(tmp_path):
    port = _port(tmp_path)
    port.revise_speaker("m1", "me", "a", "hypothesis", "Typed")
    ledger = SimpleNamespace(spans=[], visual_identities=[Identity("spk_0", "Seen", "visual", 0.9)], known_names={})
    port._apply_identity_state("m1", ledger)
    assert ledger.known_names == {"spk_0": "Typed"}


def test_reindex_runs_again_and_a_failure_keeps_the_earlier_analysis(tmp_path):
    port = _port(tmp_path, "ready")
    done = threading.Event()
    seen = {}

    def boom(meeting_id, object_key, names, reindex=False):
        seen["reindex"] = reindex
        done.set()
        raise RuntimeError("model unavailable")

    port._run_meeting = boom
    row = port.reindex("m1", "me")
    assert row["reindexing"] is True and row["status"] == "queued"
    _wait(done)
    for _ in range(100):
        if not port._rows["m1"].get("reindexing"):
            break
        threading.Event().wait(0.02)
    final = port._rows["m1"]
    assert seen["reindex"] is True
    assert final["status"] == "ready" and final["reindexing"] is False and final["reindex_error"]
    assert "previous_status" not in final


def test_reindex_is_refused_while_running_or_after_a_stop(tmp_path):
    port = _port(tmp_path, "working")
    with pytest.raises(PortError):
        port.reindex("m1", "me")
    port._rows["m1"]["status"] = "cancelled"
    with pytest.raises(PortError):
        port.reindex("m1", "me")
    with pytest.raises(PortError):
        port.reindex("nope", "me")
    with pytest.raises(PortError):
        port.reindex("m1", "someone else")


def test_stopping_a_reindex_keeps_the_analysis_and_ignores_its_late_result(tmp_path):
    port = _port(tmp_path, "needs_review")
    gate = threading.Event()
    release = threading.Event()

    def slow(meeting_id, object_key, names, reindex=False):
        gate.set()
        release.wait(5)

    port._run_meeting = slow
    port.reindex("m1", "me")
    _wait(gate)
    row = port.cancel("m1", "me")
    assert row["status"] == "needs_review" and row["reindexing"] is False
    assert port._is_cancelled("m1") is True  # the running thread is told to stop
    port._fail("m1", "late failure")  # a late failure from the stopped run must not overwrite the analysis
    assert port._rows["m1"]["status"] == "needs_review"
    release.set()
    # A later reindex is a new run and is not treated as stopped.
    port.reindex("m1", "me")
    assert port._is_cancelled("m1") is False
