# Motivation vs Logic
# Motivation: The extractor does not verdict its own sentence, and a ceiling withholds the brief without shrinking output tokens.
# Logic: Compaction, claims, counterevidence, dual entailment, coverage, ten lenses, synthesis, dissent, chart, the publish gate, then a fail-open queue sort.

import sys
import threading
from dataclasses import dataclass, field
from typing import Callable

from errors import RegistryMissing, SchemaRejected
from loop.tools import complete_with_open_span, complete_with_tools
from graph.actions import action_schema, ground_action, merge_actions, retain_durable
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
    DIGEST,
    DIGEST_REVIEW,
    ANSWER_CHECK,
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
    # What the picture showed (slides, shared screens, diagrams) and the names it displayed. See identity.resolve.
    screens: list = field(default_factory=list)
    sightings: list = field(default_factory=list)
    visual_identities: list = field(default_factory=list)
    visual_merges: list = field(default_factory=list)
    # Voice id -> name, from the person (locked) and from the picture. Given to the digest writer.
    known_names: dict = field(default_factory=dict)
    turns: list = field(default_factory=list)
    anchor_date: str | None = None
    previous_actions: list = field(default_factory=list)
    # Reference material the person supplied (context.library.ContextLibrary), or None. It is never evidence.
    context: object | None = None


class Budget:
    def __init__(self, ceiling: int | None = None, should_stop=None):
        self.ceiling = ceiling
        self.should_stop = should_stop
        self.used = 0
        self.hit = False
        self._lock = threading.Lock()

    def allow(self) -> bool:
        # A cancelled meeting stops spending: every model call goes through here.
        if self.should_stop is not None and self.should_stop():
            self.hit = True
            return False
        with self._lock:
            if self.ceiling is not None and self.used >= self.ceiling:
                self.hit = True
                return False
            self.used += 1
            return True


def run(
    ledger: Ledger,
    model,
    registry,
    store,
    key: str,
    *,
    iteration_ceiling: int | None = None,
    review_client=None,
    stage_callback: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
):
    _require_speech(ledger)
    cached = store.get(key)
    if cached is not None:
        return cached
    budget = Budget(iteration_ceiling, should_stop)

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
        if stage_callback:
            stage_callback("Compacting transcript spans")
        turn = call(COMPACTION, {"spans": [_index_row(span) for span in ledger.index]})
        if turn is not None:
            ledger.index = apply_omissions(ledger.index, _omit_ids(turn.output))

    claims: list[Claim] = []
    # A segment the transcription service rejected is a stated gap, not silence.
    gaps: list[Gap] = [
        Gap(span_ids=[span.id], reason="This part of the recording could not be transcribed.")
        for span in ledger.spans
        if span.kind == "untranscribed"
    ]
    omissions: list[Omission] = []
    disagreements = []
    if not budget.hit:
        if stage_callback:
            stage_callback("Checking audio against visual evidence")
        _cross(ledger, call, disagreements)
    if not budget.hit:
        if stage_callback:
            stage_callback("Extracting claims from the transcript")
        _extract(ledger, call, claims, gaps)
    if not budget.hit:
        if stage_callback:
            stage_callback("Checking transcript coverage")
        _coverage(ledger, call, claims, gaps, omissions)
    findings = []
    dimensions = {}
    if not budget.hit:
        if stage_callback:
            stage_callback("Analyzing all ten evidence lenses")
        from graph.lenses import run_lenses

        lensed = run_lenses(_BudgetModel(
                model,
                budget,
                registry,
                spans=ledger.spans,
                meeting_id=ledger.meeting_id,
                aliases={claim.id: claim.span_id for claim in claims if claim.span_id},
            ), registry, claims)
        findings = lensed["findings"]
        dimensions = lensed["dimensions"]
        # Visual lenses cannot say "nothing shown" about a video nobody looked at.
        if any(VISUAL_SKIPPED in str(getattr(note, "statement", "")) for note in ledger.notes):
            for name in ("cross_modal", "documentary"):
                if dimensions.get(name) == "none_in_transcript":
                    dimensions[name] = "not_evaluated"
        _apply_decisions(registry, claims, findings)
    sentences = []
    synth_omissions = []
    if not budget.hit and findings:
        if stage_callback:
            stage_callback("Building the evidence-backed brief")
        sentences, synth_omissions = _synthesize(call, findings)
    elif not budget.hit:
        if stage_callback:
            stage_callback("Summarizing the available evidence")
        turn = call(SYNTHESIS, synthesis_payload([]))
        if turn is not None:
            sentences = sentences_from(turn.output)
            dissent = call(DISSENT, dissent_payload([], sentences))
            if dissent is not None and dropped_ids(dissent.output):
                synth_omissions = synthesis_omissions(dropped_ids(dissent.output))
    actions = []
    if not budget.hit:
        if stage_callback:
            stage_callback("Extracting and grounding follow-up actions")
        actions = _actions(ledger, registry, findings, claims)
    digest = None
    if not budget.hit:
        if stage_callback:
            stage_callback("Writing the walkaway: summary, decisions, actions and topics")
        digest = _digest(ledger, call, claims, actions)
    chart = None
    if not budget.hit:
        if stage_callback:
            stage_callback("Building charts and checking publish readiness")
        try:
            chart = _chart(ledger, call)
        except Exception as exc:  # the chart is an extra; a rejected one must not fail the meeting
            print(f"chart skipped: {type(exc).__name__}", file=sys.stderr, flush=True)
            chart = None
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
        digest=digest,
    )
    # Motivation vs Logic
    # Motivation: Review urgency is a closed sort of ids the gate already queued.
    # Logic: Score order replaces review_queue only after a full answer. Any miss keeps the gate order, status, and brief.
    result = apply_order(result, registry, client=review_client)
    store.put(key, result)
    return result


