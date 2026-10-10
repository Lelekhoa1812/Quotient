"""Screen readings survive the publish gate only while their citations still resolve."""

from quotient.graph.gate import _digest


def test_a_reading_whose_lines_are_gone_is_dropped_and_a_screen_only_reading_stays():
    spans = {"s1": {"id": "s1", "kind": "speech", "text": "It should be public.", "start_ms": 0, "end_ms": 1000}}
    out = _digest({
        "screen_uses": [
            {"id": "sc1", "reading": "The page requires a login.", "span_ids": ["s1"], "differs": "A speaker said it should be public.", "start_ms": 4000},
            {"id": "sc2", "reading": "This cited a line that is gone.", "span_ids": ["missing"], "differs": None},
            {"id": "sc3", "reading": "The dashboard shows sales of $184,750.", "span_ids": [], "differs": None, "start_ms": 0},
            {"id": "", "reading": "No screen.", "span_ids": []},
            {"id": "sc4", "reading": "See span_id s1 for the point.", "span_ids": ["s1"]},
        ],
    }, spans)
    assert [row["id"] for row in out["screen_uses"]] == ["sc1", "sc3"]
    assert out["screen_uses"][0]["differs"].startswith("A speaker")
    assert out["screen_uses"][0]["start_ms"] == 4000
