import json
import threading

from bedrock.turn import ModelTurn, ToolCall
from graph.lenses import run_lenses
from graph.span import Span
from graph.state import Claim
from loop.quality import Ledger, run
from loop.store import MemoryStore
from media.compact import IndexedSpan
from registry.ids import LENS_ORDER, lens_id
from support import registry


class Scripted:
    def __init__(self):
        self.queues = {}
        self.calls = []
        self._lock = threading.Lock()

    def push(self, prompt_id, output, tool_calls=None):
        self.queues.setdefault(prompt_id, []).append(
            ModelTurn(output=output, tool_calls=tool_calls or [])
        )

    def complete(self, *, prompt_id, role, payload, max_output_tokens=None):
        with self._lock:
            self.calls.append({"prompt_id": prompt_id, "role": role, "payload": payload})
            return self.queues[prompt_id].pop(0)


def _span(span_id, text, start_ms, end_ms):
    return Span(
        id=span_id,
        meeting_id="m",
        kind="speech",
        start_ms=start_ms,
        end_ms=end_ms,
        raw_text=text,
        text=text,
    )


def test_blind_lenses_run_all_ten_without_seeing_each_other():
    model = Scripted()
    secret = "LENS-SECRET"
    for dimension in LENS_ORDER:
        if dimension == "decision":
            model.push(
                lens_id(dimension),
                {
                    "result": "findings",
                    "findings": [
                        {"id": "f-dec", "stance": "supports", "claim_ids": ["c1"], "text": secret}
                    ],
                },
            )
        else:
            model.push(lens_id(dimension), {"result": "none_in_transcript"})
    claim = Claim(
        id="c1",
        meeting_id="m",
        kind="decision",
        proposition="The team adopted the plan.",
        paraphrase="The plan was adopted.",
        quote="adopted the plan",
        status="supported",
        span_id="s1",
    )
    result = run_lenses(model, registry(), [claim])
    assert set(result["dimensions"]) == set(LENS_ORDER)
    assert result["dimensions"]["commitment"] == "none_in_transcript"
    assert len(model.calls) == 10
    roles = {call["prompt_id"]: call["role"] for call in model.calls}
    assert roles[lens_id("decision")] == "slm"
    assert roles[lens_id("stakeholder")] == "llm"
    assert roles[lens_id("risk")] == "llm"
    for call in model.calls:
        assert secret not in json.dumps(call["payload"])


def test_publish_loop_keeps_overlap_and_excludes_unanchored_due_dates():
    model = Scripted()
    model.push("meeting.compaction.v1", {"omit_ids": ["sil", "ov"]})
    model.push(
        "meeting.claim.v1",
        {
            "claims": [
                {
                    "id": "c1",
                    "kind": "commitment",
                    "proposition": "The team will ship the notes.",
                    "paraphrase": "Shipping the notes is planned.",
                    "quote": "ship the notes",
                    "decision_status": None,
                }
            ],
            "gaps": [],
        },
    )
    model.push(
        "meeting.counterevidence.v1",
        {},
        [ToolCall("open_span", {"span_id": "s1"})],
    )
    model.push(
        "meeting.counterevidence.v1",
        {"searched_ids": ["s1"], "contradicting_quote": None},
    )
    model.push("meeting.entailment.v1", {"label": "entails"})
    model.push("meeting.entailment_luna.v1", {"label": "entails"})
    model.push("meeting.coverage.v1", {"uncovered_span_ids": ["s2"]})
    model.push(
        "meeting.supplement.v1",
        {"items": [{"span_id": "s2", "outcome": "omission", "reason": "closing courtesy"}]},
    )
    draft = {
        "statement": "Ship the notes",
        "owner_span_id": None,
        "agreement_span_id": None,
        "due_kind": "relative",
        "due_surface": "by next Friday",
        "due_iso": "2026-10-16",
        "due_span_id": "s1",
        "claim_ids": ["c1"],
        "origin": "model",
        "acceptance": "proposed",
    }
    for dimension in LENS_ORDER:
        if dimension == "commitment":
            model.push(
                lens_id(dimension),
                {
                    "result": "findings",
                    "findings": [
                        {
                            "id": "f1",
                            "stance": "supports",
                            "claim_ids": ["c1"],
                            "text": "Commitment to ship notes",
                            "decision_status": None,
                            "actions": [draft],
                        }
                    ],
                },
            )
        else:
            model.push(lens_id(dimension), {"result": "none_in_transcript"})
    model.push(
        "meeting.synthesis.v1",
        {"sentences": [{"text": "Shipping the notes is planned.", "finding_ids": ["f1"]}]},
    )
    model.push("meeting.dissent.v1", {"dropped_ids": [], "softened_ids": []})
    model.push("meeting.chart.v1", {"aggregation": "count", "cells": [], "span_ids": ["s1"]})
    spans = [
        _span("s1", "please ship the notes today", 0, 1000),
        _span("s2", "thanks everyone", 1000, 1500),
    ]
    ledger = Ledger(
        meeting_id="m",
        duration_ms=2000,
        kind="video",
        spans=spans,
        index=[
            IndexedSpan("sil", "silence", 1500, 1800),
            IndexedSpan("ov", "overlap", 0, 200, overlap=True),
            IndexedSpan("sp", "speech", 0, 1500),
        ],
    )
    store = MemoryStore()
    result = run(ledger, model, registry(), store, "job-1")
    sol = next(call for call in model.calls if call["prompt_id"] == "meeting.entailment.v1")
    assert "The team will ship the notes." not in json.dumps(sol["payload"])
    synthesis = next(call for call in model.calls if call["prompt_id"] == "meeting.synthesis.v1")
    assert "please ship the notes today" not in json.dumps(synthesis["payload"])
    assert {call["prompt_id"] for call in model.calls if call["prompt_id"].startswith("meeting.lens_")} == {
        lens_id(dimension) for dimension in LENS_ORDER
    }
    by_id = {span.id: span for span in ledger.index}
    assert by_id["sil"].omitted is True
    assert by_id["ov"].omitted is False
    assert result.status == "ready"
    assert result.brief["claim_ids"] == ["c1"]
    assert result.actions[0].due_iso is None
    assert result.actions[0].acceptance == "proposed"
    assert result.actions[0].due_surface == "by next Friday"
    assert result.chart["result"] == 1
    calls = len(model.calls)
    replay = run(ledger, model, registry(), store, "job-1")
    assert replay is result
    assert len(model.calls) == calls


