import json
import threading
from types import SimpleNamespace

from bedrock.turn import ModelTurn, ToolCall
from graph.claim import finalize_claim
from graph.lenses import run_lenses
from graph.span import Span
from graph.state import Claim
from loop.quality import Budget, Ledger, _actions, _contest, run
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


def test_entailment_uses_the_validated_source_span_when_quote_repeats():
    first = _span("s1", "The budget is capped at $800.", 0, 1000)
    selected = _span("s2", "The budget is capped at $800.", 1000, 2000)
    ledger = Ledger(meeting_id="m", duration_ms=2000, kind="audio", spans=[first, selected])
    claim = Claim(
        id="c1",
        meeting_id="m",
        kind="figure",
        proposition="The budget is capped at $800.",
        paraphrase="The budget cap is eight hundred dollars.",
        quote="The budget is capped at $800.",
        source_span_ids=["s2"],
    )
    responses = [
        SimpleNamespace(output={}, tool_calls=[ToolCall("open_span", {"span_id": "s2"})]),
        SimpleNamespace(output={"searched_ids": ["s2"], "contradicting_quote": None}, tool_calls=[]),
    ]
    entailment_payloads = []

    def call(prompt_id, payload):
        if prompt_id == "meeting.counterevidence.v1":
            return responses.pop(0)
        entailment_payloads.append((prompt_id, payload))
        return SimpleNamespace(output={"label": "entails"}, tool_calls=[])

    _contest(ledger, call, claim)
    assert len(entailment_payloads) == 2
    assert all(payload["cited_span_texts"] == [selected.text] for _, payload in entailment_payloads)
    assert finalize_claim(claim, ledger.spans, duration_ms=ledger.duration_ms).status == "supported"


def test_supported_commitments_become_conservative_proposed_actions_when_lens_omits_them():
    span = _span("s-action", "Sam will collect two supplier quotes by Wednesday.", 0, 3000)
    claim = Claim(
        id="c-action",
        meeting_id="m",
        kind="commitment",
        proposition="Sam will collect supplier quotes.",
        paraphrase="Sam will collect two supplier quotes by Wednesday.",
        quote=span.text,
        span_id=span.id,
        status="supported",
    )
    ledger = SimpleNamespace(spans=[span], anchor_date=None, previous_actions=[])
    actions = _actions(ledger, registry(), [], [claim])
    assert len(actions) == 1
    assert actions[0].statement == claim.paraphrase
    assert actions[0].claim_ids == [claim.id]
    assert actions[0].owner_span_id is None
    assert actions[0].due_kind == "none"
    assert actions[0].acceptance == "proposed"


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
                    "span_ids": ["s1"],
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
    stages = []
    result = run(ledger, model, registry(), store, "job-1", stage_callback=stages.append)
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
    assert stages == [
        "Compacting transcript spans",
        "Checking audio against visual evidence",
        "Extracting claims from the transcript",
        "Checking transcript coverage",
        "Analyzing all ten evidence lenses",
        "Building the evidence-backed brief",
        "Extracting and grounding follow-up actions",
        "Writing the walkaway: summary, decisions, actions and topics",
        "Building charts and checking publish readiness",
    ]
    # The scripted model has no digest answer: the walkaway is skipped, the analysis still completes.
    assert result.digest is None
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
                    "span_ids": ["s1"],
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
                        "span_ids": ["s1"],
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


def test_default_quality_budget_does_not_stop_large_analyses_early():
    budget = Budget()
    assert all(budget.allow() for _ in range(1000))
    assert budget.used == 1000
    assert budget.hit is False


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
    # An owner alone is not agreement: the commitment lens contract keeps such a row proposed.
    owner_only = ground_action(draft, loaded, [span], quote="send the notes", anchor_date=None)
    assert owner_only.owner_span_id == "s1" and owner_only.acceptance == "proposed"
    unknown_agreement = ground_action({**draft, "agreement_span_id": "nowhere"}, loaded, [span], quote="send the notes", anchor_date=None)
    assert unknown_agreement.acceptance == "proposed"
    draft = {**draft, "agreement_span_id": "s1"}
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


