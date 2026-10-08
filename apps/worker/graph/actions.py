# Motivation vs Logic
# Motivation: An action has no owner string. Due dates come from the quote.
# accept_action stays the later override and still leaves a model row proposed.
# Logic: Validate the registry schema, strip an ISO date the quote or anchor does not support, and merge shared span ids.

from errors import RegistryMissing
from registry.check import validate
from registry.ids import ACTION, lens_id
from graph.span import Span
from graph.state import Action

_FIRST = {"i", "i'm", "i've", "i'd", "i'll"}


def action_schema(registry) -> dict:
    try:
        return registry.schema(ACTION)
    except RegistryMissing:
        found = _find_action_schema(registry.schema(lens_id("commitment")))
        if found is None:
            raise RegistryMissing(
                "contracts registry has no meeting.action.v1 schema and "
                "meeting.lens_commitment.v1 does not define an action object."
            )
        return found


def _checked(payload: dict, registry, spans: list[Span], *, quote: str, anchor_date: str | None) -> Action:
    validate(payload, action_schema(registry))
    action = Action(
        statement=payload["statement"],
        owner_span_id=payload.get("owner_span_id"),
        agreement_span_id=payload.get("agreement_span_id"),
        due_kind=payload["due_kind"],
        due_surface=payload.get("due_surface"),
        due_iso=payload.get("due_iso"),
        due_span_id=payload.get("due_span_id"),
        claim_ids=list(payload.get("claim_ids") or []),
        origin=payload.get("origin", "model"),
        acceptance=payload.get("acceptance", "proposed"),
    )
    ground_due(action, quote, anchor_date)
    apply_owner(action, {span.id: span for span in spans})
    return action


def accept_action(payload: dict, registry, spans: list[Span], *, quote: str, anchor_date: str | None) -> Action:
    action = _checked(payload, registry, spans, quote=quote, anchor_date=anchor_date)
    if action.origin == "model":
        action.acceptance = "proposed"
    return action


# Bugs vs Fixes
# Bug 1: The analysis run called accept_action, which forced model rows to stay
# proposed until a person accepted them.
# Fix 1: A model row is stored accepted when the run itself found the agreement.
# Bug 2: "Accepted" was stored whenever an owner span resolved. The commitment lens contract says
# a suggestion with a null agreement_span_id stays proposed, so a lecturer's teaching move
# ("I'll multiply by three") with a speaker but no agreement became an accepted action.
# Fix 2: Accepted needs BOTH a resolved owner span and an agreement span that exists in this
# meeting. Anything else stays proposed until a person accepts it. Human rows keep their own state.
def ground_action(payload: dict, registry, spans: list[Span], *, quote: str, anchor_date: str | None) -> Action:
    action = _checked(payload, registry, spans, quote=quote, anchor_date=anchor_date)
    if action.origin == "human":
        return action
    known = {span.id for span in spans}
    agreed = bool(action.agreement_span_id) and action.agreement_span_id in known
    action.acceptance = "accepted" if action.owner_span_id and agreed else "proposed"
    return action


def ground_due(action: Action, quote: str, anchor_date: str | None) -> None:
    if action.due_kind == "relative":
        action.due_iso = anchor_date
        return
    if action.due_kind == "absolute":
        candidate = action.due_iso or action.due_surface
        if candidate and candidate in quote:
            action.due_iso = candidate
        else:
            action.due_iso = None
            if action.due_surface and action.due_surface not in quote:
                action.due_surface = None
        return
    action.due_iso = None


def apply_owner(action: Action, spans: dict[str, Span]) -> None:
    if action.owner_span_id is None:
        return
    span = spans.get(action.owner_span_id)
    if span is None:
        action.owner_span_id = None
        return
    if _first_person(span.text) and not span.speaker_hypothesis_id:
        action.owner_span_id = None


def owner_display(action: Action, spans: dict[str, Span]) -> str:
    if not action.owner_span_id:
        return "not stated"
    return spans[action.owner_span_id].text


def _span_ids(action: Action) -> set[str]:
    return {value for value in (action.owner_span_id, action.agreement_span_id, action.due_span_id) if value}


def merge_actions(actions: list[Action]) -> list[Action]:
    merged: list[Action] = []
    for action in actions:
        ids = _span_ids(action)
        host = None
        if ids:
            for existing in merged:
                if ids & _span_ids(existing):
                    host = existing
                    break
        if host is None:
            merged.append(action)
            continue
        host.claim_ids = list(dict.fromkeys([*host.claim_ids, *action.claim_ids]))
        if "human" in {host.origin, action.origin}:
            host.origin = "human"
        # Bugs vs Fixes
        # Bug: A system-accepted row merged with a proposed sibling stayed proposed.
        # Fix: accepted wins on the merged row. Human origin is set above.
        if "accepted" in {host.acceptance, action.acceptance}:
            host.acceptance = "accepted"
    return merged


def retain_durable(previous: list[Action], regenerated: list[Action]) -> list[Action]:
    durable = [action for action in previous if action.acceptance == "accepted" or action.origin == "human"]
    return merge_actions([*regenerated, *durable])


def _find_action_schema(node):
    if isinstance(node, dict):
        properties = node.get("properties") or {}
        required = set(node.get("required") or [])
        if "owner_span_id" in properties and "due_kind" in required and node.get("additionalProperties") is False:
            return node
        for value in node.values():
            found = _find_action_schema(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_action_schema(value)
            if found is not None:
                return found
    return None


def _first_person(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    token = stripped.split()[0].lower().strip(".,:;\"'")
    return token in _FIRST