def test_second_dissent_drop_stays_on_the_graph():
    model = Scripted()
    model.push("meeting.claim.v1", {"claims": [], "gaps": [{"span_ids": ["s1"], "reason": "ambiguous"}]})
    for dimension in LENS_ORDER:
        if dimension == "risk":
            model.push(
                lens_id(dimension),
                {
                    "result": "findings",
                    "findings": [
                        {
                            "id": "f-risk",
                            "stance": "conflicts",
                            "claim_ids": [],
                            "text": "A conflict remains",
                        }
                    ],
                },
            )
        else:
            model.push(lens_id(dimension), {"result": "none_in_transcript"})
    # The risk finding cites no supported claim, so the publish gate drops it.
    # Drive dissent through a supported finding instead.
    model.queues[lens_id("risk")] = [
        ModelTurn(
            output={
                "result": "findings",
                "findings": [
                    {
                        "id": "f-risk",
                        "stance": "conflicts",
                        "claim_ids": ["c1"],
                        "text": "The dates conflict",
                    }
                ],
            }
        )
    ]
    model.push(
        "meeting.claim.v1",
        {
            "claims": [
                {
                    "id": "c1",
                    "kind": "observation",
                    "proposition": "The dates conflict in the notes.",
                    "paraphrase": "The notes contain a date conflict.",
                    "quote": "dates conflict",
                    "decision_status": None,
                }
            ],
            "gaps": [],
        },
    )
    # Replace the empty claim push above by reconstructing the queue order.
    model.queues["meeting.claim.v1"] = [
        ModelTurn(
            output={
                "claims": [
                    {
                        "id": "c1",
                        "kind": "observation",
                        "proposition": "The dates conflict in the notes.",
                        "paraphrase": "The notes contain a date conflict.",
                        "quote": "dates conflict",
                        "decision_status": None,
                    }
                ],
                "gaps": [],
            }
        )
    ]
    model.push("meeting.counterevidence.v1", {}, [ToolCall("open_span", {"span_id": "s1"})])
    model.push("meeting.counterevidence.v1", {"searched_ids": ["s1"], "contradicting_quote": None})
    model.push("meeting.entailment.v1", {"label": "entails"})
    model.push("meeting.entailment_luna.v1", {"label": "entails"})
    model.push("meeting.synthesis.v1", {"sentences": [{"text": "A softer sentence.", "finding_ids": []}]})
    model.push("meeting.dissent.v1", {"dropped_ids": ["f-risk"], "softened_ids": []})
    model.push("meeting.synthesis.v1", {"sentences": [{"text": "Still softened.", "finding_ids": []}]})
    model.push("meeting.dissent.v1", {"dropped_ids": ["f-risk"], "softened_ids": []})
    model.push("meeting.chart.v1", {"charts": []})
    ledger = Ledger(
        meeting_id="m",
        duration_ms=1000,
        kind="audio",
        spans=[_span("s1", "the dates conflict here", 0, 1000)],
    )
    result = run(ledger, model, registry(), MemoryStore(), "job-2")
    assert any(item.finding_id == "f-risk" for item in result.synthesis_omissions)
    assert any(item.id == "f-risk" for item in result.findings)
    assert result.brief is None or "f-risk" not in (result.brief or {}).get("finding_ids", [])