# Motivation vs Logic
# Motivation: "none_in_transcript" is a statement about the recording. A lens that
# timed out, was rejected twice, or ran past the budget says nothing about it.
# Logic: Those outcomes return "not_evaluated". The gate keeps the meeting in
# review while any dimension is not evaluated, and the portal reads
# "Not analysed" instead of "Not mentioned in the video".
class _BudgetModel:
    """Counts lens calls against the activity ceiling without choosing a model from the meeting."""

    def __init__(self, model, budget: Budget, registry, spans=None, meeting_id: str | None = None, aliases=None):
        self.model = model
        self.budget = budget
        self.registry = registry
        self.spans = spans or []
        self.meeting_id = meeting_id
        self.aliases = aliases or {}

    def complete(self, *, prompt_id: str, role: str | None, payload: dict):
        # A lens that opens a span first answers with a tool call; run it and ask again.
        from bedrock.turn import ModelTurn
        from errors import InputTooLarge, NotInvocable

        try:
            return complete_with_open_span(
                lambda body: self._once(prompt_id, role, body), self.spans, self.meeting_id, payload, self.aliases
            )
        except NotInvocable:
            raise  # model access is a configuration failure; do not hide it as "not evaluated"
        except (SchemaRejected, InputTooLarge, RuntimeError, TimeoutError) as exc:
            print(f"lens skipped: {prompt_id} {type(exc).__name__}", file=sys.stderr, flush=True)
            return ModelTurn(output={"result": "not_evaluated"})

    def _once(self, prompt_id: str, role: str | None, payload: dict):
        from bedrock.turn import ModelTurn

        if not self.budget.allow():
            self.budget.hit = True
            return ModelTurn(output={"result": "not_evaluated"})
        print(f"quality call: {prompt_id}", file=sys.stderr, flush=True)
        try:
            return self.model.complete(prompt_id=prompt_id, role=role, payload=payload)
        except (SchemaRejected, TimeoutError) as exc:
            if not self.budget.allow():
                self.budget.hit = True
                return ModelTurn(output={"result": "not_evaluated"})
            repaired = dict(payload)
            repaired["schema_error"] = str(exc)
            try:
                return self.model.complete(prompt_id=prompt_id, role=role, payload=repaired)
            except (SchemaRejected, TimeoutError):
                return ModelTurn(output={"result": "not_evaluated"})


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
    failures = 0
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
            # Bugs vs Fixes
            # Bug: One failed window ended extraction, so every later window of the
            # meeting produced no claims and its speech stayed silent in the brief.
            # Fix: Skip that window. The coverage stage finds its spans and closes
            # them. Stop only after three windows in a row fail, which means the
            # model is unavailable rather than one window being bad.
            failures += 1
            if failures >= 3:
                return
            continue
        failures = 0
        window_ids = {span.id for span in window}
        drafted = [
            _claim_from(raw, ledger.meeting_id, f"claim-{offset}-{index}", allowed_span_ids=window_ids)
            for index, raw in enumerate(turn.output.get("claims") or [])
        ]
        claims.extend(_finish_claims(ledger, call, drafted))
        for raw in turn.output.get("gaps") or []:
            cited_ids = [span_id for span_id in raw.get("span_ids") or [] if span_id in window_ids]
            if cited_ids:
                gaps.append(Gap(span_ids=cited_ids, reason=raw.get("reason") or ""))


