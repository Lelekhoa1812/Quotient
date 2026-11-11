"""NVIDIA NIM transport: request shaping, response cleaning, routing across keys and models, and the provider plan."""

import json

import pytest

from bedrock import nim, provider
from bedrock.nim import NimTransport, NimUnavailable, build_body, parse_response, strip_keywords, strip_schema
from bedrock.reason import Reasoner
from errors import NotInvocable

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Claims",
    "type": "object",
    "additionalProperties": False,
    "required": ["claims"],
    "properties": {"claims": {"type": "array", "uniqueItems": True, "items": {"type": "string"}}},
}


def request(**extra):
    base = {
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
        "max_output_tokens": 4096,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": "Extract claims."}]},
            {"role": "user", "content": [{"type": "input_text", "text": "{\"spans\": []}"}]},
        ],
        "text": {"format": {"type": "json_schema", "name": "meeting.claim.v1", "schema": SCHEMA}},
        "thinking": False,
        "fallback_models": ["poolside/laguna-xs-2.1"],
    }
    base.update(extra)
    return base


def reply(content, status=200, calls=None, finish="stop"):
    message = {"content": content}
    if calls:
        message["tool_calls"] = calls
    return status, json.dumps({"choices": [{"message": message, "finish_reason": finish}], "usage": {"completion_tokens": 5}}).encode()


