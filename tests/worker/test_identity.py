from dataclasses import dataclass

from identity.resolve import clean_name, reconcile, resolve_visual, same_person


@dataclass
class S:
    id: str
    name: str
    speaking: bool
    start_ms: int
    end_ms: int


def turns(*rows):
    return [(a * 1000, b * 1000, v) for a, b, v in rows]


def test_clean_name_rejects_devices_numbers_and_roles():
    assert clean_name("Maddy (Host)") == "Maddy"
    assert clean_name("jason lee") == "Jason Lee"
    assert clean_name("Jason's iPhone") == "Jason"
    assert clean_name("Ly Ha | Tomsoft") == "Ly Ha"
    for bad in ("Fireflies.ai Notetaker Ly", "Otter.ai Notetaker", "Rafi Must...", "Surende…", "iPhone", "Guest", "+61 400 123 456", "a@b.com", "Zoom User", "", None, 5, "12345", "Meeting Room"):
        assert clean_name(bad) is None


def test_a_misread_letter_is_the_same_person_and_the_common_spelling_wins():
    assert same_person("Ly Ha", "Ly Ho") and not same_person("Mark Smith", "Maddy Smith")
    intervals = turns((0, 60, "spk_0"))
    sights = [S("a", "Ly Ha | Tomsoft", True, 0, 20_000), S("b", "Ly Ho", True, 20_000, 25_000), S("c", "Ly Ha", True, 25_000, 60_000)]
    found, _ = resolve_visual(intervals, sights)
    assert [(i.speaker, i.name) for i in found] == [("spk_0", "Ly Ha")]


def test_a_notetaker_bot_tile_never_becomes_a_speaker():
    intervals = turns((0, 60, "spk_0"))
    found, _ = resolve_visual(intervals, [S("a", "Fireflies.ai Notetaker Ly", True, 0, 60_000)])
    assert found == []


def test_same_person_is_prefix_not_surname():
    assert same_person("Maddy", "Maddy Smith")
    assert not same_person("Maddy Smith", "Mark Smith")
    assert not same_person("Jason", "Jasmine")


def test_active_speaker_mark_names_a_voice():
    intervals = turns((0, 30, "spk_0"), (30, 60, "spk_1"))
    sights = [S("a", "Jason", True, 0, 28_000), S("b", "Maddy", True, 31_000, 58_000), S("c", "Maddy", False, 0, 60_000)]
    found, merges = resolve_visual(intervals, sights)
    assert {i.speaker: i.name for i in found} == {"spk_0": "Jason", "spk_1": "Maddy"}
    assert merges == []


def test_a_single_flash_is_not_enough():
    intervals = turns((0, 60, "spk_0"))
    found, _ = resolve_visual(intervals, [S("a", "Jason", True, 0, 3_000)])
    assert found == []  # three seconds is a flash


def test_conflicting_names_for_one_voice_name_nobody():
    intervals = turns((0, 60, "spk_0"))
    sights = [S("a", "Jason", True, 0, 15_000), S("b", "Maddy", True, 15_000, 30_000),
              S("c", "Jason", True, 30_000, 45_000), S("d", "Maddy", True, 45_000, 60_000)]
    found, _ = resolve_visual(intervals, sights)
    assert found == []  # no clear lead


def test_one_person_split_across_two_voices_is_merged():
    intervals = turns((0, 20, "spk_0"), (25, 45, "spk_3"), (45, 60, "spk_1"))
    sights = [S("a", "Maddy", True, 0, 20_000), S("b", "Maddy", True, 25_000, 45_000), S("c", "Jason", True, 45_000, 60_000),
              S("d", "Jason", True, 46_000, 50_000)]
    found, merges = resolve_visual(intervals, sights)
    names = {i.speaker: i for i in found}
    assert set(names) == {"spk_0", "spk_1"} or set(names) == {"spk_3", "spk_1"}
    keep = next(i for i in found if i.name == "Maddy")
    assert merges and merges[0][0] == keep.speaker and len(keep.merged) == 1