def test_fallback_action_validates_against_the_shipped_contracts():
    from pathlib import Path

    from registry.load import Registry

    shipped = Registry(Path(__file__).resolve().parents[2] / "contracts")
    span = _span("s-action", "Sam will collect two supplier quotes by Wednesday.", 0, 3000)
    claim = Claim(
        id="c-action",
        meeting_id="m",
        kind="commitment",
        proposition="Sam will collect supplier quotes.",
        paraphrase="Sam will collect two supplier quotes by Wednesday.",
        quote=span.text,
        span_id=span.id,
        status="supported",
    )
    ledger = SimpleNamespace(spans=[span], anchor_date=None, previous_actions=[])
    actions = _actions(ledger, shipped, [], [claim])
    assert [item.claim_ids for item in actions] == [[claim.id]]
    assert actions[0].origin == "model"


def test_coverage_and_supplement_payloads_match_their_contracts():
    from pathlib import Path

    import yaml

    from loop.quality import _coverage

    root = Path(__file__).resolve().parents[2] / "contracts" / "prompts"

    def allowed(name):
        return set(yaml.safe_load((root / f"{name}.yaml").read_text())["input"]["include"])

    seen = []

    def call(prompt_id, payload):
        seen.append((prompt_id, payload))
        if prompt_id == "meeting.coverage.v1":
            return SimpleNamespace(output={"uncovered_span_ids": []}, tool_calls=[])
        items = [
            {"span_id": row["span_id"], "outcome": "omission", "reason": "pleasantry"}
            for row in payload["uncovered_spans"]
        ]
        return SimpleNamespace(output={"items": items}, tool_calls=[])

    spans = [_span(f"s{n}", f"line {n}", n * 1000, n * 1000 + 900) for n in range(45)]
    ledger = SimpleNamespace(spans=spans, meeting_id="m", duration_ms=45000)
    claims, gaps, omissions = [], [], []
    _coverage(ledger, call, claims, gaps, omissions)

    for prompt_id, payload in seen:
        name = prompt_id
        assert set(payload) <= allowed(name), (name, set(payload) - allowed(name))
        assert set(payload) == allowed(name), (name, allowed(name) - set(payload))
    batches = [payload for prompt_id, payload in seen if prompt_id == "meeting.supplement.v1"]
    assert [len(item["uncovered_spans"]) for item in batches] == [20, 20, 5]
    assert all(row["text"] for item in batches for row in item["uncovered_spans"])
    assert len(omissions) == 45
    # A derived uncovered set is authoritative even if the auditor reports none.
    assert {item.span_id for item in omissions} == {span.id for span in spans}


def test_a_failed_lens_is_not_evaluated_not_absent_and_blocks_ready():
    from errors import SchemaRejected
    from graph.lenses import run_lenses
    from loop.quality import Budget, _BudgetModel
    from registry.ids import LENS_ORDER

    class Failing:
        def complete(self, **_):
            raise SchemaRejected("bad")

    claim = Claim(id="c", meeting_id="m", kind="decision", proposition="p", paraphrase="p", quote="q", status="supported")
    wrapped = _BudgetModel(Failing(), Budget(), registry())
    result = run_lenses(wrapped, registry(), [claim])
    assert set(result["dimensions"].values()) == {"not_evaluated"}
    assert list(result["dimensions"]) == list(LENS_ORDER)

    from graph.publish import gate

    from graph.state import Omission

    span = _span("s1", "text", 0, 1000)
    covered = dict(
        meeting_id="m", duration_ms=1000, spans=[span], claims=[], findings=[], sentences=[],
        synthesis_omissions=[], actions=[], disagreements=[], omissions=[Omission(span_id="s1", reason="x")], gaps=[],
        ceiling_hit=False,
    )
    clean = gate(dimensions={name: "none_in_transcript" for name in LENS_ORDER}, **covered)
    assert clean.status == "ready"  # everything covered: only the lens state can change this
    outcome = gate(dimensions=result["dimensions"], **covered)
    assert outcome.status == "needs_review"


def test_one_failed_extraction_window_does_not_drop_later_windows():
    from loop.quality import _extract

    spans = [_span(f"s{n}", f"statement number {n} is here", n * 1000, n * 1000 + 900) for n in range(45)]
    ledger = SimpleNamespace(spans=spans, meeting_id="m", duration_ms=45000)
    seen = []

    def call(prompt_id, payload):
        seen.append(payload["spans"][0]["id"])
        if len(seen) == 1:
            return None
        return SimpleNamespace(output={"claims": [], "gaps": []}, tool_calls=[])

    _extract(ledger, call, [], [])
    assert seen == ["s0", "s20", "s40"]