def test_iteration_ceiling_withholds_the_brief():
    model = Scripted()
    ledger = Ledger(
        meeting_id="m",
        duration_ms=1000,
        kind="audio",
        spans=[_span("s1", "hello", 0, 1000)],
        index=[IndexedSpan("sil", "silence", 0, 100)],
    )
    result = run(ledger, model, registry(), MemoryStore(), "job-3", iteration_ceiling=0)
    assert result.status == "needs_review"
    assert result.brief is None
    assert model.calls == []


def test_resolved_owner_is_accepted_during_the_run_and_human_rows_remain():
    from graph.actions import ground_action
    from graph.state import Action, Finding
    from loop.quality import _actions

    span = _span("s1", "Ada will send the notes", 0, 1000)
    span.speaker_hypothesis_id = "h1"
    bare = _span("s2", "I will send it.", 0, 500)
    loaded = registry()
    draft = {
        "statement": "Send the notes",
        "owner_span_id": "s1",
        "due_kind": "none",
        "claim_ids": ["c1"],
        "origin": "model",
        "acceptance": "proposed",
    }
    accepted = ground_action(draft, loaded, [span], quote="send the notes", anchor_date=None)
    assert accepted.acceptance == "accepted"
    assert accepted.owner_span_id == "s1"
    assert accepted.origin == "model"
    cleared = ground_action(
        {**draft, "owner_span_id": "s2", "statement": "Send it"},
        loaded,
        [bare],
        quote="I will send it.",
        anchor_date=None,
    )
    assert cleared.owner_span_id is None
    assert cleared.acceptance == "proposed"
    ledger = Ledger(meeting_id="m", duration_ms=1000, kind="audio", spans=[span])
    finding = Finding(
        id="f1",
        dimension="commitment",
        stance="supports",
        claim_ids=["c1"],
        text="Send the notes",
        action_drafts=[draft],
    )
    claim = Claim(
        id="c1",
        meeting_id="m",
        kind="commitment",
        proposition="Ada will send the notes.",
        paraphrase="Ada will send the notes.",
        quote="send the notes",
        status="supported",
    )
    human = Action(
        statement="Keep the human row",
        owner_span_id=None,
        agreement_span_id=None,
        due_kind="none",
        due_surface=None,
        due_iso=None,
        due_span_id=None,
        claim_ids=["c-human"],
        origin="human",
        acceptance="accepted",
    )
    ledger.previous_actions = [human]
    stored = _actions(ledger, loaded, [finding], [claim])
    assert any(item.origin == "model" and item.acceptance == "accepted" and item.owner_span_id == "s1" for item in stored)
    assert any(item.origin == "human" and item.acceptance == "accepted" for item in stored)


def test_missing_decision_status_finishes_in_the_review_queue():
    import json
    from pathlib import Path

    from graph.lenses import apply_decision_status
    from graph.publish import gate
    from graph.state import Finding
    from support import dimensions

    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts/schemas/meeting.lens_decision.v1.json").read_text()
    )
    span = _span("s1", "the team adopted the plan", 0, 1000)

    def claim(status_value=None):
        return Claim(
            id="c1",
            meeting_id="m",
            kind="decision",
            proposition="The team adopted the plan.",
            paraphrase="The plan was adopted.",
            quote="adopted the plan",
            status="supported",
            span_id="s1",
            decision_status=status_value,
        )

    filled = claim()
    apply_decision_status(
        [filled],
        [Finding(id="f-dec", dimension="decision", stance="supports", claim_ids=["c1"], text="aligned", decision_status="aligned")],
        schema,
    )
    assert filled.decision_status == "aligned"
    assert filled.status == "supported"
    invented = claim()
    apply_decision_status(
        [invented],
        [Finding(id="f-dec", dimension="decision", stance="supports", claim_ids=["c1"], text="maybe", decision_status="maybe")],
        schema,
    )
    assert invented.decision_status is None
    assert invented.status == "unresolved"
    absent = claim()
    finding = Finding(
        id="f-dec",
        dimension="decision",
        stance="supports",
        claim_ids=["c1"],
        text="no status",
        decision_status=None,
    )
    apply_decision_status([absent], [finding], schema)
    assert absent.status == "unresolved"
    result = gate(
        meeting_id="m",
        duration_ms=1000,
        spans=[span],
        claims=[absent],
        findings=[finding],
        sentences=[],
        synthesis_omissions=[],
        actions=[],
        disagreements=[],
        omissions=[],
        gaps=[],
        dimensions=dimensions(),
        ceiling_hit=False,
    )
    assert result.status == "needs_review"
    assert "c1" in result.review_queue
    assert "c1" not in result.brief["claim_ids"]
