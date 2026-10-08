"""Contract tests for tools/list and initialize."""

from starlette.testclient import TestClient

from quotient import PROTOCOL_VERSION, SERVER_NAME, SERVER_TITLE
from quotient.app import create_app
from quotient.worker.memory import MemoryPort

from conftest import open_session, rpc

EXPECTED = {
    "submit_meeting": {
        "taskSupport": "required",
        "readOnlyHint": False,
        "destructiveHint": False,
        "required": ["object_key"],
    },
    "get_meeting": {
        "taskSupport": "forbidden",
        "readOnlyHint": True,
        "destructiveHint": False,
        "required": ["meeting_id"],
    },
    "read_graph": {
        "taskSupport": "forbidden",
        "readOnlyHint": True,
        "destructiveHint": False,
        "required": ["meeting_id"],
    },
    "read_span": {
        "taskSupport": "forbidden",
        "readOnlyHint": True,
        "destructiveHint": False,
        "required": ["meeting_id", "span_id"],
    },
    "accept_action": {
        "taskSupport": "forbidden",
        "readOnlyHint": False,
        "destructiveHint": False,
        "required": ["meeting_id", "action_id"],
    },
    "revise_speaker": {
        "taskSupport": "forbidden",
        "readOnlyHint": False,
        "destructiveHint": False,
        "required": ["meeting_id", "span_id", "scope", "display_name"],
    },
    "revise_text": {
        "taskSupport": "forbidden",
        "readOnlyHint": False,
        "destructiveHint": False,
        "required": ["meeting_id", "span_id", "text"],
    },
    "cancel_meeting": {
        "taskSupport": "forbidden",
        "readOnlyHint": False,
        "destructiveHint": True,
        "required": ["meeting_id"],
    },
}


def test_initialize_and_tools_list_shape():
    app = create_app(auth_bypass=True, port=MemoryPort(), environ={})
    with TestClient(app) as client:
        headers = open_session(client)
        listed = rpc(client, headers, "tools/list")
    tools = listed["result"]["tools"]
    assert [tool["name"] for tool in tools] == list(EXPECTED)
    assert "nextCursor" not in listed["result"]
    for tool in tools:
        spec = EXPECTED[tool["name"]]
        assert tool["title"]
        assert len(tool["description"]) > 40
        assert tool["inputSchema"]["type"] == "object"
        assert tool["inputSchema"]["required"] == spec["required"]
        assert tool["execution"] == {"taskSupport": spec["taskSupport"]}
        assert tool["annotations"]["readOnlyHint"] is spec["readOnlyHint"]
        assert tool["annotations"]["destructiveHint"] is spec["destructiveHint"]
        assert tool["annotations"]["openWorldHint"] is False
        assert "bedrock" not in tool["description"].lower()


def test_initialize_identity():
    app = create_app(auth_bypass=True, port=MemoryPort(), environ={})
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "probe", "version": "0"},
                },
            },
        )
    body = response.json()["result"]
    assert body["protocolVersion"] == PROTOCOL_VERSION
    assert body["serverInfo"]["name"] == SERVER_NAME
    assert body["serverInfo"]["title"] == SERVER_TITLE
    tasks = body["capabilities"]["tasks"]
    assert tasks["requests"]["tools"]["call"] == {}
    assert tasks["list"] == {}
    assert tasks["cancel"] == {}
    assert body["capabilities"]["resources"]["subscribe"] is True


def test_task_support_errors_and_no_meetings_route():
    app = create_app(auth_bypass=True, port=MemoryPort(), environ={})
    with TestClient(app) as client:
        assert client.get("/meetings").status_code == 404
        assert client.post("/v1/meetings").status_code == 404
        headers = open_session(client)
        missing_task = rpc(
            client,
            headers,
            "tools/call",
            {"name": "submit_meeting", "arguments": {"object_key": "media/a.mp4"}},
        )
        forbidden = rpc(
            client,
            headers,
            "tools/call",
            {
                "name": "get_meeting",
                "arguments": {"meeting_id": "m1"},
                "task": {"ttl": 1000},
            },
        )
    assert missing_task["error"]["code"] == -32601
    assert forbidden["error"]["code"] == -32601
