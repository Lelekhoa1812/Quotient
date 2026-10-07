# Motivation vs Logic
# Motivation: Sonic and Pegasus disagreements stay two records. They are not merged into one sentence.
# Logic: Pair by time overlap only. Persist a disagreement solely when the model cites both ids.

from graph.span import Span
from graph.state import Disagreement
from errors import SchemaRejected


def overlapping(span: Span, observations: list) -> list:
    return [
        observation
        for observation in observations
        if observation.start_ms < span.end_ms and observation.end_ms > span.start_ms
    ]


def record_cross(span: Span, observation, output: dict) -> Disagreement | None:
    raw_before = span.raw_text
    text_before = span.text
    relation = output.get("relation")
    if output.get("sonic_span_id") != span.id or output.get("observation_id") != observation.id:
        raise SchemaRejected("cross-modal output must cite the paired sonic span and observation")
    if relation == "agreement":
        _unchanged(span, raw_before, text_before)
        return None
    if relation == "disagreement":
        statement = output.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            raise SchemaRejected("a disagreement requires a conflict statement")
        _unchanged(span, raw_before, text_before)
        return Disagreement(sonic_span_id=span.id, observation_id=observation.id, statement=statement)
    raise SchemaRejected("cross-modal relation must be agreement or disagreement")


def _unchanged(span: Span, raw_before: str, text_before: str) -> None:
    if span.raw_text != raw_before or span.text != text_before:
        raise SchemaRejected("cross-modal pairing must not rewrite span text")
