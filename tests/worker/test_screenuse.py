from types import SimpleNamespace

from graph.screenuse import batches, ground_screen_uses
from graph.span import Span


def _span(span_id, text, start, end=None):
    return Span(
        id=span_id, meeting_id="m", kind="speech", start_ms=start, end_ms=end if end is not None else start + 2000,
        raw_text=text, text=text, speaker_hypothesis_id="spk_0",
    )


def _screen(screen_id, text, start=0, end=8000, title="Orders"):
    return SimpleNamespace(id=screen_id, kind="ui", title=title, text=text, start_ms=start, end_ms=end)


def _pack(screen, spans):
    return batches([screen], spans)[0]


def test_a_reading_with_a_figure_the_screen_shows_is_kept_and_an_unknown_screen_is_dropped():
    screen = _screen("sc", "Sales This Week\nDemo sample\n$184,750")
    pack = _pack(screen, [_span("s1", "This week's sales figure is one hundred and eighty four thousand.", 1000)])
    kept = ground_screen_uses(
        {"readings": [
            {"id": "sc", "reading": "The dashboard shows this week's sales as $184,750, marked as demo sample.", "span_ids": ["s1"], "differs": None},
            {"id": "other", "reading": "Not a screen we sent.", "span_ids": [], "differs": None},
        ]},
        pack,
    )
    assert [row["id"] for row in kept] == ["sc"]
    assert kept[0]["span_ids"] == ["s1"]
    assert kept[0]["start_ms"] == 0


def test_a_figure_that_is_neither_on_the_screen_nor_in_a_cited_line_drops_the_reading():
    screen = _screen("sc", "Margin\n12%")
    pack = _pack(screen, [_span("s1", "The margin on this order is twelve percent.", 1000)])
    kept = ground_screen_uses(
        {"readings": [{"id": "sc", "reading": "The order margin is 0%.", "span_ids": ["s1"], "differs": None}]},
        pack,
    )
    assert kept == []


def test_a_citation_outside_the_screen_window_is_removed_and_a_difference_needs_one():
    screen = _screen("sc", "Please login to play.\n$50,000 virtual currency", start=424_000, end=432_000)
    spans = [
        _span("near", "It should be public, anyone can play.", 426_000),
        _span("far", "We will rebuild the whole site.", 10_000),
    ]
    pack = _pack(screen, spans)
    kept = ground_screen_uses(
        {"readings": [{
            "id": "sc",
            "reading": "The page tells attendees to log in before they can allocate the $50,000.",
            "span_ids": ["far", "near"],
            "differs": "The screen requires a login, while a speaker said the game should be public.",
        }]},
        pack,
    )
    assert len(kept) == 1
    assert kept[0]["span_ids"] == ["near"]
    assert "public" in kept[0]["differs"]


def test_a_difference_with_no_remaining_citation_is_cleared_and_the_reading_stays():
    screen = _screen("sc", "Roles\n142 permissions")
    pack = _pack(screen, [])
    kept = ground_screen_uses(
        {"readings": [{
            "id": "sc",
            "reading": "The roles page lists 142 permissions.",
            "span_ids": ["missing"],
            "differs": "Someone said there were 10.",
        }]},
        pack,
    )
    assert len(kept) == 1
    assert kept[0]["span_ids"] == []
    assert kept[0]["differs"] is None


def test_a_long_screen_keeps_its_tail_and_short_speech_is_not_sampled_away():
    body = "Heading\n" + ("row\n" * 400) + "Margin\n0%\nTotal\n$12.40"
    screen = _screen("sc", body, start=0, end=800_000)
    spans = [_span(f"s{index}", f"line {index} about the order", index * 20_000) for index in range(40)]
    pack = _pack(screen, spans)
    text = pack["screens"][0]["text"]
    assert "0%" in text and "$12.40" in text
    said = pack["screens"][0]["said"]
    # Forty short lines fit, so the middle is not sampled away.
    assert len(said) == 40
    assert said[0]["id"] == "s0"
    assert said[20]["id"] == "s20"
    assert said[-1]["id"] == "s39"
    assert "details" not in pack["screens"][0]