def test_extraction_stops_after_three_consecutive_window_failures():
    from loop.quality import _extract

    spans = [_span(f"s{n}", f"statement number {n} is here", n * 1000, n * 1000 + 900) for n in range(120)]
    ledger = SimpleNamespace(spans=spans, meeting_id="m", duration_ms=120000)
    seen = []

    def call(prompt_id, payload):
        seen.append(payload["spans"][0]["id"])
        return None

    _extract(ledger, call, [], [])
    assert len(seen) == 3


def _tool_then_answer(first_calls, answer):
    """A model that first asks to open spans, then answers once it sees tool results."""
    from bedrock.turn import ModelTurn

    seen = []

    class Model:
        def complete(self, *, prompt_id, role, payload):
            seen.append(payload)
            if "tool_results" not in payload:
                return ModelTurn(output={}, tool_calls=first_calls)
            return ModelTurn(output=answer, tool_calls=[])

    return Model(), seen


def test_a_lens_that_opens_a_span_first_still_returns_its_findings():
    from bedrock.turn import ToolCall
    from graph.lenses import run_lenses
    from loop.quality import Budget, _BudgetModel
    from registry.ids import LENS_ORDER

    span = _span("s1", "Sam will send the budget by Friday.", 0, 2000)
    findings = {
        "result": "findings",
        "findings": [{"id": "f1", "stance": "supports", "claim_ids": ["c1"], "text": "Sam owns the budget", "decision_status": None}],
    }
    model, seen = _tool_then_answer([ToolCall("open_span", {"span_id": "s1"})], findings)
    claim = Claim(id="c1", meeting_id="m", kind="commitment", proposition="p", paraphrase="p", quote="q", status="supported")
    wrapped = _BudgetModel(model, Budget(), registry(), spans=[span], meeting_id="m")
    result = run_lenses(wrapped, registry(), [claim])
    assert all(isinstance(value, list) for value in result["dimensions"].values())
    assert len(result["findings"]) == len(LENS_ORDER)
    fill = [payload for payload in seen if "tool_results" in payload][0]
    assert fill["_fill"] is True
    assert fill["tool_results"][0]["text"] == span.text
    assert fill["claims"]  # the original input travels with the fill request


def test_a_lens_whose_tool_call_cannot_be_answered_is_not_evaluated_not_empty():
    from bedrock.turn import ToolCall
    from graph.lenses import run_lenses
    from loop.quality import Budget, _BudgetModel

    model, _ = _tool_then_answer([ToolCall("open_span", {"span_id": "does-not-exist"})], {"result": "none_in_transcript"})
    claim = Claim(id="c1", meeting_id="m", kind="commitment", proposition="p", paraphrase="p", quote="q", status="supported")
    wrapped = _BudgetModel(model, Budget(), registry(), spans=[_span("s1", "x", 0, 1)], meeting_id="m")
    result = run_lenses(wrapped, registry(), [claim])
    assert set(result["dimensions"].values()) == {"not_evaluated"}


def test_the_coverage_supplement_runs_its_open_span_tool_before_answering():
    from bedrock.turn import ModelTurn, ToolCall
    from loop.quality import _coverage

    spans = [_span(f"s{n}", f"filler line {n}", n * 1000, n * 1000 + 900) for n in range(3)]
    ledger = SimpleNamespace(spans=spans, meeting_id="m", duration_ms=3000)
    omit = {"items": [{"span_id": span.id, "outcome": "omission", "reason": "filler"} for span in spans]}

    def call(prompt_id, payload):
        if prompt_id == "meeting.coverage.v1":
            return ModelTurn(output={"uncovered_span_ids": [span.id for span in spans]}, tool_calls=[])
        if "tool_results" not in payload:
            return ModelTurn(output={}, tool_calls=[ToolCall("open_span", {"span_id": "s0"})])
        assert payload["uncovered_spans"]
        return ModelTurn(output=omit, tool_calls=[])

    omissions = []
    _coverage(ledger, call, [], [], omissions)
    assert {item.span_id for item in omissions} == {"s0", "s1", "s2"}