# Motivation vs Logic
# Motivation: A claim became "contradicted" whenever the counter-search returned any quote, with
# no check. Live runs marked supported claims contradicted by quotes that agreed with them
# ("I've tacked on this extra column" "contradicting" "an extra column has been added").
# Logic: A contradiction stands only if (1) its quote exists verbatim in this meeting and
# (2) that quote does not itself entail the claim. A quote that fails either test is dropped, so the
# claim is decided by the remaining checks instead of being condemned by an unverified one.
def _verified_contradiction(ledger: Ledger, call, claim: Claim) -> str | None:
    quote = claim.contradicting_quote
    if not quote:
        return None
    from graph.quote import resolve_quote

    resolution = resolve_quote(quote, ledger.spans, meeting_id=ledger.meeting_id, duration_ms=ledger.duration_ms)
    if resolution.status != "resolved" or not resolution.span_id:
        return None
    # Bugs vs Fixes
    # Bug: Any counter-quote that did not "entail" the claim counted as a contradiction, including
    # an unrelated ("neutral") one. On the panel recording 15 of 16 "contradicted" claims had both
    # entailment checks saying the claim was supported ("It was technically feasible to connect
    # networks together" was marked contradicted by its own supporting sentence).
    # Fix: A contradiction needs the verification to say the quote contradicts the claim.
    turn = call(ENTAILMENT_SOL, {"paraphrase": claim.paraphrase, "cited_span_texts": [quote]})
    if turn is not None and turn.output.get("label") == "contradicts":
        return quote
    return None


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
                continue  # an unknown tool is ignored, not a reason to fail the meeting
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
    claim.contradicting_quote = _verified_contradiction(ledger, call, claim)
    # Bugs vs Fixes
    # Bug: Entailment's contract reads cited_span_texts. The worker sent quotes,
    # so both models labeled neutral and every claim stayed unsupported.
    # Fix: Send the one span text that contains the quote, under that field name.
    from graph.quote import resolve_quote

    resolution = resolve_quote(
        claim.quote,
        ledger.spans,
        meeting_id=ledger.meeting_id,
        duration_ms=ledger.duration_ms,
        span_ids=set(claim.source_span_ids) if claim.source_span_ids is not None else None,
    )
    cited: list[str] = []
    if resolution.span_id:
        cited = [next(span.text for span in ledger.spans if span.id == resolution.span_id)]
    if not cited:
        # No span contains the quote, so there is nothing for entailment to read.
        # The claim stays unresolved without spending two model calls on empty text.
        return
    pack = {"paraphrase": claim.paraphrase, "cited_span_texts": cited}

    def vote(prompt_id: str):
        return call(prompt_id, pack)

    sol, luna = map_ordered(vote, (ENTAILMENT_SOL, ENTAILMENT_LUNA))
    if sol is not None:
        claim.sol_label = sol.output.get("label")
    if luna is not None:
        claim.luna_label = luna.output.get("label")


