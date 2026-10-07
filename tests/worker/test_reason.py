from pathlib import Path

import pytest

from bedrock.limits import LUNA_MAX_OUTPUT_TOKENS, LUNA_MODEL, SOL_FALLBACK, SOL_MAX_OUTPUT_TOKENS, SOL_MODEL
from bedrock.reason import Reasoner
from registry.load import Registry
from support import registry
from errors import InputTooLarge, NotInvocable, SchemaRejected


class Transport:
    def __init__(self, texts, *, reject_sol=False, reject_luna=False):
        self.texts = list(texts)
        self.reject_sol = reject_sol
        self.reject_luna = reject_luna
        self.requests = []

    def respond(self, request):
        self.requests.append(request)
        if self.reject_sol and request["model"] == SOL_MODEL:
            raise NotInvocable(SOL_MODEL, "ValidationException")
        if self.reject_luna and request["model"] == LUNA_MODEL:
            raise NotInvocable(LUNA_MODEL, "ValidationException")
        calls = []
        return {"output_text": self.texts.pop(0) if self.texts else "", "tool_calls": calls, "usage": {"cached_tokens": 12}}


def test_two_passes_use_vendor_max_and_cache_the_prefix():
    transport = Transport(["free text trace", '{"label": "entails"}'])
    turn = Reasoner(registry(), transport).complete(
        prompt_id="meeting.entailment.v1",
        role="llm",
        payload={"paraphrase": "Margin is fifteen percent.", "quotes": ["15%"]},
    )
    assert turn.output == {"label": "entails"}
    assert turn.cached_tokens == 24
    first, second = transport.requests
    assert first["text"]["format"]["type"] == "json_schema"
    assert second["text"]["format"]["type"] == "json_schema"
    assert first["max_output_tokens"] == SOL_MAX_OUTPUT_TOKENS == 131072
    assert second["max_output_tokens"] == 131072
    assert first["region"] == "ap-southeast-2"
    assert first["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert first["input"][0]["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert first["model"] == SOL_MODEL


def test_valid_first_object_is_not_relabeled():
    transport = Transport(['{"label": "entails"}', '{"label": "neutral"}'])
    turn = Reasoner(registry(), transport).complete(
        prompt_id="meeting.entailment.v1",
        role="llm",
        payload={"paraphrase": "The new wave is coming.", "cited_span_texts": ["the new wave is coming"]},
    )
    assert turn.output == {"label": "entails"}
    assert len(transport.requests) == 1


def test_tool_round_returns_before_the_schema_fill():
    class Calling(Transport):
        def respond(self, request):
            self.requests.append(request)
            return {
                "output_text": "",
                "tool_calls": [{"name": "open_span", "arguments": {"span_id": "span-1"}}],
                "usage": {"cached_tokens": 3},
            }

    transport = Calling([])
    root = Path(__file__).resolve().parents[2] / "contracts"
    turn = Reasoner(Registry(root), transport).complete(
        prompt_id="meeting.counterevidence.v1",
        role="slm",
        payload={"paraphrase": "He will introduce himself.", "quotes": ["i'll introduce myself"]},
    )
    assert [(call.name, call.arguments) for call in turn.tool_calls] == [("open_span", {"span_id": "span-1"})]
    assert len(transport.requests) == 1
    sent = transport.requests[0]
    assert sent["tool_choice"] == "auto"
    assert sent["tools"][0]["name"] == "open_span"
    assert "$schema" not in sent["tools"][0]["parameters"]
    assert "text" not in sent
    assert sent["max_output_tokens"] == LUNA_MAX_OUTPUT_TOKENS


def test_tool_prompt_fills_schema_when_no_tool_is_called():
    transport = Transport(["opened nothing", '{"searched_ids": ["span-1"], "finding": {"kind": "empty"}}'])
    root = Path(__file__).resolve().parents[2] / "contracts"
    turn = Reasoner(Registry(root), transport).complete(
        prompt_id="meeting.counterevidence.v1",
        role="slm",
        payload={"paraphrase": "p", "quotes": ["q"]},
    )
    assert turn.output == {"searched_ids": ["span-1"], "finding": {"kind": "empty"}}
    assert turn.tool_calls == []
    first, second = transport.requests
    assert first["tools"][0]["name"] == "open_span"
    assert "text" not in first
    assert second["text"]["format"]["type"] == "json_schema"
    assert "tools" not in second


def test_fill_round_does_not_offer_tools():
    transport = Transport(["trace", '{"searched_ids": ["span-1"], "finding": {"kind": "empty"}}'])
    root = Path(__file__).resolve().parents[2] / "contracts"
    turn = Reasoner(Registry(root), transport).complete(
        prompt_id="meeting.counterevidence.v1",
        role="slm",
        payload={"_fill": True, "tool_results": [{"span_id": "span-1", "text": "ship Friday"}], "opened_ids": ["span-1"]},
    )
    assert turn.output["searched_ids"] == ["span-1"]
    assert turn.tool_calls == []
    first = transport.requests[0]
    assert "tools" not in first
    assert first["text"]["format"]["type"] == "json_schema"
    assert "_fill" not in first["input"][1]["content"][0]["text"]


def test_sol_falls_back_once_and_luna_does_not():
    transport = Transport(['{"label": "entails"}', '{"label": "entails"}'], reject_sol=True)
    reasoner = Reasoner(registry(), transport)
    turn = reasoner.complete(prompt_id="meeting.entailment.v1", role="llm", payload={"paraphrase": "p", "quotes": ["q"]})
    assert turn.output["label"] == "entails"
    assert {row["fallback"] for row in reasoner.fallback_log} == {SOL_FALLBACK}
    assert any(request["model"] == SOL_FALLBACK for request in transport.requests)
    luna = Transport([], reject_luna=True)
    with pytest.raises(NotInvocable) as caught:
        Reasoner(registry(), luna).complete(
            prompt_id="meeting.entailment_luna.v1",
            role="slm",
            payload={"paraphrase": "p", "quotes": ["q"]},
        )
    assert caught.value.model_id == LUNA_MODEL
    assert caught.value.code == "ValidationException"
    assert all(request["max_output_tokens"] == LUNA_MAX_OUTPUT_TOKENS for request in luna.requests)


def test_lower_max_tokens_truncated_json_and_oversize_input_fail():
    transport = Transport([])
    with pytest.raises(ValueError, match="vendor maximum"):
        Reasoner(registry(), transport).complete(
            prompt_id="meeting.entailment.v1",
            role="llm",
            payload={},
            max_output_tokens=1024,
        )
    assert transport.requests == []
    broken = Transport(["trace", "{"])
    with pytest.raises(SchemaRejected):
        Reasoner(registry(), broken).complete(prompt_id="meeting.entailment.v1", role="llm", payload={"a": 1})
    invalid = Transport(["trace", '{"label": "yes"}'])
    with pytest.raises(SchemaRejected):
        Reasoner(registry(), invalid).complete(prompt_id="meeting.entailment.v1", role="llm", payload={"a": 1})
    huge = Transport([])
    with pytest.raises(InputTooLarge):
        Reasoner(registry(), huge).complete(
            prompt_id="meeting.entailment.v1",
            role="llm",
            payload={"blob": "x" * (272_000 * 4)},
        )
    assert huge.requests == []
