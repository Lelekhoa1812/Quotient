"""Audit lines for Bedrock and Jev stay free of secrets and request bodies."""

import json

from audit import record
from bedrock.wire import Transport
from jev.client import Client


def test_record_is_silent_until_the_log_path_is_set(monkeypatch, tmp_path):
    monkeypatch.delenv("QUOTIENT_AUDIT_LOG", raising=False)
    record("llm", "respond", model_id="global.openai.gpt-6.1-sol", authorization="secret-value")
    assert list(tmp_path.iterdir()) == []


def test_record_drops_secret_names_and_configured_values(monkeypatch, tmp_path):
    path = tmp_path / "audit.log"
    monkeypatch.setenv("QUOTIENT_AUDIT_LOG", str(path))
    monkeypatch.setenv("AWS_BEDROCK_API_KEY", "bedrock-secret-value")
    record(
        "llm",
        "respond",
        model_id="bedrock-secret-value",
        authorization="should-not-appear",
        status=200,
    )
    line = path.read_text(encoding="utf-8")
    event = json.loads(line)
    assert event["service"] == "llm"
    assert event["operation"] == "respond"
    assert event["status"] == 200
    assert event["model_id"] == "[redacted]"
    assert "authorization" not in event
    assert "should-not-appear" not in line
    assert "bedrock-secret-value" not in line


def test_output_text_keeps_the_last_message():
    from bedrock.wire import _output_text

    text = _output_text(
        {
            "output": [
                {"type": "reasoning", "content": [{"type": "output_text", "text": "think"}]},
                {"type": "message", "content": [{"type": "output_text", "text": "preamble"}]},
                {"type": "message", "content": [{"type": "output_text", "text": '{"ok": true}'}]},
            ]
        }
    )
    assert text == '{"ok": true}'


def test_function_call_arguments_parse_and_bad_json_is_dropped():
    from bedrock.wire import _function_calls

    calls = _function_calls(
        {
            "output": [
                {"type": "function_call", "name": "open_span", "arguments": '{"span_id": "s1"}'},
                {"type": "function_call", "name": "open_span", "arguments": "not-json"},
                {"type": "message", "content": [{"text": "done"}]},
            ]
        }
    )
    assert calls == [{"name": "open_span", "arguments": {"span_id": "s1"}}]


def test_bedrock_respond_appends_status_without_the_body(monkeypatch, tmp_path):
    path = tmp_path / "audit.log"
    monkeypatch.setenv("QUOTIENT_AUDIT_LOG", str(path))
    monkeypatch.setattr(
        "bedrock.wire._auth_headers",
        lambda *args, **kwargs: {"Content-Type": "application/json"},
    )

    def opener(request):
        assert b"meeting transcript" in request.data
        return 200, b'{"output_text":"private answer"}'

    transport = Transport(token="local-audit-token", opener=opener)
    result = transport.respond(
        {"model": "global.openai.gpt-6.1-sol", "region": "ap-southeast-2", "input": "meeting transcript"}
    )
    assert result["output_text"] == "private answer"
    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["service"] == "llm"
    assert event["operation"] == "respond"
    assert event["model_id"] == "global.openai.gpt-6.1-sol"
    assert event["host"] == "bedrock-runtime.ap-southeast-2.amazonaws.com"
    assert event["status"] == 200
    assert event["request_bytes"] > 0
    assert "meeting transcript" not in path.read_text(encoding="utf-8")
    assert "private answer" not in path.read_text(encoding="utf-8")
    assert "local-audit-token" not in path.read_text(encoding="utf-8")


def test_jev_exchange_records_status_without_the_key(monkeypatch, tmp_path):
    path = tmp_path / "audit.log"
    monkeypatch.setenv("QUOTIENT_AUDIT_LOG", str(path))
    monkeypatch.setenv("JEV_TYPESAFE_API_KEY", "typesafe-secret-value")
    client = Client("typesafe-secret-value", transport=lambda payload: (200, {}, b'{"rank":1}'))
    assert client.evaluate({"utterance": "ship the report"})["rank"] == 1
    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["service"] == "api"
    assert event["operation"] == "jev"
    assert event["model"] == "jev-1.13.0"
    assert event["status"] == 200
    text = path.read_text(encoding="utf-8")
    assert "typesafe-secret-value" not in text
    assert "ship the report" not in text
