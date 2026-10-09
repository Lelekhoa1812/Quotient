# Motivation vs Logic
# Motivation: The published artifact is a provenance graph. Prose is a projection of these objects.
# Logic: Claims, findings, actions, and disagreements stay separate records with explicit ids.

from dataclasses import dataclass, field


@dataclass
class Claim:
    id: str
    meeting_id: str
    kind: str
    proposition: str
    paraphrase: str
    quote: str
    span_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    status: str = "unresolved"
    decision_status: str | None = None
    origin: str = "model"
    coarse: bool = False
    overlap: bool = False
    luna_label: str | None = None
    sol_label: str | None = None
    searched_ids: list[str] = field(default_factory=list)
    opened_ids: list[str] = field(default_factory=list)
    contradicting_quote: str | None = None
    evidence_kind: str = "span"
    # Extractor-provided evidence candidates, validated against its input window.
    source_span_ids: list[str] | None = None
    # confirmed | likely | contradicted | unverified (see graph/claim.py confidence_of).
    confidence: str = "unverified"


@dataclass
class Finding:
    id: str
    dimension: str
    stance: str
    claim_ids: list[str]
    text: str
    decision_status: str | None = None
    action_drafts: list[dict] = field(default_factory=list)


@dataclass
class Sentence:
    text: str
    finding_ids: list[str]


@dataclass
class Action:
    statement: str
    owner_span_id: str | None
    agreement_span_id: str | None
    due_kind: str
    due_surface: str | None
    due_iso: str | None
    due_span_id: str | None
    claim_ids: list[str]
    origin: str
    acceptance: str


@dataclass
class Disagreement:
    sonic_span_id: str
    observation_id: str
    statement: str


@dataclass
class Omission:
    span_id: str
    reason: str


@dataclass
class SynthesisOmission:
    finding_id: str
    reason: str


@dataclass
class Gap:
    span_ids: list[str]
    reason: str
