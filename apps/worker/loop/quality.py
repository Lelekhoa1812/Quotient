# Motivation vs Logic
# Motivation: The extractor does not verdict its own sentence, and a ceiling withholds the brief without shrinking output tokens.
# Logic: Compaction, claims, counterevidence, dual entailment, coverage, ten lenses, synthesis, dissent, chart, the publish gate, then a fail-open queue sort.

import sys
import threading
from dataclasses import dataclass, field

from errors import RegistryMissing, SchemaRejected
from graph.actions import ground_action, merge_actions, retain_durable
from graph.chart import compute, render
from graph.claim import finalize_claim
from graph.cross import overlapping, record_cross
from graph.publish import gate
from jev.sort import apply_order
from graph.state import Claim, Gap, Omission
from graph.synth import dissent_payload, dropped_ids, sentences_from, synthesis_omissions, synthesis_payload
from loop.pool import map_ordered
from media.compact import apply_omissions
from registry.ids import (
    CHART,
    CLAIM,
    COMPACTION,
    COUNTEREVIDENCE,
    COVERAGE,
    CROSSMODAL,
    DISSENT,
    ENTAILMENT_LUNA,
    ENTAILMENT_SOL,
    SUPPLEMENT,
    SYNTHESIS,
    lens_id,
)


@dataclass
class Ledger:
    meeting_id: str
    duration_ms: int
    kind: str
    spans: list
    index: list = field(default_factory=list)
    cells: dict = field(default_factory=dict)
    observations: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    anchor_date: str | None = None
    previous_actions: list = field(default_factory=list)


class Budget:
    def __init__(self, ceiling: int):
        self.ceiling = ceiling
        self.used = 0
        self.hit = False
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            if self.used >= self.ceiling:
                self.hit = True
                return False
            self.used += 1
            return True


def run(ledger: Ledger, model, registry, store, key: str, *, iteration_ceiling: int = 32, review_client=None):
    cached = store.get(key)
    if cached is not None:
        return cached
    budget = Budget(iteration_ceiling)

    def call(prompt_id: str, payload: dict):
        # Bugs vs Fixes
        # Bug: One empty array, or one Responses read that exceeded the socket
        # timeout, aborted the meeting before the publish gate could run.
        # Fix: Retry that call once, then skip the stage. The gate still
        # withholds a brief that fails its own checks.
        if not budget.allow():
            return None
        prompt = registry.prompt(prompt_id)

        def once(body: dict):
            return model.complete(prompt_id=prompt_id, role=prompt.model_role, payload=body)

        print(f"quality call: {prompt_id}", file=sys.stderr, flush=True)
        try:
            return once(payload)
        except (SchemaRejected, TimeoutError, RuntimeError) as exc:
            # Bugs vs Fixes
            # Bug: One Bedrock internal_server_error raised out of the loop and
            # marked the whole meeting failed before the publish gate.
            # Fix: Retry that call once, then skip the stage. A later gate
            # still withholds a brief that fails its own checks.
            if not budget.allow():
                return None
            repaired = dict(payload)
            repaired["schema_error"] = str(exc)
            try:
                return once(repaired)
            except (SchemaRejected, TimeoutError, RuntimeError) as again:
                print(
                    f"quality skip: {prompt_id} {type(again).__name__}",
                    file=sys.stderr,
                    flush=True,
                )
                return None

    if ledger.index:
        turn = call(COMPACTION, {"spans": [_index_row(span) for span in ledger.index]})
        if turn is not None:
            ledger.index = apply_omissions(ledger.index, _omit_ids(turn.output))

    claims: list[Claim] = []
    gaps: list[Gap] = []
    omissions: list[Omission] = []
    disagreements = []
    if not budget.hit:
        _cross(ledger, call, disagreements)
    if not budget.hit:
        _extract(ledger, call, claims, gaps)
    if not budget.hit:
        _coverage(ledger, call, claims, gaps, omissions)
    findings = []
    dimensions = {}
    if not budget.hit:
        from graph.lenses import run_lenses

        lensed = run_lenses(_BudgetModel(model, budget, registry), registry, claims)
        findings = lensed["findings"]
        dimensions = lensed["dimensions"]
        _apply_decisions(registry, claims, findings)
    sentences = []
    synth_omissions = []
    if not budget.hit and findings:
        sentences, synth_omissions = _synthesize(call, findings)
    elif not budget.hit:
        turn = call(SYNTHESIS, synthesis_payload([]))
        if turn is not None:
            sentences = sentences_from(turn.output)
            dissent = call(DISSENT, dissent_payload([], sentences))
            if dissent is not None and dropped_ids(dissent.output):
                synth_omissions = synthesis_omissions(dropped_ids(dissent.output))
    actions = []
    if not budget.hit:
        actions = _actions(ledger, registry, findings, claims)
    chart = None
    if not budget.hit:
        chart = _chart(ledger, call)
    result = gate(
        meeting_id=ledger.meeting_id,
        duration_ms=ledger.duration_ms,
        spans=ledger.spans,
        claims=claims,
        findings=findings,
        sentences=sentences,
        synthesis_omissions=synth_omissions,
        actions=actions,
        disagreements=disagreements,
        omissions=omissions,
        gaps=gaps,
        dimensions=dimensions,
        ceiling_hit=budget.hit,
        prompt_release=registry.release,
        versions=registry.versions(),
        idempotency_key=key,
        chart=chart,
    )
    # Motivation vs Logic
    # Motivation: Review urgency is a closed sort of ids the gate already queued.
    # Logic: Score order replaces review_queue only after a full answer. Any miss keeps the gate order, status, and brief.
    result = apply_order(result, registry, client=review_client)
    store.put(key, result)
    return result