def test_two_voices_that_talk_over_each_other_are_not_merged():
    intervals = turns((0, 40, "spk_0"), (10, 50, "spk_1"))
    sights = [S("a", "Maddy", True, 0, 40_000), S("b", "Maddy", True, 10_000, 50_000), S("c", "Maddy", True, 5_000, 20_000)]
    found, merges = resolve_visual(intervals, sights)
    assert merges == []
    assert len([i for i in found if i.name == "Maddy"]) <= 1


def test_a_person_always_on_the_stage_does_not_name_every_voice():
    # Ly is marked speaking almost the whole time, but only one voice talks for most of it, and another voice
    # (someone else, answering) talks while the mark is still on Ly: the mark does not tell them apart,
    # so the voice that talks far more gets the name and the other stays unnamed.
    intervals = turns((0, 200, "spk_2"), (200, 240, "spk_3"), (240, 400, "spk_2"), (400, 420, "spk_1"))
    sights = [S("a", "Ly Ho", True, 0, 400_000), S("b", "Ravi Goyat", True, 400_000, 420_000)]
    found, merges = resolve_visual(intervals, sights)
    names = {i.speaker: i.name for i in found}
    assert names.get("spk_2") == "Ly Ho" and "spk_3" not in names and merges == []
    assert names.get("spk_1") == "Ravi Goyat"


def test_a_mark_that_follows_the_voice_names_it_and_a_split_voice_is_merged():
    intervals = turns((0, 60, "spk_0"), (60, 120, "spk_1"), (120, 180, "spk_2"), (180, 240, "spk_0"))
    sights = [S("a", "Maddy", True, 0, 60_000), S("b", "Maddy", True, 180_000, 240_000), S("c", "Jason", True, 60_000, 120_000), S("d", "Jason", True, 120_000, 180_000)]
    found, merges = resolve_visual(intervals, sights)
    assert {i.speaker: i.name for i in found} == {"spk_0": "Maddy", "spk_1": "Jason"} or merges
    assert any(keep == "spk_1" and gone == "spk_2" for keep, gone in merges) or any(keep == "spk_2" and gone == "spk_1" for keep, gone in merges)


def test_a_wall_of_name_tiles_without_a_speaking_mark_names_nobody():
    intervals = turns((0, 30, "spk_0"), (30, 60, "spk_1"))
    sights = [S("a", "Jason", False, 0, 60_000), S("b", "Maddy", False, 0, 60_000)]
    found, _ = resolve_visual(intervals, sights)
    assert found == []


def test_a_speaker_view_label_names_the_voice_weakly():
    intervals = turns((0, 60, "spk_0"))
    sights = [S("a", "Jason", False, 0, 30_000), S("b", "Jason", False, 30_000, 60_000)]
    found, _ = resolve_visual(intervals, sights)
    assert [(i.speaker, i.name) for i in found] == [("spk_0", "Jason")]
    assert found[0].confidence < 0.6  # weak evidence stays below the trust line for a conflict


def test_reconcile_priorities():
    intervals = turns((0, 60, "spk_0"))
    seen, _ = resolve_visual(intervals, [S("a", "Jason Lee", True, 0, 30_000), S("b", "Jason Lee", True, 30_000, 60_000)])
    out = reconcile(seen, {"spk_0": "Jason"}, {})
    assert out["spk_0"].name == "Jason Lee" and out["spk_0"].source == "visual+audio"
    out = reconcile(seen, {"spk_0": "Priya"}, {})
    assert out["spk_0"].name == "Jason Lee" and out["spk_0"].conflict == "Priya"
    out = reconcile(seen, {"spk_0": "Priya"}, {"spk_0": "Ravi"})
    assert out["spk_0"].name == "Ravi" and out["spk_0"].source == "user"
    out = reconcile([], {"spk_2": "Ravi"}, {})
    assert out["spk_2"].source == "audio"


def test_a_mark_that_never_lets_up_names_nobody():
    intervals = turns((0, 200, "spk_2"), (200, 240, "spk_3"), (240, 420, "spk_2"))
    found, merges = resolve_visual(intervals, [S("a", "Ly Ho", True, 0, 420_000)])
    assert found == [] and merges == []
