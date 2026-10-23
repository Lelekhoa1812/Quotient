import pytest

from bedrock.wire import _SonicSession, _pegasus_response


def test_sonic_forbidden_response_has_safe_configuration_guidance():
    session = object.__new__(_SonicSession)
    session._status = 403
    session._model_id = "amazon.nova-2-5-sonic"
    session._error = "sonic HTTP 403"

    with pytest.raises(RuntimeError) as error:
        session._raise_status()

    message = str(error.value)
    assert "configured AWS identity" in message
    assert "Sonic model access" in message
    assert "bidirectional-stream permission" in message


def test_send_all_waits_for_a_busy_non_blocking_socket_instead_of_failing():
    import ssl

    from bedrock import wire

    class Busy:
        """Refuses the first write, then accepts at most 3 bytes at a time."""

        def __init__(self):
            self.refusals = 2
            self.received = bytearray()

        def send(self, view):
            if self.refusals:
                self.refusals -= 1
                raise ssl.SSLWantWriteError("busy")
            chunk = bytes(view[:3])
            self.received.extend(chunk)
            return len(chunk)

        def fileno(self):
            raise OSError  # forces the select() path to be patched out below

    sock = Busy()
    original = wire.select.select
    wire.select.select = lambda r, w, x, t: ([], [], [])
    try:
        wire._send_all(sock, b"abcdefgh")
    finally:
        wire.select.select = original
    assert bytes(sock.received) == b"abcdefgh"


def test_send_all_gives_up_after_its_deadline():
    import pytest
    import ssl

    from bedrock import wire

    class Never:
        def send(self, view):
            raise ssl.SSLWantWriteError("busy")

    original = wire.select.select
    wire.select.select = lambda r, w, x, t: ([], [], [])
    try:
        with pytest.raises(RuntimeError, match="send timed out"):
            wire._send_all(Never(), b"x", timeout=0.05)
    finally:
        wire.select.select = original


def test_send_all_waits_for_readability_when_tls_needs_to_read_first():
    import ssl

    from bedrock import wire

    class NeedsRead:
        def __init__(self):
            self.state = 0
            self.received = bytearray()

        def send(self, view):
            self.state += 1
            if self.state == 1:
                raise ssl.SSLWantReadError("read first")
            self.received.extend(bytes(view))
            return len(view)

    waited = []
    original = wire.select.select
    wire.select.select = lambda r, w, x, t: waited.append(("read" if r else "write")) or ([], [], [])
    try:
        sock = NeedsRead()
        wire._send_all(sock, b"hello")
    finally:
        wire.select.select = original
    assert waited == ["read"] and bytes(sock.received) == b"hello"


def test_pegasus_1_5_stop_reason_becomes_finish_reason():
    # Motivation vs Logic
    # Motivation: Pegasus 1.5 returns stopReason. The client still branches on finishReason.
    # Logic: Copy stopReason into finishReason and leave the JSON message untouched.
    mapped = _pegasus_response(
        {
            "message": '{"observations":[]}',
            "stopReason": "length",
            "input_tokens": 10,
            "output_tokens": 4,
        }
    )
    assert mapped == {"finishReason": "length", "message": '{"observations":[]}'}


def test_to_converse_body_and_response_extraction():
    from bedrock.wire import _converse_response, _to_converse_body

    req = {
        "model": "au.anthropic.claude-haiku-5-5",
        "max_output_tokens": 128000,
        "effort": "xhigh",
        "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": "System prefix prompt",
                        "prompt_cache_breakpoint": {"mode": "explicit"},
                    }
                ],
            },
            {"role": "user", "content": [{"type": "input_text", "text": "Hello world"}]},
        ],
        "tools": [
            {
                "name": "search_docs",
                "description": "Search internal docs",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ],
    }

    body = _to_converse_body(req)
    assert body["additionalModelRequestFields"]["thinking"]["type"] == "adaptive"
    assert body["additionalModelRequestFields"]["output_config"]["effort"] == "xhigh"
    assert body["inferenceConfig"]["maxTokens"] == 128000
    assert body["system"][0]["text"] == "System prefix prompt"
    assert body["system"][1] == {"cachePoint": {"type": "default"}}
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"][0]["text"] == "Hello world"
    assert body["toolConfig"]["tools"][0]["toolSpec"]["name"] == "search_docs"
    assert body["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"]["additionalProperties"] is False

    # Test response parsing
    mock_data = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"reasoningContent": {"reasoningText": {"text": "thinking..."}}},
                    {"text": "Here is the result"},
                    {"toolUse": {"name": "search_docs", "input": {"query": "pricing"}}},
                ],
            }
        },
        "usage": {
            "cacheReadInputTokens": 1024,
            "inputTokens": 200,
            "outputTokens": 50,
        },
    }
    parsed = _converse_response(mock_data)
    assert parsed["output_text"] == "Here is the result"
    assert parsed["tool_calls"] == [{"name": "search_docs", "arguments": {"query": "pricing"}}]
    assert parsed["usage"]["cached_tokens"] == 1024
