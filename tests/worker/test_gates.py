import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from support import dimensions, registry
from errors import ChartRejected, DimensionSkipped, RegistryMissing, SchemaRejected
from graph.actions import accept_action, merge_actions, owner_display, retain_durable
from graph.audit import hypothesis_stats
from graph.chart import commit_plot, compute, load_cells, render
from graph.claim import finalize_claim
from graph.cross import record_cross
from graph.publish import gate
from graph.quote import resolve_quote
from graph.span import Span
from graph.state import Claim, Finding, Sentence
from graph.union import union_length
from pegasus.client import VisualNote


def speech(span_id, text, **kwargs):
    return Span(
        id=span_id,
        meeting_id=kwargs.pop("meeting_id", "m"),
        kind="speech",
        start_ms=kwargs.pop("start_ms", 0),
        end_ms=kwargs.pop("end_ms", 1000),
        raw_text=text,
        text=text,
        **kwargs,
    )


def claim_for(span, proposition, quote, **kwargs):
    return Claim(
        id=kwargs.pop("id", "c1"),
        meeting_id=span.meeting_id,
        kind=kwargs.pop("kind", "figure"),
        proposition=proposition,
        paraphrase=kwargs.pop("paraphrase", "paraphrase away from the proposition"),
        quote=quote,
        searched_ids=kwargs.pop("searched_ids", [span.id]),
        opened_ids=kwargs.pop("opened_ids", [span.id]),
        luna_label=kwargs.pop("luna_label", "entails"),
        sol_label=kwargs.pop("sol_label", "entails"),
        **kwargs,
    )


def publish(spans, claims, findings=None, sentences=None, **kwargs):
    return gate(
        meeting_id="m",
        duration_ms=kwargs.pop("duration_ms", 10_000),
        spans=spans,
        claims=claims,
        findings=findings or [],
        sentences=sentences or [],
        synthesis_omissions=kwargs.pop("synthesis_omissions", []),
        actions=kwargs.pop("actions", []),
        disagreements=[],
        omissions=kwargs.pop("omissions", []),
        gaps=[],
        dimensions=kwargs.pop("dimensions", dimensions()),
        ceiling_hit=kwargs.pop("ceiling_hit", False),
    )


def test_quote_resolution_requires_exactly_one_hit():
    only = speech("s1", "The margin is 50.")
    other = speech("s2", "The margin is 50.", start_ms=1000, end_ms=2000)
    zero = resolve_quote("missing words", [only], meeting_id="m", duration_ms=10_000)
    assert zero.status == "unresolved" and zero.hits == 0
    two = resolve_quote("The margin is 50.", [only, other], meeting_id="m", duration_ms=10_000)
    assert two.status == "unresolved" and two.hits == 2
    one = resolve_quote("The margin is 50.", [only], meeting_id="m", duration_ms=10_000)
    assert one.status == "resolved"
    assert only.text[one.char_start : one.char_end] == "The margin is 50."
    assert (one.start_ms, one.end_ms) == (0, 1000)
    foreign = speech("s9", "The margin is 50.", meeting_id="other")
    assert resolve_quote("The margin is 50.", [foreign], meeting_id="m", duration_ms=10_000).status == "unresolved"


def test_fifteen_percent_against_fifty_stays_out_of_the_brief():
    span = speech("s1", "The margin is 50.")
    claim = finalize_claim(
        claim_for(span, "The margin is 15%.", "The margin is 50."),
        [span],
        duration_ms=10_000,
    )
    assert claim.status == "unresolved"
    result = publish([span], [claim])
    assert result.status == "needs_review"
    assert claim.id in result.review_queue
    assert claim.id not in result.brief["claim_ids"]


def test_percent_must_match_unit_and_direction_and_word_forms():
    span = speech("s1", "The margin is 15 percent.")
    matched = finalize_claim(claim_for(span, "The margin is 15%.", "The margin is 15 percent."), [span], duration_ms=10_000)
    assert matched.status == "supported"
    bare = speech("s2", "The margin is 15.")
    unit = finalize_claim(claim_for(bare, "The margin is 15%.", "The margin is 15.", id="c2"), [bare], duration_ms=10_000)
    assert unit.status == "unresolved"
    down = speech("s3", "Costs rose 15%.")
    direction = finalize_claim(
        claim_for(down, "Costs fell 15%.", "Costs rose 15%.", id="c3"),
        [down],
        duration_ms=10_000,
    )
    assert direction.status == "unresolved"
    words = speech("s4", "The margin is 15%.")
    verbal = finalize_claim(
        claim_for(words, "The margin is fifteen percent.", "The margin is 15%.", id="c4"),
        [words],
        duration_ms=10_000,
    )
    assert verbal.status == "supported"
    couple = speech("s5", "We need a couple percent.")
    unsettled = finalize_claim(
        claim_for(couple, "We need a couple percent.", "We need a couple percent.", id="c5"),
        [couple],
        duration_ms=10_000,
    )
    assert unsettled.status == "unresolved"
    clock = speech("s6", "Call at 3:00.")
    timed = finalize_claim(claim_for(clock, "Call at 3:00.", "Call at 3:00.", id="c6"), [clock], duration_ms=10_000)
    assert timed.status == "supported"
    bare_clock = speech("s7", "Call at 3.")
    assert (
        finalize_claim(claim_for(bare_clock, "Call at 3:00.", "Call at 3.", id="c7"), [bare_clock], duration_ms=10_000).status
        == "unresolved"
    )