# Motivation vs Logic
# Motivation: A speech span that has no claim, omission, or gap is silent in the
# brief. The audit that finds those spans is a set difference the worker already
# holds exactly; the stage that closes them needs the span text.
# Logic: The uncovered set is computed here and is authoritative. The coverage
# prompt receives the three id sets its contract names and acts as a cross-check
# whose disagreement is logged. The supplement prompt receives `uncovered_spans`
# (id, times, text) in bounded batches, so each span ends as a claim or an
# omission. A round that closes nothing stops the loop.
# Bugs vs Fixes
# Bug: The coverage call sent `span_ids` and the supplement call sent
# `span_ids`, but the contracts name `speech_span_ids`/`claim_span_ids`/
# `omission_span_ids` and `uncovered_spans`. The model never saw what it was
# asked to compare, returned no uncovered spans, and every span stayed open, so
# a meeting could not become ready.
# Fix: Send contract-shaped payloads, batch the supplement, and number claim ids
# per batch so they cannot collide.
COVERAGE_BATCH = 20
COVERAGE_ROUNDS = 3


def _coverage(ledger, call, claims, gaps, omissions) -> None:
    speech = [span for span in ledger.spans if span.kind == "speech"]
    speech_ids = [span.id for span in speech]

    def sets() -> tuple[set[str], set[str]]:
        # Same definition as the publish gate: the span a claim's quote resolved to. Spans a claim
        # merely listed as candidates are not covered, or the gate and this stage disagree.
        claimed = {claim.span_id for claim in claims if claim.span_id}
        for gap in gaps:
            claimed.update(gap.span_ids)
        return claimed, {item.span_id for item in omissions}

    def uncovered() -> list[str]:
        claimed, omitted = sets()
        return [span_id for span_id in speech_ids if span_id not in claimed and span_id not in omitted]

    pending = uncovered()
    batch_number = 0
    for _ in range(COVERAGE_ROUNDS):
        if not pending:
            return
        claimed, omitted = sets()
        turn = call(
            COVERAGE,
            {
                "speech_span_ids": speech_ids,
                "claim_span_ids": sorted(claimed),
                "omission_span_ids": sorted(omitted),
            },
        )
        listed = turn.output.get("uncovered_span_ids") if turn is not None else None
        if listed is not None and set(listed) != set(pending):
            print(
                f"coverage cross-check differs: auditor {len(set(listed))}, derived {len(pending)}",
                file=sys.stderr,
                flush=True,
            )
        before = set(pending)
        by_id = {span.id: span for span in speech}
        for start in range(0, len(pending), COVERAGE_BATCH):
            batch = [by_id[span_id] for span_id in pending[start : start + COVERAGE_BATCH]]
            supplement = complete_with_open_span(
                lambda body: call(SUPPLEMENT, body),
                ledger.spans,
                ledger.meeting_id,
                {
                    "uncovered_spans": [
                        {"span_id": span.id, "start_ms": span.start_ms, "end_ms": span.end_ms, "text": span.text}
                        for span in batch
                    ]
                },
            )
            batch_number += 1
            if supplement is None:
                print(f"coverage supplement batch {batch_number}: no answer for {len(batch)} spans", file=sys.stderr, flush=True)
                return
            items = supplement.output.get("items") or []
            answered = {item.get("span_id") for item in items if isinstance(item, dict)}
            print(
                f"coverage supplement batch {batch_number}: asked {len(batch)}, answered {len(answered & {s.id for s in batch})}, "
                f"claims {sum(1 for i in items if isinstance(i, dict) and i.get('outcome') == 'claim')}, "
                f"omissions {sum(1 for i in items if isinstance(i, dict) and i.get('outcome') == 'omission')}",
                file=sys.stderr,
                flush=True,
            )
            _apply_supplement(ledger, call, claims, omissions, supplement.output, prefix=f"supplement-{batch_number}")
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


