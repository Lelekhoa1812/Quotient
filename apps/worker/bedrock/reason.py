# Motivation vs Logic
# Motivation: Sol and Luna fill a registry schema at the vendor output maximum.
# Logic: Both passes send that schema, so a call ends when the object ends.
# An unconstrained first pass was still generating when the meeting should have published.
# A prompt that declares tools gets one tool round first, with no schema, so a
# function call can return before the fill. Sol falls back once. Luna does not.
# The vendor max_output_tokens value is unchanged.

from __future__ import annotations

import json
import logging

from bedrock.limits import (
    INPUT_TOKEN_BUDGET,
    LUNA_MAX_OUTPUT_TOKENS,
    LUNA_MODEL,
    REASON_REGION,
    SOL_FALLBACK,
    SOL_MAX_OUTPUT_TOKENS,
    SOL_MODEL,
)
from bedrock.turn import ModelTurn, ToolCall
from errors import InputTooLarge, NotInvocable, SchemaRejected
from registry.check import validate_json
from registry.load import Registry

logger = logging.getLogger("quotient.bedrock")

_MODELS = {
    "llm": (SOL_MODEL, SOL_MAX_OUTPUT_TOKENS, SOL_FALLBACK),
    "slm": (LUNA_MODEL, LUNA_MAX_OUTPUT_TOKENS, None),
}


def estimate_tokens(text: str) -> int:
    return len(text) // 4