class _BudgetModel:
    """Counts lens calls against the activity ceiling without choosing a model from the meeting."""

    def __init__(self, model, budget: Budget, registry):
        self.model = model
        self.budget = budget
        self.registry = registry

    def complete(self, *, prompt_id: str, role: str | None, payload: dict):
        from bedrock.turn import ModelTurn

        if not self.budget.allow():
            self.budget.hit = True
            return ModelTurn(output={"result": "none_in_transcript"})
        print(f"quality call: {prompt_id}", file=sys.stderr, flush=True)
        try:
            return self.model.complete(prompt_id=prompt_id, role=role, payload=payload)
        except (SchemaRejected, TimeoutError) as exc:
            if not self.budget.allow():
                self.budget.hit = True
                return ModelTurn(output={"result": "none_in_transcript"})
            repaired = dict(payload)
            repaired["schema_error"] = str(exc)
            try:
                return self.model.complete(prompt_id=prompt_id, role=role, payload=repaired)
            except (SchemaRejected, TimeoutError):
                return ModelTurn(output={"result": "none_in_transcript"})


def _index_row(span) -> dict:
    return {
        "id": span.id,
        "kind": span.kind,
        "start_ms": span.start_ms,
        "end_ms": span.end_ms,
        "overlap": span.overlap,
    }


def _cross(ledger: Ledger, call, disagreements: list) -> None:
    pairs = [
        (span, observation)
        for span in ledger.spans
        if span.kind == "speech"
        for observation in overlapping(span, ledger.observations)
    ]

    def one(pair) -> object:
        span, observation = pair
        turn = call(
            CROSSMODAL,
            {
                "sonic_span_id": span.id,
                "observation_id": observation.id,
                "quote": span.text,
                "observation": observation.statement,
            },
        )
        if turn is None:
            return None
        return record_cross(span, observation, turn.output)

    for found in map_ordered(one, pairs):
        if found is not None:
            disagreements.append(found)


def _extract(ledger: Ledger, call, claims: list, gaps: list) -> None:
    speech = [span for span in ledger.spans if span.kind == "speech"]
    for offset in range(0, len(speech), 20):
        window = speech[offset : offset + 20]
        turn = call(
            CLAIM,
            {
                "spans": [
                    {
                        "id": span.id,
                        "text": span.text,
                        "start_ms": span.start_ms,
                        "end_ms": span.end_ms,
                        "speaker_hypothesis_id": span.speaker_hypothesis_id,
                    }
                    for span in window
                ]
            },
        )
        if turn is None:
            return
        drafted = [
            _claim_from(raw, ledger.meeting_id, f"claim-{offset}-{index}")
            for index, raw in enumerate(turn.output.get("claims") or [])
        ]
        claims.extend(_finish_claims(ledger, call, drafted))
        for raw in turn.output.get("gaps") or []:
            gaps.append(Gap(span_ids=list(raw.get("span_ids") or []), reason=raw.get("reason") or ""))


