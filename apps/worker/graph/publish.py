# Motivation vs Logic
# Motivation: A finding or sentence that fails provenance is dropped in code, and a queued claim never enters the brief.
# Logic: Supported claims, covered speech, ten dimensions, and visible conflicts decide ready versus needs_review.

from dataclasses import dataclass, field

from graph.audit import audio_figures
from graph.lenses import require_dimensions
from graph.state import Finding, Sentence
from registry.ids import LENS_ORDER


@dataclass
class GateResult:
    status: str
    brief: dict | None
    review_queue: list[str]
    dimensions: dict
    findings: list
    synthesis: list
    synthesis_omissions: list
    actions: list
    claims: list
    disagreements: list
    omissions: list
    gaps: list
    audit: dict
    artifacts: dict
    prompt_release: str | None = None
    versions: dict = field(default_factory=dict)
    ceiling_hit: bool = False
    idempotency_key: str | None = None
    chart: dict | None = None


def keep_findings(findings: list[Finding], claims_by_id: dict) -> list[Finding]:
    kept = []
    for finding in findings:
        if not finding.claim_ids:
            continue
        if all(claims_by_id.get(claim_id) and claims_by_id[claim_id].status == "supported" for claim_id in finding.claim_ids):
            kept.append(finding)
    return kept


def keep_sentences(sentences: list[Sentence], finding_ids: set[str]) -> list[Sentence]:
    kept = []
    for sentence in sentences:
        if sentence.finding_ids and all(finding_id in finding_ids for finding_id in sentence.finding_ids):
            kept.append(sentence)
    return kept


def speech_covered(spans: list, claims: list, omissions: list, gaps: list) -> bool:
    covered = {claim.span_id for claim in claims if claim.span_id}
    covered.update(omission.span_id for omission in omissions)
    for gap in gaps:
        covered.update(gap.span_ids)
    for span in spans:
        if span.kind == "speech" and span.id not in covered:
            return False
    return True


def gate(
    *,
    meeting_id: str,
    duration_ms: int,
    spans: list,
    claims: list,
    findings: list[Finding],
    sentences: list[Sentence],
    synthesis_omissions: list,
    actions: list,
    disagreements: list,
    omissions: list,
    gaps: list,
    dimensions: dict,
    ceiling_hit: bool,
    prompt_release: str | None = None,
    versions: dict | None = None,
    idempotency_key: str | None = None,
    chart: dict | None = None,
) -> GateResult:
    if ceiling_hit:
        published_dimensions = dict(dimensions)
    else:
        require_dimensions(dimensions)
        published_dimensions = {name: dimensions[name] for name in LENS_ORDER}
    claims_by_id = {claim.id: claim for claim in claims}
    visible_findings = keep_findings(findings, claims_by_id)
    # A dropped finding stays addressable on the graph. The brief uses only the kept set.
    finding_ids = {finding.id for finding in visible_findings}
    visible_sentences = keep_sentences(sentences, finding_ids)
    review_queue = [claim.id for claim in claims if claim.status != "supported"]
    cited = {finding_id for sentence in visible_sentences for finding_id in sentence.finding_ids}
    omitted = {item.finding_id for item in synthesis_omissions}
    conflicts_hidden = [
        finding.id
        for finding in visible_findings
        if finding.stance == "conflicts" and finding.id not in cited and finding.id not in omitted
    ]
    covered = speech_covered(spans, claims, omissions, gaps)
    brief_claims = []
    for sentence in visible_sentences:
        for finding_id in sentence.finding_ids:
            finding = next(item for item in visible_findings if item.id == finding_id)
            for claim_id in finding.claim_ids:
                if claim_id not in brief_claims and claim_id not in review_queue:
                    brief_claims.append(claim_id)
    brief = {
        "sentences": [{"text": sentence.text, "finding_ids": list(sentence.finding_ids)} for sentence in visible_sentences],
        "finding_ids": [finding_id for sentence in visible_sentences for finding_id in sentence.finding_ids],
        "claim_ids": brief_claims,
    }
    if set(brief["claim_ids"]) & set(review_queue):
        raise RuntimeError("a queued claim entered the brief")
    status = "ready"
    unevaluated = [name for name, value in published_dimensions.items() if value == "not_evaluated"]
    if review_queue or not covered or conflicts_hidden or gaps or unevaluated:
        status = "needs_review"
    if ceiling_hit:
        status = "needs_review"
        brief = None
    audit = audio_figures(spans, duration_ms, claims)
    artifacts = {
        "ledger": "ready",
        "claims": "ready",
        "counterevidence": "ready",
        "entailment": "ready",
        "coverage": "ready" if covered and not gaps else "incomplete",
        "exports": "not_run",
    }
    return GateResult(
        status=status,
        brief=brief,
        review_queue=review_queue,
        dimensions=published_dimensions,
        findings=visible_findings,
        synthesis=visible_sentences,
        synthesis_omissions=list(synthesis_omissions),
        actions=actions,
        claims=claims,
        disagreements=disagreements,
        omissions=omissions,
        gaps=gaps,
        audit=audit,
        artifacts=artifacts,
        prompt_release=prompt_release,
        versions=versions or {},
        ceiling_hit=ceiling_hit,
        idempotency_key=idempotency_key,
        chart=chart,
    )