def test_lens_payload_shows_the_span_each_claim_cites_and_claim_ids_resolve_to_spans():
    from bedrock.turn import ToolCall
    from loop.quality import Budget, _BudgetModel

    span = _span("s1", "Sam will send the budget by Friday.", 0, 2000)
    claim = Claim(id="c1", meeting_id="m", kind="commitment", proposition="p", paraphrase="p", quote="q", status="supported", span_id="s1")
    seen = []

    class Model:
        def complete(self, *, prompt_id, role, payload):
            seen.append(payload)
            if "tool_results" not in payload:
                return ModelTurn(output={}, tool_calls=[ToolCall("open_span", {"span_id": "c1"})])  # a claim id
            return ModelTurn(output={"result": "none_in_transcript"}, tool_calls=[])

    wrapped = _BudgetModel(Model(), Budget(), registry(), spans=[span], meeting_id="m", aliases={"c1": "s1"})
    result = run_lenses(wrapped, registry(), [claim])
    assert seen[0]["claims"][0]["span_id"] == "s1"
    assert set(result["dimensions"].values()) == {"none_in_transcript"}  # answered, not "not evaluated"
    fill = [p for p in seen if "tool_results" in p][0]
    assert fill["tool_results"][0]["span_id"] == "s1"


def test_a_cancelled_meeting_stops_spending_model_calls():
    stopped = {"now": False}
    budget = Budget(should_stop=lambda: stopped["now"])
    assert budget.allow() is True
    stopped["now"] = True
    assert budget.allow() is False
    assert budget.hit is True


def test_a_lens_that_errors_at_the_provider_is_not_evaluated_but_missing_model_access_fails_loudly():
    import pytest

    from errors import NotInvocable
    from loop.quality import Budget, _BudgetModel

    claim = Claim(id="c1", meeting_id="m", kind="decision", proposition="p", paraphrase="p", quote="q", status="supported")

    class Flaky:
        def complete(self, **_):
            raise RuntimeError("internal_server_error")

    result = run_lenses(_BudgetModel(Flaky(), Budget(), registry()), registry(), [claim])
    assert set(result["dimensions"].values()) == {"not_evaluated"}

    class Denied:
        def complete(self, **_):
            raise NotInvocable("model", "ResourceNotFoundException")

    with pytest.raises(NotInvocable):
        run_lenses(_BudgetModel(Denied(), Budget(), registry()), registry(), [claim])


def test_coverage_counts_only_the_span_a_quote_resolved_to_like_the_gate_does():
    from loop.quality import _coverage

    spans = [_span("s1", "first", 0, 1000), _span("s2", "second", 1000, 2000)]
    ledger = SimpleNamespace(spans=spans, meeting_id="m", duration_ms=2000)
    claim = Claim(id="c", meeting_id="m", kind="decision", proposition="p", paraphrase="p", quote="first", status="supported", span_id="s1", source_span_ids=["s1", "s2"])
    asked = []

    def call(prompt_id, payload):
        if prompt_id == "meeting.supplement.v1":
            asked.append([row["span_id"] for row in payload["uncovered_spans"]])
            return ModelTurn(output={"items": [{"span_id": "s2", "outcome": "omission", "reason": "x"}]}, tool_calls=[])
        return ModelTurn(output={"uncovered_span_ids": ["s2"]}, tool_calls=[])

    omissions = []
    _coverage(ledger, call, [claim], [], omissions)
    assert asked == [["s2"]]  # s2 was only a candidate source, so it still needs closing
    assert [item.span_id for item in omissions] == ["s2"]


def test_a_failed_auditor_call_does_not_skip_the_supplement():
    from loop.quality import _coverage

    spans = [_span("s1", "only line", 0, 1000)]
    ledger = SimpleNamespace(spans=spans, meeting_id="m", duration_ms=1000)
    supplement_calls = []

    def call(prompt_id, payload):
        if prompt_id == "meeting.coverage.v1":
            return None
        supplement_calls.append(payload)
        return ModelTurn(output={"items": [{"span_id": "s1", "outcome": "omission", "reason": "x"}]}, tool_calls=[])

    omissions = []
    _coverage(ledger, call, [], [], omissions)
    assert len(supplement_calls) == 1 and len(omissions) == 1