def test_empty_search_or_one_model_does_not_publish():
    span = speech("s1", "Ship the notes.")
    empty = finalize_claim(
        claim_for(span, "Ship the notes.", "Ship the notes.", searched_ids=[], opened_ids=[]),
        [span],
        duration_ms=10_000,
    )
    assert empty.status == "unresolved"
    split = finalize_claim(
        claim_for(span, "Ship the notes.", "Ship the notes.", id="c2", sol_label="neutral"),
        [span],
        duration_ms=10_000,
    )
    assert split.status == "gap"
    result = publish([span], [empty, split])
    assert result.status == "needs_review"
    assert "c1" not in result.brief["claim_ids"]
    assert "c2" not in result.brief["claim_ids"]
    note = VisualNote(id="n1", statement="a light")
    assert note.can_support_claim is False
    uncited = finalize_claim(
        claim_for(span, "A light flickered.", "Ship the notes.", id="c3", evidence_kind="uncited_note"),
        [span],
        duration_ms=10_000,
    )
    assert uncited.status == "unresolved"


def test_owner_string_fails_schema_and_relative_due_stays_unanchored():
    span = speech("s1", "I will send it.", speaker_hypothesis_id=None)
    with pytest.raises(SchemaRejected):
        accept_action(
            {
                "statement": "Send it",
                "owner": "Ada",
                "due_kind": "none",
                "claim_ids": ["c1"],
                "origin": "model",
                "acceptance": "proposed",
            },
            registry(),
            [span],
            quote="I will send it.",
            anchor_date=None,
        )
    action = accept_action(
        {
            "statement": "Send it",
            "owner_span_id": "s1",
            "agreement_span_id": None,
            "due_kind": "relative",
            "due_surface": "by next Friday",
            "due_iso": "2026-10-16",
            "due_span_id": "s1",
            "claim_ids": ["c1"],
            "origin": "model",
            "acceptance": "accepted",
        },
        registry(),
        [span],
        quote="by next Friday",
        anchor_date=None,
    )
    assert action.due_iso is None
    assert action.due_surface == "by next Friday"
    assert action.acceptance == "proposed"
    assert action.owner_span_id is None
    assert owner_display(action, {"s1": span}) == "not stated"
    named = speech("s2", "Ada will send it.", speaker_hypothesis_id="h1")
    kept = accept_action(
        {
            "statement": "Send it",
            "owner_span_id": "s2",
            "due_kind": "absolute",
            "due_iso": "2026-10-16",
            "claim_ids": ["c1"],
            "origin": "model",
            "acceptance": "proposed",
        },
        registry(),
        [named],
        quote="due 2026-10-16",
        anchor_date=None,
    )
    assert kept.owner_span_id == "s2"
    assert kept.due_iso == "2026-10-16"
    human = accept_action(
        {
            "statement": "Send it",
            "due_kind": "none",
            "claim_ids": ["c1"],
            "origin": "human",
            "acceptance": "accepted",
        },
        registry(),
        [named],
        quote="",
        anchor_date=None,
    )
    regenerated = retain_durable([human], [action])
    assert any(item.origin == "human" and item.acceptance == "accepted" for item in regenerated)
    duplicate = merge_actions([kept, kept])
    assert len(duplicate) == 1


def test_chart_numeric_literal_fails_before_render_and_workbook_value_is_plotted(tmp_path):
    class Boom(dict):
        def __getitem__(self, key):
            raise AssertionError("renderer ran")

    with pytest.raises(ChartRejected):
        compute({"aggregation": "sum", "cells": ["Sheet1!B2"], "limit": 1}, cells=Boom(), spans={})
    book_path = tmp_path / "cells.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["B2"] = 50
    book.save(book_path)
    book.close()
    cells = load_cells(book_path)
    table = compute({"aggregation": "sum", "cells": ["Sheet1!B2"], "span_ids": []}, cells=cells, spans={})
    assert table.result == 50
    assert render(table)["result"] == 50
    assert cells["Sheet1!B2"] == 50
    artifact = tmp_path / "chart.json"
    artifact.write_text("{}", encoding="utf-8")
    assert commit_plot(artifact, table, [50.0], 999) is None
    assert not artifact.exists()
    written = commit_plot(tmp_path / "ok.json", table, [50.0], 50)
    assert json.loads(Path(written).read_text())["result"] == 50
    left = speech("a", "a", start_ms=0, end_ms=10)
    right = speech("b", "b", start_ms=5, end_ms=15)
    union = compute(
        {"aggregation": "duration_union", "cells": [], "span_ids": ["a", "b"]},
        cells={},
        spans={"a": left, "b": right},
    )
    assert union.result == 15
    assert union_length([(0, 10), (5, 15)]) == 15