def _contest(ledger: Ledger, call, claim: Claim) -> None:
    by_id = {span.id: span for span in ledger.spans}
    # Bugs vs Fixes
    # Bug: The search payload had the paraphrase and the quote, and no span id.
    # The model could not name a span to open, so searched_ids never matched opened_ids.
    # Fix: Send the speech index (id and time, not the text). The tool returns the text.
    payload = {
        "paraphrase": claim.paraphrase,
        "quotes": [claim.quote],
        "spans": [
            {"id": span.id, "kind": span.kind, "start_ms": span.start_ms, "end_ms": span.end_ms}
            for span in ledger.spans
            if span.kind == "speech"
        ],
    }
    opened: list[str] = []
    turn = None
    for _ in range(4):
        turn = call(COUNTEREVIDENCE, payload)
        if turn is None:
            return
        if not turn.tool_calls:
            break
        results = []
        for tool_call in turn.tool_calls:
            if tool_call.name != "open_span":
                from errors import SchemaRejected

                raise SchemaRejected("counterevidence tools are dispatched by name open_span")
            span_id = tool_call.arguments.get("span_id")
            if not isinstance(span_id, str) or not span_id:
                continue
            span = by_id.get(span_id)
            if span is None:
                continue
            if span.meeting_id != ledger.meeting_id:
                from errors import SchemaRejected

                raise SchemaRejected("evidence span meeting_id does not match this meeting")
            opened.append(span_id)
            results.append({"span_id": span_id, "text": span.text})
        if not results:
            return
        # Bugs vs Fixes
        # Bug: The next round still advertised open_span, so the model called it
        # again and the loop ended on an empty schema object.
        # Fix: After a real open, the next round is a schema fill. _fill is not a model field.
        payload = {
            "_fill": True,
            "tool_results": results,
            "opened_ids": list(dict.fromkeys(opened)),
        }
    if turn is None:
        return
    claim.opened_ids = opened
    claim.searched_ids = list(turn.output.get("searched_ids") or [])
    finding = turn.output.get("finding") if isinstance(turn.output.get("finding"), dict) else {}
    if finding.get("kind") == "contradicts":
        claim.contradicting_quote = finding.get("quote") or None
    else:
        claim.contradicting_quote = turn.output.get("contradicting_quote") or None
    # Bugs vs Fixes
    # Bug: Entailment's contract reads cited_span_texts. The worker sent quotes,
    # so both models labeled neutral and every claim stayed unsupported.
    # Fix: Send the one span text that contains the quote, under that field name.
    from graph.quote import resolve_quote

    resolution = resolve_quote(
        claim.quote, ledger.spans, meeting_id=ledger.meeting_id, duration_ms=ledger.duration_ms
    )
    cited: list[str] = []
    if resolution.span_id:
        cited = [next(span.text for span in ledger.spans if span.id == resolution.span_id)]
    pack = {"paraphrase": claim.paraphrase, "cited_span_texts": cited}

    def vote(prompt_id: str):
        return call(prompt_id, pack)

    sol, luna = map_ordered(vote, (ENTAILMENT_SOL, ENTAILMENT_LUNA))
    if sol is not None:
        claim.sol_label = sol.output.get("label")
    if luna is not None:
        claim.luna_label = luna.output.get("label")


def _coverage(ledger, call, claims, gaps, omissions) -> None:
    def uncovered() -> list[str]:
        covered = {claim.span_id for claim in claims if claim.span_id}
        covered.update(item.span_id for item in omissions)
        for gap in gaps:
            covered.update(gap.span_ids)
        return [span.id for span in ledger.spans if span.kind == "speech" and span.id not in covered]

    pending = uncovered()
    while pending:
        turn = call(COVERAGE, {"span_ids": pending})
        if turn is None:
            return
        before = set(pending)
        listed = turn.output.get("uncovered_span_ids")
        if listed is None:
            for raw in turn.output.get("omissions") or []:
                omissions.append(Omission(span_id=raw["span_id"], reason=raw.get("reason") or ""))
            drafted = [
                _claim_from(raw, ledger.meeting_id, f"coverage-{index}")
                for index, raw in enumerate(turn.output.get("claims") or [])
            ]
            claims.extend(_finish_claims(ledger, call, drafted))
        else:
            supplement = call(SUPPLEMENT, {"span_ids": listed}) if listed else None
            if supplement is not None:
                _apply_supplement(ledger, call, claims, omissions, supplement.output)
        pending = uncovered()
        if set(pending) == before:
            return