def _claim_from(
    raw: dict,
    meeting_id: str,
    fallback_id: str,
    *,
    allowed_span_ids: set[str] | None = None,
) -> Claim:
    proposition = raw["proposition"]
    raw_span_ids = raw.get("span_ids") or []
    source_span_ids = [span_id for span_id in raw_span_ids if isinstance(span_id, str)]
    if allowed_span_ids is not None:
        source_span_ids = [span_id for span_id in source_span_ids if span_id in allowed_span_ids]
    return Claim(
        id=raw.get("id") or fallback_id,
        meeting_id=meeting_id,
        kind=raw["kind"],
        proposition=proposition,
        paraphrase=raw.get("paraphrase") or proposition,
        quote=raw["quote"],
        decision_status=raw.get("decision_status"),
        source_span_ids=list(dict.fromkeys(source_span_ids)),
    )


def _apply_supplement(ledger, call, claims, omissions, output: dict, *, prefix: str = "supplement") -> None:
    drafted: list[Claim] = []
    meeting_span_ids = {span.id for span in ledger.spans if span.kind == "speech"}
    for index, item in enumerate(output.get("items") or []):
        span_id = item.get("span_id")
        if not isinstance(span_id, str) or span_id not in meeting_span_ids:
            continue
        if item.get("outcome") == "omission":
            omissions.append(Omission(span_id=span_id, reason=item.get("reason") or ""))
            continue
        if item.get("outcome") != "claim":
            continue
        raw_claim = {**item, "span_ids": [span_id]}
        drafted.append(
            _claim_from(
                raw_claim,
                ledger.meeting_id,
                f"{prefix}-{index}",
                allowed_span_ids={span_id},
            )
        )
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
    # A supported commitment is already verified even when the commitment
    # lens misses its action draft. Keep a conservative proposed action so a
    # person can accept it; do not infer an owner or deadline here.
    represented = {claim_id for action in built for claim_id in action.claim_ids}
    fallback_groups = {}
    for claim in claims:
        if claim.status != "supported" or claim.kind != "commitment" or claim.id in represented:
            continue
        key = " ".join(claim.paraphrase.casefold().split()) or claim.id
        fallback_groups.setdefault(key, []).append(claim)
    for siblings in fallback_groups.values():
        claim = siblings[0]
        draft = {
            "statement": claim.paraphrase,
            "owner_span_id": None,
            "agreement_span_id": None,
            "due_kind": "none",
            "due_surface": None,
            "due_span_id": None,
            "claim_ids": [item.id for item in siblings],
            "acceptance": "proposed",
        }
        # Motivation vs Logic
        # Motivation: The fallback row is a convenience. A contract mismatch on it
        # must not discard a completed analysis; the claim stays in the review queue.
        # Logic: origin is sent only when the loaded action schema declares it; the
        # shipped commitment schema does not. A rejected draft is skipped and
        # reported on stderr.
        if "origin" in action_schema(registry).get("properties", {}):
            draft["origin"] = "model"
        try:
            built.append(ground_action(draft, registry, ledger.spans, quote=claim.quote, anchor_date=ledger.anchor_date))
        except SchemaRejected as error:
            print(f"fallback action skipped for {claim.id}: {error}", file=sys.stderr)
    return retain_durable(ledger.previous_actions, merge_actions(built))


MIN_SPEECH_CHECK_MS = 30_000
VISUAL_SKIPPED = "Visual analysis was skipped"


def _require_speech(ledger) -> None:
    """A recording with nothing transcribed must fail, not publish as ready with every dimension reading
    "not mentioned": silence in the transcript is not evidence that nothing was said. A recording whose
    segments were all rejected by the provider is a different case (named gaps) and is left to the gate."""
    if getattr(ledger, "duration_ms", 0) <= MIN_SPEECH_CHECK_MS:
        return
    spans = getattr(ledger, "spans", None) or []
    if any(span.kind == "untranscribed" or (span.kind == "speech" and (span.text or span.raw_text or "").strip()) for span in spans):
        return
    from errors import NoSpeech

    raise NoSpeech("no speech was transcribed")


