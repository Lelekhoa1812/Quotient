# Motivation vs Logic
# Motivation: A claim ships only when the quote hits once, both models entail it, and the numbers are in the span.
# Logic: Code resolves the quote and compares labels. Neutral, a split, an empty search, or a bad number stays out.

from graph.numbers import grounded
from graph.quote import resolve_quote
from graph.state import Claim
from graph.span import Span


def dual(luna_label: str | None, sol_label: str | None) -> str:
    if luna_label == "entails" and sol_label == "entails":
        return "entails"
    if luna_label == "contradicts" or sol_label == "contradicts":
        return "contradicted"
    return "gap"


# Motivation vs Logic
# Motivation: "supported" needs both models to agree, which kept most substantive,
# verbatim-quoted statements (figures, procedures, positions) out of everything a reader
# sees. The owner chose to admit a second, visibly marked tier.
# Logic: status keeps its meaning (the gate, review queue and MCP brief are unchanged).
# confidence adds: confirmed = supported; likely = the quote sits verbatim in exactly one
# span, at least one model says entails, neither says contradicts, no verified
# contradicting quote, and the numbers in the claim appear in that span; contradicted;
# otherwise unverified. A failed counter-search bookkeeping check alone does not demote a
# claim below likely, because it is not evidence against it.
def confidence_of(claim: Claim, spans: list[Span]) -> str:
    if claim.status == "supported":
        return "confirmed"
    if claim.status == "contradicted" or claim.contradicting_quote:
        return "contradicted"
    labels = {claim.luna_label, claim.sol_label}
    if "contradicts" in labels:
        return "contradicted"
    if not claim.span_id or "entails" not in labels:
        return "unverified"
    span = next((item for item in spans if item.id == claim.span_id), None)
    if span is None or not grounded(claim.proposition, span.text):
        return "unverified"
    return "likely"


def finalize_claim(claim: Claim, spans: list[Span], *, duration_ms: int) -> Claim:
    _finalize(claim, spans, duration_ms=duration_ms)
    claim.confidence = confidence_of(claim, spans)
    return claim


def _finalize(claim: Claim, spans: list[Span], *, duration_ms: int) -> Claim:
    if claim.evidence_kind == "uncited_note":
        claim.status = "unresolved"
        return claim
    resolution = resolve_quote(
        claim.quote,
        spans,
        meeting_id=claim.meeting_id,
        duration_ms=duration_ms,
        span_ids=set(claim.source_span_ids) if claim.source_span_ids is not None else None,
    )
    if resolution.status != "resolved":
        claim.status = "unresolved"
        return claim
    claim.span_id = resolution.span_id
    claim.char_start = resolution.char_start
    claim.char_end = resolution.char_end
    claim.start_ms = resolution.start_ms
    claim.end_ms = resolution.end_ms
    claim.coarse = resolution.coarse
    claim.overlap = resolution.overlap
    if not claim.searched_ids or set(claim.searched_ids) != set(claim.opened_ids):
        claim.status = "unresolved"
        return claim
    if claim.contradicting_quote:
        claim.status = "contradicted"
        return claim
    verdict = dual(claim.luna_label, claim.sol_label)
    if verdict == "contradicted":
        claim.status = "contradicted"
        return claim
    if verdict != "entails":
        claim.status = "gap"
        return claim
    span = next(item for item in spans if item.id == claim.span_id)
    if not grounded(claim.proposition, span.text):
        claim.status = "unresolved"
        return claim
    claim.status = "supported"
    return claim