def _synthesize(call, findings):
    turn = call(SYNTHESIS, synthesis_payload(findings))
    if turn is None:
        return [], []
    sentences = sentences_from(turn.output)
    dissent = call(DISSENT, dissent_payload(findings, sentences))
    if dissent is None:
        return sentences, []
    first = dropped_ids(dissent.output)
    if not first:
        return sentences, []
    again = call(SYNTHESIS, synthesis_payload(findings, first))
    if again is None:
        return sentences, []
    sentences = sentences_from(again.output)
    second = call(DISSENT, dissent_payload(findings, sentences))
    if second is None:
        return sentences, []
    return sentences, synthesis_omissions(dropped_ids(second.output))


def _omit_ids(output: dict) -> list[str]:
    omissions = output.get("omissions") or []
    found = []
    for item in omissions:
        if isinstance(item, dict) and item.get("span_id"):
            found.append(item["span_id"])
        elif isinstance(item, str):
            found.append(item)
    if found:
        return found
    return list(output.get("omit_ids") or [])


def _claim_from(raw: dict, meeting_id: str, fallback_id: str) -> Claim:
    proposition = raw["proposition"]
    return Claim(
        id=raw.get("id") or fallback_id,
        meeting_id=meeting_id,
        kind=raw["kind"],
        proposition=proposition,
        paraphrase=raw.get("paraphrase") or proposition,
        quote=raw["quote"],
        decision_status=raw.get("decision_status"),
    )


def _apply_supplement(ledger, call, claims, omissions, output: dict) -> None:
    drafted: list[Claim] = []
    for index, item in enumerate(output.get("items") or []):
        if item.get("outcome") == "omission":
            omissions.append(Omission(span_id=item["span_id"], reason=item.get("reason") or ""))
            continue
        if item.get("outcome") != "claim":
            continue
        drafted.append(_claim_from(item, ledger.meeting_id, f"supplement-{index}"))
    claims.extend(_finish_claims(ledger, call, drafted))


def _finish_claims(ledger: Ledger, call, drafted: list[Claim]) -> list[Claim]:
    def finish(claim: Claim) -> Claim:
        _contest(ledger, call, claim)
        return finalize_claim(claim, ledger.spans, duration_ms=ledger.duration_ms)

    return map_ordered(finish, drafted)


def _apply_decisions(registry, claims, findings) -> None:
    from graph.lenses import apply_decision_status

    schema: dict = {}
    try:
        schema = registry.schema(lens_id("decision"))
    except RegistryMissing:
        schema = {}
    apply_decision_status(claims, findings, schema)


def _actions(ledger, registry, findings, claims):
    by_id = {claim.id: claim for claim in claims}
    built = []
    for finding in findings:
        if finding.dimension != "commitment":
            continue
        for draft in finding.action_drafts:
            quote = ""
            claim_ids = draft.get("claim_ids") or []
            if claim_ids and claim_ids[0] in by_id:
                quote = by_id[claim_ids[0]].quote
            built.append(
                ground_action(draft, registry, ledger.spans, quote=quote, anchor_date=ledger.anchor_date)
            )
    return retain_durable(ledger.previous_actions, merge_actions(built))


def _chart(ledger, call):
    turn = call(
        CHART,
        {
            "cells": sorted(ledger.cells),
            "span_ids": [span.id for span in ledger.spans if span.kind == "speech"],
        },
    )
    if turn is None:
        return None
    output = turn.output or {}
    if output.get("charts") == [] or "aggregation" not in output:
        return None
    table = compute(output, cells=ledger.cells, spans={span.id: span for span in ledger.spans})
    return render(table)
