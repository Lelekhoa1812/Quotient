from graph.digest import SCREEN_MAX, ground_digest, screen_rows
from pegasus.client import Screen
from test_digest import CLAIMS, SPANS, SPEAKERS, _raw


def _screen(i, text="Revenue $2M", start=0, end=1000, kind="slide", title="Plan", details=""):
    return Screen(id=f"x{i}", kind=kind, title=title, text=text, details=details, start_ms=start, end_ms=end)


def test_screen_rows_fold_a_repeated_screen_and_keep_time_order():
    rows = screen_rows([_screen(2, "B", 70_000, 80_000), _screen(1, "A", 0, 10_000), _screen(3, "A", 10_000, 20_000)])
    assert [(r["t"], r["text"]) for r in rows] == [("0:00", "A"), ("1:10", "B")]
    assert rows[0]["end"] == "0:20"  # the same slide shown again is one entry


def test_screen_rows_are_bounded():
    many = [_screen(i, f"text {i}", i * 1000, i * 1000 + 500) for i in range(SCREEN_MAX + 50)]
    assert len(screen_rows(many)) == SCREEN_MAX
    huge = [_screen(1, "x" * 70_000, 0, 1)]
    assert screen_rows(huge) == []  # one screen larger than the whole budget is left out, not truncated mid-text


def test_a_known_name_is_listed_and_a_conflicting_model_name_is_refused():
    raw = _raw(speakers=[{"id": "spk_1", "name": "Somebody Else", "span_ids": ["s2"]}])
    out = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS, {"spk_1": "Priya Nair"})
    assert [s["name"] for s in out["speakers"]] == ["Priya Nair"]  # the model contradicted the known name: never renamed
    out = ground_digest(_raw(speakers=[]), SPANS, CLAIMS, [], SPEAKERS, {"spk_1": "Priya Nair", "spk_9": "Ghost"})
    assert [(s["id"], s["name"]) for s in out["speakers"]] == [("spk_1", "Priya Nair")]
    assert out["speakers"][0]["span_ids"]  # cited to the voice's own first lines


def test_a_known_name_the_model_confirms_needs_no_spoken_introduction():
    raw = _raw(speakers=[{"id": "spk_0", "name": "Jason", "role": "host", "span_ids": ["s1"]}])
    out = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS, {"spk_0": "Jason Pham"})
    assert [(s["id"], s["name"], s["role"]) for s in out["speakers"]] == [("spk_0", "Jason Pham", "host")]
    # With no known name the old rule still applies: the name must be in a cited line.
    out = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)
    assert out["speakers"] == []
