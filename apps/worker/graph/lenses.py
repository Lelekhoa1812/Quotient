# Motivation vs Logic
# Motivation: All ten dimensions run on every meeting. None of them sees another lens's prose.
# Logic: Each call gets the supported claims only. The dimension name is the registry pin, not a model field.

from loop.pool import map_ordered
from registry.ids import LENS_ORDER, lens_id
from errors import DimensionSkipped
from graph.state import Finding


def _take_enum(prop: dict, found: set[str]) -> None:
    enum = prop.get("enum")
    if isinstance(enum, list):
        found.update(item for item in enum if isinstance(item, str))
    const = prop.get("const")
    if isinstance(const, str):
        found.add(const)
    for option in prop.get("anyOf") or []:
        if isinstance(option, dict):
            _take_enum(option, found)


def _decision_enum(node, found: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "decision_status" and isinstance(value, dict):
                _take_enum(value, found)
            _decision_enum(value, found)
    elif isinstance(node, list):
        for value in node:
            _decision_enum(value, found)


# Bugs vs Fixes
# Bug: decision_status stayed null so a person could fill it after the lens
# had already returned a value, and the task had nothing terminal to store.
# Fix: Copy the lens value when it is in that schema's enum. If the enum value
# is absent, mark the cited supported claim unresolved so the review queue
# finishes the meeting instead of pausing it.
def apply_decision_status(claims: list, findings: list, schema: dict) -> None:
    allowed: set[str] = set()
    _decision_enum(schema, allowed)
    by_id = {claim.id: claim for claim in claims}
    filled: set[str] = set()
    missing: set[str] = set()
    for finding in findings:
        if finding.dimension != "decision":
            continue
        status = finding.decision_status
        usable = status if isinstance(status, str) and status in allowed else None
        for claim_id in finding.claim_ids:
            claim = by_id.get(claim_id)
            if claim is None or claim.decision_status is not None or claim_id in filled:
                continue
            if usable is not None:
                claim.decision_status = usable
                filled.add(claim_id)
                missing.discard(claim_id)
            else:
                missing.add(claim_id)
    for claim_id in missing:
        claim = by_id[claim_id]
        if claim.decision_status is None and claim.status == "supported":
            claim.status = "unresolved"


def require_dimensions(dimensions: dict) -> None:
    missing = [name for name in LENS_ORDER if name not in dimensions]
    if missing:
        raise DimensionSkipped("skipped dimensions: " + ", ".join(missing))
    for name in LENS_ORDER:
        value = dimensions[name]
        if value not in ("none_in_transcript", "not_evaluated") and not value:
            raise DimensionSkipped(f"{name} has no finding, no none_in_transcript marker, and no not_evaluated marker")


def run_lenses(model, registry, claims: list) -> dict:
    payload = {
        "claims": [
            {
                "id": claim.id,
                # The lens contracts ask for owner/agreement/due span ids and offer open_span;
                # without a span id here the model opened claim ids instead.
                "span_id": claim.span_id,
                "kind": claim.kind,
                "paraphrase": claim.paraphrase,
                "quote": claim.quote,
                "decision_status": claim.decision_status,
            }
            for claim in claims
            if claim.status == "supported"
        ]
    }
    # Bugs vs Fixes
    # Bug: The ten blinded lenses ran one after another, so a meeting waited
    # on ten round trips that do not read each other's prose.
    # Fix: Run them together and merge findings back in LENS_ORDER.
    def ask(dimension: str):
        prompt = registry.prompt(lens_id(dimension))
        turn = model.complete(prompt_id=lens_id(dimension), role=prompt.model_role, payload=payload)
        return dimension, turn

    dimensions: dict = {}
    findings: list[Finding] = []
    for dimension, turn in map_ordered(ask, LENS_ORDER):
        output = turn.output or {}
        # An empty answer (for example a tool call nobody could run) says nothing about
        # the recording. It is "not evaluated", never "none in transcript".
        if not output:
            dimensions[dimension] = "not_evaluated"
            continue
        disposition = output.get("disposition") or output.get("result")
        if disposition == "none_in_transcript":
            dimensions[dimension] = "none_in_transcript"
            continue
        if disposition == "not_evaluated":
            dimensions[dimension] = "not_evaluated"
            continue
        sibling_actions = list(output.get("actions") or []) if dimension == "commitment" else []
        built: list[Finding] = []
        for index, raw in enumerate(output.get("findings") or []):
            drafts = list(raw.get("actions") or [])
            if index == 0:
                drafts = [*sibling_actions, *drafts]
            finding = Finding(
                id=raw.get("id") or f"{dimension}-{index}",
                dimension=dimension,
                stance=raw.get("stance") or "unknown",
                claim_ids=list(raw.get("claim_ids") or []),
                text=raw.get("text") or raw.get("statement") or "",
                decision_status=raw.get("decision_status"),
                action_drafts=drafts if dimension == "commitment" else [],
            )
            built.append(finding)
        if not built:
            dimensions[dimension] = "none_in_transcript"
        else:
            dimensions[dimension] = built
            findings.extend(built)
    require_dimensions(dimensions)
    return {"dimensions": dimensions, "findings": findings}