def _digest(ledger, call, claims, actions):
    """Walkaway pass. Never fails the analysis: any error leaves the meeting without a digest."""
    from graph.digest import claim_rows, ground_digest, screen_rows, transcript_lines

    def speaker_of(span) -> str:
        return span.speaker_hypothesis_id or "unknown"

    try:
        lines = transcript_lines(ledger.spans, speaker_of)
        if not lines:
            return None
        payload = {
            "transcript": lines,
            "claims": claim_rows(claims),
            "actions": [
                {"id": f"a{index}", "statement": action.statement, "due_said": action.due_surface}
                for index, action in enumerate(actions)
            ],
        }
        on_screen = screen_rows(getattr(ledger, "screens", None) or [])
        if on_screen:
            payload["on_screen"] = on_screen
        known_names = {label: name for label, name in (getattr(ledger, "known_names", None) or {}).items() if label in {row.get("speaker") for row in lines}}
        if known_names:
            payload["known_names"] = known_names
        # Reference material the person supplied: an index in the prompt, the documents on demand.
        library = getattr(ledger, "context", None)
        handlers = {}
        if library is not None and library.payload():
            from context.library import tool_handler

            payload["context"] = library.payload()
            handlers = {"read_context": tool_handler(library)}
        from errors import InputTooLarge

        try:
            turn = complete_with_tools(lambda body: call(DIGEST, body), handlers, payload)
        except InputTooLarge:
            # Reference material pushed the prompt over the budget: write the walkaway without it
            # rather than lose the walkaway.
            if "context" not in payload:
                raise
            print("digest: context left out (over the input budget)", file=sys.stderr, flush=True)
            payload = {key: value for key, value in payload.items() if key != "context"}
            handlers = {}
            turn = complete_with_tools(lambda body: call(DIGEST, body), handlers, payload)
        if turn is None:
            print("digest skipped: no answer", file=sys.stderr, flush=True)
            return None
        speakers = {row["speaker"] for row in lines if row.get("speaker") not in (None, "unknown")}
        digest = ground_digest(turn.output, ledger.spans, claims, actions, speakers, known_names)
        digest = _reviewed(call, payload, turn.output, digest, lambda raw: ground_digest(raw, ledger.spans, claims, actions, speakers, known_names), handlers)
        digest = _verify_questions(ledger, call, digest)
        from jev.rank import rank_digest

        return rank_digest(digest)
    except Exception as exc:  # the walkaway is optional; the evidence graph is not
        print(f"digest skipped: {type(exc).__name__}", file=sys.stderr, flush=True)
        return None


# Motivation vs Logic
# Motivation: A single writing pass cannot see its own omissions or misreadings; blind evaluation found
# the same classes of defect on every recording (reversed readings, a missing dispute or next step,
# generous "answered" flags).
# Logic: A second pass reads the transcript and the draft and returns a corrected walkaway. It is
# grounded by the same code as the draft, so it cannot add what the transcript does not support. It
# replaces the draft only when it is a sound walkaway of at least 70% of the draft's size; a failed,
# empty or much thinner review keeps the draft.
REVIEW_KEEP = 0.7
_SECTIONS = ("chapters", "decisions", "actions", "open_questions", "disagreements", "perspectives", "key_figures", "risks", "concepts", "speakers", "summary")


def _size(digest) -> int:
    return sum(len(digest.get(name) or []) for name in _SECTIONS) if isinstance(digest, dict) else 0