def test_unsupported_finding_and_empty_synthesis_are_dropped():
    span = speech("s1", "Ship the notes.")
    bad = finalize_claim(
        claim_for(span, "The margin is 15%.", "Ship the notes.", kind="observation"),
        [span],
        duration_ms=10_000,
    )
    finding = Finding(id="f1", dimension="gap", stance="supports", claim_ids=[bad.id], text="not supported")
    sentence = Sentence(text="no ids", finding_ids=[])
    cited = Sentence(text="cites the dropped finding", finding_ids=["f1"])
    result = publish([span], [bad], [finding], [sentence, cited])
    assert "f1" not in {item.id for item in result.findings}
    assert result.synthesis == []
    assert bad.id not in result.brief["claim_ids"]


def test_skipping_a_dimension_fails_and_a_ceiling_withholds_the_brief():
    span = speech("s1", "Ship the notes.")
    claim = finalize_claim(claim_for(span, "Ship the notes.", "Ship the notes.", kind="observation"), [span], duration_ms=10_000)
    assert claim.status == "supported"
    dims = dimensions()
    del dims["risk"]
    with pytest.raises(DimensionSkipped):
        publish([span], [claim], dimensions=dims)
    result = publish([span], [claim], ceiling_hit=True, dimensions={})
    assert result.status == "needs_review"
    assert result.brief is None


def test_cross_modal_disagreement_keeps_both_ids_and_raw_text():
    span = speech("s1", "We agreed to ship.")
    observation = type("Obs", (), {"id": "o1", "start_ms": 0, "end_ms": 1000, "statement": "the slide says wait"})()
    found = record_cross(
        span,
        observation,
        {
            "relation": "disagreement",
            "sonic_span_id": "s1",
            "observation_id": "o1",
            "statement": "speech says ship and the slide says wait",
            "merged": "one smoothed sentence",
        },
    )
    assert found.sonic_span_id == "s1" and found.observation_id == "o1"
    assert span.raw_text == "We agreed to ship."
    assert span.text == "We agreed to ship."
    assert record_cross(
        span,
        observation,
        {"relation": "agreement", "sonic_span_id": "s1", "observation_id": "o1"},
    ) is None


def test_hypothesis_durations_use_a_union_and_are_not_chart_measures():
    spans = [
        speech("a", "a", start_ms=0, end_ms=10, speaker_hypothesis_id="h"),
        speech("b", "b", start_ms=5, end_ms=15, speaker_hypothesis_id="h"),
    ]
    stats = hypothesis_stats(spans)
    assert stats["chart_measure"] is False
    assert stats["rows"][0]["duration_ms"] == 15
    assert stats["rows"][0]["turn_count"] == 2
    assert stats["rows"][0]["hypotheses"] is True


def test_repo_registry_routes_match_plan_pins():
    from registry.load import Registry, default_root
    from registry.ids import lens_id

    root = default_root()
    if not (root / "registry.json").is_file():
        pytest.skip("contracts registry is not on disk")
    loaded = Registry(root)
    assert loaded.prompt("meeting.claim.v1").model_role == "slm"
    assert loaded.prompt(lens_id("stakeholder")).model_role == "llm"
    assert loaded.prompt("meeting.chart.v1").model_role == "slm"
    assert loaded.schema("meeting.entailment.v1")["properties"]["label"]["enum"] == [
        "entails",
        "neutral",
        "contradicts",
    ]
    # Bugs vs Fixes
    # Bug: sonic, pegasus, continuation, and crossmodal now resolve in the repo
    # registry, so RegistryMissing no longer fires for those prompt ids.
    # Fix: load each route and assert its contract model_role.
    assert loaded.prompt("meeting.sonic.v1").model_role == "sonic"
    assert loaded.prompt("meeting.pegasus.v1").model_role == "pegasus"
    assert loaded.prompt("meeting.pegasus.continue.v1").model_role == "pegasus"
    assert loaded.prompt("meeting.crossmodal.v1").model_role == "llm"
    from graph.actions import action_schema
    from registry.check import validate

    with pytest.raises(SchemaRejected):
        validate(
            {
                "statement": "Send it",
                "owner": "Ada",
                "owner_span_id": None,
                "agreement_span_id": None,
                "due_kind": "none",
                "due_surface": None,
                "due_span_id": None,
                "claim_ids": ["c1"],
                "acceptance": "proposed",
            },
            action_schema(loaded),
        )


def test_missing_registry_id_fails_clearly(tmp_path):
    root = tmp_path / "contracts"
    root.mkdir()
    (root / "registry.json").write_text(json.dumps({"prompts": {}, "schemas": {}}), encoding="utf-8")
    from registry.load import Registry

    loaded = Registry(root)
    with pytest.raises(RegistryMissing, match="meeting.claim.v1"):
        loaded.prompt("meeting.claim.v1")
