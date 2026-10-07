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


def finalize_claim(claim: Claim, spans: list[Span], *, duration_ms: int) -> Claim:
    if claim.evidence_kind == "uncited_note":
        claim.status = "unresolved"
        return claim
    resolution = resolve_quote(claim.quote, spans, meeting_id=claim.meeting_id, duration_ms=duration_ms)
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
