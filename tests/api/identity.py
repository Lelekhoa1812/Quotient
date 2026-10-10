"""Identities, screens and the stale flag reach the client; unknown shapes are cleaned, never trusted."""

from quotient.graph.gate import page_graph, project_meeting, summary


def _row(**extra):
    row = {
        "meeting_id": "m1", "subject": "me", "status": "ready", "object_key": "uploads/t/a.mp4",
        "spans": [
            {"span_id": "a", "kind": "speech", "start_ms": 0, "end_ms": 1000, "text": "hi", "raw_text": "hi", "speaker_hypothesis_id": "spk_0"},
            {"span_id": "b", "kind": "speech", "start_ms": 1000, "end_ms": 2000, "text": "yo", "raw_text": "yo", "speaker_hypothesis_id": "spk_1"},
        ],
    }
    row.update(extra)
    return row


def test_identities_reach_the_span_and_the_page_but_not_typed_names():
    projected = project_meeting(_row(identities={"spk_0": {"name": " Jason ", "source": "visual", "confidence": 0.8, "conflict": "Jay", "merged": ["spk_4"]}}))
    spans = {span["span_id"]: span for span in projected["graph"]["spans"]}
    assert spans["a"]["speaker_identity"] == "Jason" and spans["b"]["speaker_identity"] is None
    assert spans["a"]["speaker_display"] is None
    page, _ = page_graph(projected["graph"], 0, 50)
    assert page["identities"]["spk_0"]["conflict"] == "Jay" and page["identities"]["spk_0"]["merged"] == ["spk_4"]


def test_bad_identity_and_screen_rows_are_dropped_or_clamped():
    projected = project_meeting(
        _row(
            identities={"spk_0": {"name": "x" * 500, "source": "made-up", "confidence": "high"}, "spk_1": {"name": ""}, "spk_2": "junk", 7: {"name": "z"}},
            screens=[
                {"id": "s1", "kind": "slide", "title": "T", "text": "y" * 9000, "details": "d", "start_ms": 5, "end_ms": 9},
                {"kind": "slide", "start_ms": "x", "end_ms": 9},
                "junk",
            ],
        )
    )
    identities = projected["graph"]["identities"]
    assert list(identities) == ["spk_0"] and len(identities["spk_0"]["name"]) == 128
    assert identities["spk_0"]["source"] == "audio" and identities["spk_0"]["confidence"] == 0.0
    screens = projected["graph"]["screens"]
    assert len(screens) == 1 and len(screens[0]["text"]) == 4000


def test_a_stale_analysis_and_a_running_reindex_show_in_the_summary_only_when_they_matter():
    quiet = summary(project_meeting(_row(identity_revision=2, analysed_identity_revision=2)))
    assert "identity" not in quiet
    stale = summary(project_meeting(_row(identity_revision=3, analysed_identity_revision=2)))
    assert stale["identity"] == {"stale": True, "reindexing": False, "error": None}
    running = summary(project_meeting(_row(status="working", reindexing=True, identity_revision=3, analysed_identity_revision=2)))
    assert running["identity"]["reindexing"] is True
    failed = summary(project_meeting(_row(reindex_error="model unavailable", identity_revision=1, analysed_identity_revision=1)))
    assert failed["identity"]["error"] == "model unavailable"