def _reviewed(call, payload, draft_output, draft, ground, handlers=None):
    if not isinstance(draft, dict) or not isinstance(draft_output, dict):
        return draft
    try:
        body = {**payload, "draft": draft_output}
        turn = complete_with_tools(lambda request: call(DIGEST_REVIEW, request), handlers or {}, body)
        if turn is None:
            print("digest review skipped: no answer", file=sys.stderr, flush=True)
            return draft
        review = ground(turn.output)
    except Exception as exc:  # the draft is already a valid walkaway
        print(f"digest review skipped: {type(exc).__name__}", file=sys.stderr, flush=True)
        return draft
    if not isinstance(review, dict) or _size(review) < REVIEW_KEEP * _size(draft) or not review.get("summary"):
        print("digest review kept the draft: the review was thinner", file=sys.stderr, flush=True)
        return draft
    return review


# Motivation vs Logic
# Motivation: In every evaluated recording the walkaway called a question unanswered although a later
# line answered it (a reply from another voice, minutes later, or a partial answer).
# Logic: Every question the digest lists is checked by a narrow pass that sees only the question and the
# next ANSWER_WINDOW_MS of speech, and may reply only by naming one of those lines; code checks that the
# line was one of those shown and comes after the question. The check can promote an unanswered
# question, or demote an answered one it does not confirm (keeping the cited reply as a partial one).
# If the check fails, returns nothing usable, or cites a line it was not shown, the writing pass's own
# answer stands: verification never removes a walkaway or a question.
ANSWER_WINDOW_MS = 8 * 60_000
ANSWER_LINES = 160


def _verify_questions(ledger, call, digest):
    if not isinstance(digest, dict):
        return digest
    speech = sorted(
        (span for span in ledger.spans if span.kind == "speech" and (span.text or "").strip() and span.start_ms is not None),
        key=lambda span: span.start_ms,
    )
    by_id = {span.id: span for span in speech}
    # Every question is checked, not only the unanswered ones: blind evaluation found the writing pass
    # marking questions answered on a partial or off-subject reply. A question the check does not
    # confirm is demoted to unanswered, keeping the reply it cited as a partial one.
    pending = list(digest.get("open_questions") or [])

    def check(row):
        asked = by_id.get(row.get("asked_span_id"))
        if asked is None:
            return
        after = [span for span in speech if span.start_ms > asked.start_ms and span.start_ms - asked.start_ms <= ANSWER_WINDOW_MS][:ANSWER_LINES]
        if not after:
            return
        turn = call(
            ANSWER_CHECK,
            {
                "question": row["question"],
                "lines_after": [
                    {"id": span.id, "t": f"{int(span.start_ms // 60000)}:{int(span.start_ms // 1000) % 60:02d}",
                     "speaker": span.speaker_hypothesis_id or "unknown", "text": span.text.strip()}
                    for span in after
                ],
            },
        )
        output = getattr(turn, "output", None) if turn is not None else None
        if not isinstance(output, dict):
            return
        if row.get("answered") and output.get("answered") is False:
            row["answered"] = False
            return
        if row.get("answered"):
            return  # confirmed: keep the writing pass's answer as it is
        shown = {span.id for span in after}
        answer_id = output.get("answer_span_id")
        answer = by_id.get(answer_id) if isinstance(answer_id, str) and answer_id in shown else None
        if answer is None or answer.start_ms <= asked.start_ms:
            return  # a reply may only be one of the lines the check was shown
        if output.get("answered") is not True:
            if asked.speaker_hypothesis_id and answer.speaker_hypothesis_id == asked.speaker_hypothesis_id:
                return  # the asker carrying on is the question continuing, not a partial reply
            # A reply that only partly addresses the question is kept, marked as partial.
            if not row.get("answer") and (output.get("answer") or "").strip():
                row["answer"] = output["answer"].strip()
                row["answer_span_id"] = answer.id
                row["answer_ms"] = answer.start_ms
            return
        row["answered"] = True
        row["answer"] = (output.get("answer") or answer.text).strip()
        row["answer_span_id"] = answer.id
        row["answer_ms"] = answer.start_ms

    try:
        map_ordered(check, pending)
    except Exception as exc:  # verification is an improvement, never a reason to lose the walkaway
        print(f"answer check skipped: {type(exc).__name__}", file=sys.stderr, flush=True)
    return digest


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
