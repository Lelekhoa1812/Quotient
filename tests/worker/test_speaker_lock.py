from pathlib import Path

from quotient.port import Port, apply_locked_names


def _port(tmp_path: Path) -> Port:
    port = Port(None, None, None, None, tmp_path / "state.json")
    port._rows["m1"] = {
        "meeting_id": "m1", "subject": "me", "status": "needs_review", "revisions": [],
        "spans": [
            {"span_id": "a", "speaker_hypothesis_id": "spk_0", "speaker_display": None},
            {"span_id": "b", "speaker_hypothesis_id": "spk_1", "speaker_display": None},
            {"span_id": "c", "speaker_hypothesis_id": "spk_0", "speaker_display": None},
        ],
    }
    return port


def test_a_name_given_to_a_voice_covers_all_its_lines_and_survives_a_rerun(tmp_path):
    port = _port(tmp_path)
    row = port.revise_speaker("m1", "me", "a", "hypothesis", "Priya Nair")
    assert [span["speaker_display"] for span in row["spans"]] == ["Priya Nair", None, "Priya Nair"]
    assert row["speaker_names"] == {"spk_0": "Priya Nair"}
    # A later analysis rebuilds the spans with whatever the model produced; the person's name wins.
    fresh = [
        {"span_id": "x", "speaker_hypothesis_id": "spk_0", "speaker_display": "Someone else"},
        {"span_id": "y", "speaker_hypothesis_id": "spk_1", "speaker_display": None},
    ]
    apply_locked_names(row, fresh)
    assert [span["speaker_display"] for span in fresh] == ["Priya Nair", None]


def test_renaming_one_line_does_not_lock_the_voice(tmp_path):
    port = _port(tmp_path)
    row = port.revise_speaker("m1", "me", "a", "span", "Guest")
    assert "speaker_names" not in row


def test_merging_two_voices_makes_one_voice_with_one_name(tmp_path):
    port = _port(tmp_path)
    port.revise_speaker("m1", "me", "b", "hypothesis", "Priya Nair")
    row = port.merge_speakers("m1", "me", "a", "b", "Priya Nair")
    assert {span["speaker_hypothesis_id"] for span in row["spans"]} == {"spk_0"}
    assert [span["speaker_display"] for span in row["spans"]] == ["Priya Nair"] * 3
    assert row["speaker_names"] == {"spk_0": "Priya Nair"}
