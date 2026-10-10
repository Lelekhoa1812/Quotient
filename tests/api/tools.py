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
    "prepare_context": {
        "taskSupport": "forbidden",
        "readOnlyHint": False,
        "destructiveHint": False,
        "required": ["files"],
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
    "merge_speakers": {
        "taskSupport": "forbidden",
        "readOnlyHint": False,
        "destructiveHint": False,
        "required": ["meeting_id", "span_id", "other_span_id", "display_name"],
    },
    "reindex_meeting": {
        "taskSupport": "forbidden",
        "readOnlyHint": False,
        "destructiveHint": False,
        "required": ["meeting_id"],
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


class _ContextPort(MemoryPort):
    """A port that can sign context uploads, to exercise the tool without object storage."""

    def __init__(self):
        super().__init__()
        self.batches = {}
        self.seen = []

    def prepare_context(self, subject, files):
        self.seen.append((subject, files))
        batch = "batch1"
        self.batches[batch] = (subject, [f["filename"] for f in files])
        return {"batch_id": batch, "uploads": [{"index": i, "filename": f["filename"], "upload_url": "http://x/put", "method": "PUT", "headers": {"Content-Type": "text/plain"}, "object_key": f"context/{batch}/{i:02d}-{f['filename']}"} for i, f in enumerate(files)]}

    def context_items(self, subject, batch_id):
        owner = self.batches.get(batch_id)
        return [] if owner and owner[0] == subject else None


def _call(client, headers, name, arguments):
    return rpc(client, headers, "tools/call", {"name": name, "arguments": arguments})


def test_prepare_context_validates_input_and_returns_one_target_per_file():
    port = _ContextPort()
    with TestClient(create_app(auth_bypass=True, port=port, environ={})) as client:
        headers = open_session(client)
        good = _call(client, headers, "prepare_context", {"files": [{"filename": "design.docx", "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "byte_size": 1000}, {"filename": "notes.md"}]})
        body = good["result"]["structuredContent"]
        assert body["batch_id"] == "batch1" and [u["index"] for u in body["uploads"]] == [0, 1]
        for bad in ({"files": []}, {"files": "x"}, {"files": [{}]}, {"files": [{"filename": "a.md", "byte_size": -1}]}, {"files": [{"filename": "a.md", "media_type": 5}]}, {"files": [{"filename": "x" * 201}]}, {"files": [{"filename": "a.md"}] * 21}):
            assert "error" in _call(client, headers, "prepare_context", bad)


def test_prepare_context_without_object_storage_says_so_plainly():
    with TestClient(create_app(auth_bypass=True, port=MemoryPort(), environ={})) as client:
        reply = _call(client, open_session(client), "prepare_context", {"files": [{"filename": "a.md"}]})
        assert reply["result"]["isError"] is True and "object storage" in reply["result"]["structuredContent"]["error"]
