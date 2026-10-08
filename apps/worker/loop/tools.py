# Motivation vs Logic
# Motivation: Several prompts (the ten lenses, the coverage supplement, counterevidence)
# declare an open_span tool. On such a prompt the reasoner answers with a tool call and an
# empty output, and expects the caller to run the tool and ask again in fill mode. A caller
# that skips this reads {} as a real answer: a lens then reports "none_in_transcript" and
# the coverage supplement closes nothing.
# Logic: Run open_span against the meeting's own spans, then ask again with a _fill payload
# that carries the original input and the opened text. At most three tool rounds. A
# tool call that cannot be answered returns the empty turn unchanged, so the caller can
# treat it as "not evaluated" instead of "nothing found".

from __future__ import annotations

from errors import SchemaRejected

MAX_TOOL_ROUNDS = 3


def complete_with_open_span(complete, spans, meeting_id: str | None, payload: dict, aliases: dict | None = None):
    """complete(payload) -> turn. Returns the final turn, or None if complete() does.

    `aliases` maps another id the model may use (a claim id) to the span it cites.
    """
    by_id = {span.id: span for span in spans or []}
    aliases = aliases or {}
    original = payload
    opened: list[str] = []
    results_all: list[dict] = []
    turn = complete(payload)
    for _ in range(MAX_TOOL_ROUNDS):
        if turn is None or not getattr(turn, "tool_calls", None):
            return turn
        fresh: list[dict] = []
        for call in turn.tool_calls:
            if call.name != "open_span":
                raise SchemaRejected("tools are dispatched by name open_span")
            span_id = call.arguments.get("span_id")
            span = by_id.get(span_id) or by_id.get(aliases.get(span_id)) if isinstance(span_id, str) else None
            if span is None:
                continue
            if meeting_id is not None and span.meeting_id != meeting_id:
                raise SchemaRejected("evidence span meeting_id does not match this meeting")
            opened.append(span.id)
            fresh.append({"span_id": span.id, "text": span.text, "start_ms": span.start_ms, "end_ms": span.end_ms})
        if not fresh:
            return turn
        results_all = [*results_all, *fresh]
        turn = complete({**original, "_fill": True, "tool_results": results_all, "opened_ids": list(dict.fromkeys(opened))})
    return turn
