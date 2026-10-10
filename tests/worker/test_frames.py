import json
from pathlib import Path

from errors import SchemaRejected
from registry.load import Registry
from visual import frames
from visual.frames import FrameReader, frame_times, merge_readings


def reading(shown=False, kind="ui", title="", text="", details="", people=()):
    return {"screen": {"shown": shown, "kind": kind, "title": title, "text": text, "details": details},
            "people": [{"name": n, "speaking": s, "cue": "highlight"} for n, s in people]}


def test_frame_times_are_even_and_bounded():
    times, interval = frame_times(600_000)
    assert interval == 8000 and len(times) == 75 and times[0] == 4000 and times[-1] < 600_000
    long_times, long_interval = frame_times(3_308_000)
    assert len(long_times) <= 160 and long_interval > 8000
    assert frame_times(0) == ([], 8000)


def test_a_repeated_screen_is_one_entry_and_a_new_one_starts_another():
    dash = reading(True, "ui", "Dashboard", "Sales This Week $184,750 Purchases $96,320", "four cards")
    nearly = reading(True, "ui", "Dashboard", "Sales This Week $184,750 Purchases $96,320 ", "four cards, one hovered")
    other = reading(True, "ui", "Contacts", "Name Email Phone Status", "a table")
    readings = [(4000, dash), (12000, nearly), (20000, reading()), (28000, other), (36000, other)]
    screens, _ = merge_readings(readings, 8000, 40_000, "m")
    assert [(s.title, s.start_ms, s.end_ms) for s in screens] == [("Dashboard", 0, 16000), ("Contacts", 24000, 40_000)]


def test_names_become_sightings_with_the_speaking_mark_and_placeholders_are_dropped():
    r = reading(people=[("Ly Ho | Tomsoft", True), ("Jett Van ...", False), ("John Doe", True), ("Presenter", True), ("  ", True)])
    _, sightings = merge_readings([(4000, r)], 8000, 10_000, "m")
    assert [(s.name, s.speaking, s.start_ms, s.end_ms) for s in sightings] == [("Ly Ho | Tomsoft", True, 0, 8000), ("Jett Van ...", False, 0, 8000)]


def test_reader_skips_a_frame_it_cannot_read_and_counts_it(monkeypatch, tmp_path):
    calls = []

    def fake_extract(path, at, dest):
        dest.write_bytes(b"jpeg")
        return dest

    monkeypatch.setattr(frames, "extract_frame", fake_extract)
    answers = {4000: json.dumps(reading(True, "slide", "Plan", "Q3 goals")), 12000: "not json"}

    class Transport:
        def respond(self, request):
            content = request["input"][1]["content"][0]
            assert content["type"] == "input_image" and content["image_url"].startswith("data:image/jpeg;base64,")
            assert request["text"]["format"]["type"] == "json_schema"
            calls.append(request)
            return {"output_text": answers[4000] if len(calls) == 1 else answers[12000]}

    monkeypatch.setenv("QUOTIENT_WORKERS", "1")
    reader = FrameReader(Registry(), Transport(), model="m", fallback=None, region="r", cap=1)
    screens, sightings, failed = reader.read(Path("x.mp4"), 16_000, "mid")
    assert failed == 1 and len(screens) == 1 and screens[0].text == "Q3 goals" and sightings == []


def test_the_same_page_read_differently_each_time_is_one_screen_and_the_cleanest_reading_wins():
    base = "Sales orders FoodFlow TEST STAGING Home Sales Purchasing Inventory Production Dispatch Accounting Reports Admin Order Customer Delivery Status Total"
    a = reading(True, "ui", "Sales orders", "https://staging.vfoodflow.com.au/sales/orders " + base + " [unreadable] [unreadable]", "list")
    b = reading(True, "ui", "Sales orders", "https://staging.xfoodflow.com/sales/orders?page=1 " + base, "list, one row selected")
    c = reading(True, "ui", "Roles", "FoodFlow Roles Permissions View Manage Allow Admin Sales Purchasing", "a roles page")
    screens, _ = merge_readings([(4000, a), (12000, b), (20000, c)], 8000, 24_000, "m")
    assert [s.title for s in screens] == ["Sales orders", "Roles"]
    assert "[unreadable]" not in screens[0].text  # the cleaner of the two readings is kept
    assert screens[0].start_ms == 0 and screens[0].end_ms == 16_000


def test_two_different_pages_with_the_same_chrome_stay_apart():
    chrome = "FoodFlow TEST STAGING Home Sales Purchasing Inventory Production Dispatch Accounting Reports Admin"
    one = reading(True, "ui", "Sales orders", chrome + " Order Customer Delivery", "")
    two = reading(True, "ui", "Purchase orders", chrome + " Supplier Expected Receipt", "")
    screens, _ = merge_readings([(4000, one), (12000, two)], 8000, 16_000, "m")
    assert len(screens) == 2