def test_a_contradiction_that_actually_agrees_with_the_claim_is_dropped():
    from loop.quality import _verified_contradiction

    spans = [_span("s1", "i've tacked on this extra column", 0, 1000), _span("s2", "the pilot starts monday", 1000, 2000)]
    ledger = SimpleNamespace(spans=spans, meeting_id="m", duration_ms=2000)
    claim = Claim(id="c", meeting_id="m", kind="observation", proposition="p", paraphrase="An extra column has been added.", quote="q")

    def call(label):
        return lambda prompt_id, payload: SimpleNamespace(output={"label": label}, tool_calls=[])

    claim.contradicting_quote = "i've tacked on this extra column"
    assert _verified_contradiction(ledger, call("entails"), claim) is None  # it supports the claim
    assert _verified_contradiction(ledger, call("contradicts"), claim) == "i've tacked on this extra column"
    claim.contradicting_quote = "a sentence nobody said"
    assert _verified_contradiction(ledger, call("contradicts"), claim) is None  # not in the recording
    claim.contradicting_quote = None
    assert _verified_contradiction(ledger, call("contradicts"), claim) is None


def test_the_answer_check_can_answer_only_with_a_later_line_and_fails_soft():
    from loop.quality import _verify_questions

    spans = [_span("s1", "How does weighing work?", 0, 2000), _span("s2", "We integrate the scale and scanner.", 60_000, 64_000), _span("s3", "Unrelated aside.", 70_000, 72_000)]
    ledger = SimpleNamespace(spans=spans)
    digest = {"open_questions": [
        {"question": "How does weighing work?", "asked_span_id": "s1", "answered": False, "answer": None, "answer_span_id": None},
        {"question": "Will it rain?", "asked_span_id": "s1", "answered": False, "answer": None, "answer_span_id": None},
        {"question": "Already known", "asked_span_id": "s1", "answered": True, "answer": "yes", "answer_span_id": "s2"},
    ]}
    seen = []

    def call(prompt_id, payload):
        seen.append((prompt_id, payload["question"], [row["id"] for row in payload["lines_after"]]))
        if payload["question"] == "How does weighing work?":
            return ModelTurn(output={"answered": True, "answer_span_id": "s2", "answer": "Scale and scanner are integrated."}, tool_calls=[])
        return ModelTurn(output={"answered": True, "answer_span_id": "invented", "answer": "It will."}, tool_calls=[])

    out = _verify_questions(ledger, call, digest)
    first, second, third = out["open_questions"]
    assert (first["answered"], first["answer_span_id"], first["answer_ms"]) == (True, "s2", 60_000)
    assert second["answered"] is False and second["answer_span_id"] is None  # an invented line id is rejected
    assert third["answered"] is True  # the check confirmed it ("answered" with an unusable line id keeps the writer's answer)
    assert [item[0] for item in seen] == ["meeting.answer_check.v1"] * 3  # answered questions are checked too
    assert seen[0][2] == ["s2", "s3"]

    def failing(prompt_id, payload):
        return None

    again = _verify_questions(ledger, failing, {"open_questions": [{"question": "x", "asked_span_id": "s1", "answered": False}]})
    assert again["open_questions"][0]["answered"] is False


def test_a_neutral_counter_quote_is_not_a_contradiction():
    from loop.quality import _verified_contradiction

    span = _span("s1", "so it was technically feasible to connect networks together", 0, 3000)
    ledger = SimpleNamespace(spans=[span], meeting_id="m", duration_ms=3000)
    claim = Claim(id="c", meeting_id="m", kind="observation", proposition="p", paraphrase="It was technically feasible to connect networks.", quote="q", contradicting_quote="technically feasible to connect networks together")

    def verdict(label):
        return lambda prompt_id, payload: ModelTurn(output={"label": label}, tool_calls=[])

    assert _verified_contradiction(ledger, verdict("neutral"), claim) is None
    assert _verified_contradiction(ledger, verdict("entails"), claim) is None
    assert _verified_contradiction(ledger, verdict("contradicts"), claim) == "technically feasible to connect networks together"
    assert _verified_contradiction(ledger, verdict("contradicts"), Claim(id="d", meeting_id="m", kind="x", proposition="p", paraphrase="p", quote="q", contradicting_quote="words that are nowhere in the recording")) is None