class Script:
    """A fake network: answers come from a list, and every request is kept."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.seen = []

    def __call__(self, http_request):
        body = json.loads(http_request.data)
        self.seen.append({"key": http_request.get_header("Authorization"), "body": body})
        answer = self.answers.pop(0) if self.answers else reply("{}")
        return answer if isinstance(answer, tuple) else (answer, b"{}")


@pytest.fixture(autouse=True)
def fresh_state():
    nim.reset_keys_for_tests()
    yield
    nim.reset_keys_for_tests()


def test_a_property_named_like_a_keyword_is_kept():
    # Bug: the digest schema has a required property called "title"; stripping the "title" keyword everywhere deleted it,
    # NIM never wrote it, and every digest was rejected.
    schema = {"type": "object", "title": "Digest", "required": ["title"], "properties": {"title": {"type": "string", "title": "T"}, "items": {"type": "array", "uniqueItems": True, "items": {"type": "string"}}}}
    clean = strip_keywords(schema)
    assert "title" in clean["properties"] and "title" not in clean and "title" not in clean["properties"]["title"]
    assert clean["required"] == ["title"] and "uniqueItems" not in json.dumps(clean)
    body = build_body(request(text={"format": {"type": "json_schema", "name": "d", "schema": schema}}), "m", response_format="schema")
    assert "title" in body["response_format"]["json_schema"]["schema"]["properties"]


def test_schema_is_stripped_of_keywords_nim_cannot_express():
    clean = strip_keywords(SCHEMA)
    assert "uniqueItems" not in json.dumps(clean) and "$schema" not in clean and "title" not in clean
    assert clean["properties"]["claims"]["items"] == {"type": "string"}


def test_body_turns_thinking_off_and_sends_a_strict_schema():
    body = build_body(request(), "nvidia/nemotron-3-ultra-550b-a55b", response_format="schema")
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"] is True
    assert body["messages"][0] == {"role": "system", "content": "Extract claims."}
    assert body["max_tokens"] == 4096 and body["stream"] is False


def test_thinking_models_are_left_to_think_when_the_plan_says_so():
    body = build_body(request(thinking=True), "nvidia/nemotron-3-ultra-550b-a55b", response_format="schema")
    assert "chat_template_kwargs" not in body


def test_glm_gets_low_reasoning_effort_when_thinking_is_off():
    body = build_body(request(), "z-ai/glm-5.3-flash", response_format="object")
    assert body["reasoning_effort"] == "low" and body["response_format"] == {"type": "json_object"}


def test_tools_use_the_openai_function_shape_and_drop_the_schema_format():
    tools = [{"name": "open_spans", "description": "d", "parameters": {"type": "object", "properties": {}}}]
    body = build_body(request(tools=tools), "m", response_format="schema")
    assert body["tools"][0]["function"]["name"] == "open_spans" and "response_format" not in body


def test_response_is_cleaned_of_thinking_and_fences():
    text = parse_response({"choices": [{"message": {"content": "<think>hmm</think>\n```json\n{\"claims\": []}\n```"}}]})["output_text"]
    assert text == '{"claims": []}'
    assert parse_response({"choices": [{"message": {"content": "reasoning...</think>{\"a\": 1}"}}]})["output_text"] == '{"a": 1}'


def test_tool_calls_are_parsed_with_json_arguments():
    parsed = parse_response({"choices": [{"message": {"content": None, "tool_calls": [{"function": {"name": "open_spans", "arguments": "{\"ids\": [\"a\"]}"}}]}}]})
    assert parsed["tool_calls"] == [{"name": "open_spans", "arguments": {"ids": ["a"]}}]


def test_a_rate_limited_key_is_skipped_and_the_next_key_answers():
    net = Script((429, b"{}"), reply('{"claims": []}'))
    transport = NimTransport(keys=["nvapi-a", "nvapi-b"], opener=net)
    assert transport.respond(request())["output_text"] == '{"claims": []}'
    assert len(net.seen) == 2 and net.seen[0]["key"] != net.seen[1]["key"]


def test_server_named_unimplemented_keywords_are_removed_and_resent_on_the_same_model():
    error = (400, b'{"message":"Grammar error: Unimplemented keys: [\\"minItems\\"]"}')
    net = Script(error, reply('{"claims": []}'))
    out = NimTransport(keys=["nvapi-a"], opener=net).respond(request())
    assert out["output_text"] == '{"claims": []}'
    assert net.seen[0]["body"]["model"] == net.seen[1]["body"]["model"]


def test_a_grammar_the_model_refuses_falls_back_to_json_object_mode():
    net = Script((400, b'{"message":"Bad Request"}'), reply('{"claims": []}'))
    NimTransport(keys=["nvapi-a"], opener=net).respond(request())
    assert net.seen[0]["body"]["response_format"]["type"] == "json_schema"
    assert net.seen[1]["body"]["response_format"] == {"type": "json_object"}


def test_an_empty_reply_moves_to_the_next_model_in_the_plan():
    net = Script(reply(None, finish="length"), reply('{"claims": []}'))
    out = NimTransport(keys=["nvapi-a", "nvapi-b"], opener=net).respond(request())
    assert out["output_text"] == '{"claims": []}'
    assert [item["body"]["model"] for item in net.seen] == ["nvidia/nemotron-3-ultra-550b-a55b", "poolside/laguna-xs-2.1"]


def test_an_invalid_key_is_not_tried_again_in_this_process():
    seen = []

    def net(http_request):
        key = http_request.get_header("Authorization")
        seen.append(key)
        return (401, b"{}") if key == "Bearer nvapi-bad" else reply('{"claims": []}')

    transport = NimTransport(keys=["nvapi-bad", "nvapi-good"], opener=net)
    for _ in range(4):
        assert transport.respond(request())["output_text"] == '{"claims": []}'
    assert seen.count("Bearer nvapi-bad") <= 1  # tried at most once, and only when the shuffle picked it first


def test_when_nothing_answers_the_error_names_exhaustion_and_never_the_key():
    net = Script(*[(500, b"{}")] * 12)
    with pytest.raises(NotInvocable) as raised:
        NimTransport(keys=["nvapi-secret-1"], opener=net).respond(request())
    assert "nim-exhausted" in raised.value.code and "nvapi-secret-1" not in str(raised.value)


def test_no_keys_is_a_clear_error():
    with pytest.raises(NimUnavailable):
        NimTransport(keys=[]).respond(request())


def test_keys_load_from_numbered_environment_names(monkeypatch):
    for index in range(1, 10):
        monkeypatch.delenv(f"NVIDIA_NIM_API_KEY_{index}", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEYS", raising=False)
    monkeypatch.delenv("NIM_SECRET_ARN", raising=False)
    monkeypatch.setenv("NVIDIA_NIM_API_KEY_1", "nvapi-one")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY_3", "nvapi-three")
    monkeypatch.setenv("NVIDIA_NIM_API_KEYS", "nvapi-x, nvapi-y")
    assert nim.load_keys(refresh=True) == ["nvapi-x", "nvapi-y", "nvapi-one", "nvapi-three"]


# --- provider plan -----------------------------------------------------------------------------------------------


def test_bedrock_plan_is_the_pinned_release():
    plans = provider.plans("bedrock")
    assert plans["llm"].model.endswith("claude-haiku-5-5") and plans["slm"].region == "ap-southeast-2"


def test_nim_plan_gives_fast_passes_no_thinking_and_long_reasoning_thinking():
    plans = provider.plans("nim")
    assert plans["slm"].thinking is False and plans["llm"].thinking is True
    assert plans["slm"].region == "nvidia" and plans["llm"].fallbacks


def test_overrides_only_accept_known_roles_and_proven_models():
    assert provider.clean_overrides({"slm": "poolside/laguna-xs-2.1", "llm": "evil/model", "x": "poolside/laguna-xs-2.1"}) == {"slm": "poolside/laguna-xs-2.1"}
    plans = provider.plans("nim", {"slm": "poolside/laguna-xs-2.1"})
    assert plans["slm"].model == "poolside/laguna-xs-2.1" and "poolside/laguna-xs-2.1" not in plans["slm"].fallbacks
    assert plans["slm"].fallbacks[0] == "nvidia/nemotron-3-ultra-550b-a55b"


def test_provider_names_are_normalised():
    assert provider.normalise_provider(" NIM ") == "nim" and provider.normalise_provider("openai") == ""


def test_reasoner_sends_nim_requests_with_the_plan(monkeypatch):
    from registry.load import Registry as registry

    seen = []

    class Fake:
        def respond(self, req):
            seen.append(req)
            return {"output_text": json.dumps({"claims": [], "gaps": []}), "tool_calls": [], "usage": {}}

    reasoner = Reasoner(registry(), Fake(), plans=provider.plans("nim"))
    reasoner.complete(prompt_id="meeting.claim.v1", role="slm", payload={"span_window": [], "proper_nouns": []})
    assert seen and seen[0]["model"] == "nvidia/nemotron-3-ultra-550b-a55b"
    assert seen[0]["thinking"] is False and seen[0]["fallback_models"]
    assert seen[0]["max_output_tokens"] == provider.plans("nim")["slm"].max_output_tokens


def test_reasoner_without_plans_keeps_the_bedrock_request_unchanged():
    from registry.load import Registry as registry

    seen = []

    class Fake:
        def respond(self, req):
            seen.append(req)
            return {"output_text": json.dumps({"claims": [], "gaps": []}), "tool_calls": [], "usage": {}}

    Reasoner(registry(), Fake()).complete(prompt_id="meeting.claim.v1", role="slm", payload={"span_window": [], "proper_nouns": []})
    assert "thinking" not in seen[0] and seen[0]["region"] == "ap-southeast-2"