class Reasoner:
    def __init__(self, registry: Registry, transport):
        self.registry = registry
        self.transport = transport
        self.fallback_log: list[dict] = []

    def complete(
        self,
        *,
        prompt_id: str,
        role: str | None,
        payload: dict,
        max_output_tokens: int | None = None,
    ) -> ModelTurn:
        prompt = self.registry.prompt(prompt_id, expected_role=role)
        if prompt.model_role not in _MODELS:
            raise NotInvocable(prompt.model_role or "", "unpinned-role")
        _model, cap, _fallback = _MODELS[prompt.model_role]
        if max_output_tokens is not None and max_output_tokens != cap:
            raise ValueError(f"max_output_tokens must stay at the vendor maximum {cap}")
        schema = self.registry.schema(prompt.schema_id) if prompt.schema_id else None
        # Bugs vs Fixes
        # Bug: Counterevidence told the model to open spans, but both passes
        # forced a schema object and dropped function calls. opened_ids stayed
        # empty, so every claim failed closed and every lens saw no supported claim.
        # A later round that already held tool results still offered tools, so
        # the model opened spans again and never emitted searched_ids.
        # Fix: A tool prompt gets one round that can return function calls.
        # _fill is a worker control key, stripped before the model sees it, and
        # that round is schema-only.
        filling = bool(payload.get("_fill"))
        payload = {key: value for key, value in payload.items() if key != "_fill"}
        if prompt.tools and not filling:
            trace, calls, cached_tools = self._tools(prompt, payload)
            if calls:
                return ModelTurn(output={}, tool_calls=calls, trace=trace, cached_tokens=cached_tools)
            if not trace.strip():
                trace = json.dumps(payload, sort_keys=True, default=str)
            raw, cached_second = self._pass(prompt, schema, payload, schema_mode=True, trace=trace)
            cached_first = cached_tools
        else:
            trace, cached_first = self._pass(prompt, schema, payload, schema_mode=False, trace="")
            # Bugs vs Fixes
            # Bug: The fill pass saw only the first JSON object, not the cited
            # text, and replaced an entails label with neutral.
            # Fix: A first object that already validates is the turn.
            if schema is not None:
                try:
                    output = validate_json(trace, schema)
                except SchemaRejected:
                    output = None
                if output is not None:
                    return ModelTurn(output=output, trace=trace, cached_tokens=cached_first)
            raw, cached_second = self._pass(prompt, schema, payload, schema_mode=True, trace=trace)
        if schema is None:
            from registry.check import loads_object

            output = loads_object(raw)
        else:
            output = validate_json(raw, schema)
        return ModelTurn(output=output, trace=trace, cached_tokens=cached_first + cached_second)

    def _tools(self, prompt, payload: dict) -> tuple[str, list[ToolCall], int]:
        model_id, cap, fallback = _MODELS[prompt.model_role]
        request = self._request(model_id, cap, prompt, None, payload, False, "", tools=True)
        try:
            response = self.transport.respond(request)
        except NotInvocable as exc:
            if fallback is None:
                logger.info("model_id=%s error_code=%s fallback=", exc.model_id, exc.code)
                raise
            logger.info("model_id=%s error_code=%s fallback=%s", exc.model_id, exc.code, fallback)
            self.fallback_log.append(
                {"model_id": exc.model_id, "error_code": exc.code, "fallback": fallback}
            )
            request = dict(request)
            request["model"] = fallback
            response = self.transport.respond(request)
        calls = []
        for item in response.get("tool_calls") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            arguments = item.get("arguments")
            if isinstance(name, str) and name and isinstance(arguments, dict):
                calls.append(ToolCall(name=name, arguments=arguments))
        return response.get("output_text", ""), calls, int((response.get("usage") or {}).get("cached_tokens") or 0)

    def _pass(self, prompt, schema, payload, *, schema_mode: bool, trace: str) -> tuple[str, int]:
        model_id, cap, fallback = _MODELS[prompt.model_role]
        request = self._request(model_id, cap, prompt, schema, payload, schema_mode, trace, tools=False)
        try:
            response = self.transport.respond(request)
        except NotInvocable as exc:
            if fallback is None:
                logger.info("model_id=%s error_code=%s fallback=", exc.model_id, exc.code)
                raise
            logger.info("model_id=%s error_code=%s fallback=%s", exc.model_id, exc.code, fallback)
            self.fallback_log.append(
                {"model_id": exc.model_id, "error_code": exc.code, "fallback": fallback}
            )
            request = dict(request)
            request["model"] = fallback
            response = self.transport.respond(request)
        return response.get("output_text", ""), int((response.get("usage") or {}).get("cached_tokens") or 0)

    def _request(self, model_id, cap, prompt, schema, payload, schema_mode: bool, trace: str, *, tools: bool) -> dict:
        if cap not in (SOL_MAX_OUTPUT_TOKENS, LUNA_MAX_OUTPUT_TOKENS):
            raise ValueError("refusing to send a max_output_tokens below the vendor maximum")
        prefix_parts = [prompt.body]
        if prompt.tools:
            prefix_parts.append(json.dumps(prompt.tools, sort_keys=True))
        if schema_mode and schema is not None:
            prefix_parts.append(json.dumps(schema, sort_keys=True))
        prefix = "\n".join(prefix_parts)
        user = trace if schema_mode else json.dumps(payload, sort_keys=True, default=str)
        if estimate_tokens(prefix + user) > INPUT_TOKEN_BUDGET:
            raise InputTooLarge(
                f"assembled input estimates above {INPUT_TOKEN_BUDGET} tokens; compact the state object"
            )
        # Bugs vs Fixes
        # Bug: A boolean prompt_cache_breakpoint on a string content field is
        # rejected: the marker has to sit on a cacheable content block.
        # Fix: Put mode explicit on an input_text block. The prefix stays the
        # cached span and the user text stays after it.
        request = {
            "model": model_id,
            "region": REASON_REGION,
            "max_output_tokens": cap,
            "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prefix,
                            "prompt_cache_breakpoint": {"mode": "explicit"},
                        }
                    ],
                },
                {"role": "user", "content": [{"type": "input_text", "text": user}]},
            ],
        }
        if tools:
            request["tools"] = _function_tools(prompt.tools)
            request["tool_choice"] = "auto"
        elif schema is not None:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": prompt.schema_id or prompt.id,
                    "schema": schema,
                }
            }
        return request


def _function_tools(tools: list) -> list[dict]:
    """Registry tool objects become Responses function tools. Schema keywords the vendor rejects stay off the wire."""

    functions = []
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            continue
        parameters = tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {}
        parameters = {
            key: value
            for key, value in parameters.items()
            if key not in {"$schema", "$id", "title", "description"}
        }
        functions.append(
            {
                "type": "function",
                "name": tool["name"],
                "description": tool.get("description") if isinstance(tool.get("description"), str) else "",
                "parameters": parameters or {"type": "object", "properties": {}},
            }
        )
    return functions
