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
MAX_CALLS_PER_ROUND = 4
MAX_ARGUMENT_CHARS = 300


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


# Motivation vs Logic
# Motivation: The walkaway passes can read the person's reference documents while they work, the same way
# the lenses open transcript spans. The lens loop above only knows open_span.
# Logic: Run any set of named tools the caller supplies. A handler takes the call's arguments and returns
# one bounded result, or None when it cannot answer. The model is asked again with the original input
# plus every result so far, at most MAX_TOOL_ROUNDS times. If a round produced nothing usable the model
# is still asked once more, told so, so it answers from what it has instead of returning an empty turn.
# At most MAX_CALLS_PER_ROUND calls run per round and their arguments are cut short. The reasoner offers
# tools only on its first pass, so in practice a model gets one round of tool calls and then answers.

def complete_with_tools(complete, handlers: dict, payload: dict, *, max_rounds: int = MAX_TOOL_ROUNDS):
    """complete(payload) -> turn (or None). handlers: {tool name: fn(arguments) -> dict | None}."""
    original = payload
    results: list[dict] = []
    turn = complete(payload)
    for _ in range(max_rounds):
        if turn is None or not getattr(turn, "tool_calls", None):
            return turn
        fresh: list[dict] = []
        for call in turn.tool_calls[:MAX_CALLS_PER_ROUND]:
            arguments = _short(call.arguments)
            handler = handlers.get(call.name)
            outcome = None
            if handler is not None:
                try:
                    outcome = handler(arguments)
                except Exception:  # a broken tool is no reason to lose the answer
                    outcome = None
            fresh.append({"tool": call.name, "arguments": arguments, "result": outcome if outcome is not None else {"error": "no result"}})
        results = [*results, *fresh]
        turn = complete({**original, "_fill": True, "tool_results": results})
    return turn


def _short(arguments) -> dict:
    """The call's arguments, with long strings cut: they are echoed back to the model with the result."""
    if not isinstance(arguments, dict):
        return {}
    return {str(key)[:40]: (value[:MAX_ARGUMENT_CHARS] if isinstance(value, str) else value) for key, value in list(arguments.items())[:6]}
