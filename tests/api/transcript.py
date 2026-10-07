"""read_span and read_graph keep raw audio beside the synthesized text."""

import json

from starlette.testclient import TestClient

from quotient.app import create_app
from quotient.worker.memory import MemoryPort

from conftest import open_session, rpc


def test_read_span_and_read_graph_expose_raw_and_synthesized_strings():
    port = MemoryPort()
    app = create_app(auth_bypass=True, port=port, environ={})
    with TestClient(app) as client:
        headers = open_session(client)
        created = rpc(
            client,
            headers,
            "tools/call",
            {
                "name": "submit_meeting",
                "arguments": {"object_key": "media/slice.mp4", "upload_complete": True},
                "task": {"ttl": 60000},
            },
        )
        task_id = created["result"]["task"]["taskId"]
        viewed = rpc(client, headers, "tasks/get", {"taskId": task_id})
        meeting_id = viewed["result"]["statusMessage"].split(" ", 2)[1]
        port.settle(
            meeting_id,
            status="ready",
            graph={
                "raw_transcript": {"audio": "client upload", "video": "client upload"},
                "spans": [
                    {
                        "span_id": "s-late",
                        "meeting_id": meeting_id,
                        "kind": "speech",
                        "start_ms": 5000,
                        "end_ms": 6000,
                        "raw_text": "beta from audio",
                        "text": "beta synthesized",
                        "coarse": False,
                        "overlap": False,
                    },
                    {
                        "span_id": "s-gap",
                        "meeting_id": meeting_id,
                        "kind": "speech",
                        "start_ms": 2000,
                        "end_ms": 2100,
                        "raw_text": "",
                        "text": "gap synthesized",
                        "coarse": False,
                        "overlap": False,
                    },
                    {
                        "span_id": "s-early",
                        "meeting_id": meeting_id,
                        "kind": "speech",
                        "start_ms": 100,
                        "end_ms": 900,
                        "raw_text": "alpha from audio",
                        "text": "alpha synthesized",
                        "coarse": False,
                        "overlap": False,
                    },
                ],
                "observations": [
                    {"id": "o2", "statement": "second frame", "start_ms": 7000, "end_ms": 7100},
                    {"id": "o1", "statement": "first frame", "start_ms": 50, "end_ms": 80},
                ],
                "claims": [],
                "omissions": [],
            },
        )
        early = rpc(
            client,
            headers,
            "tools/call",
            {"name": "read_span", "arguments": {"meeting_id": meeting_id, "span_id": "s-early"}},
        )
        late = rpc(
            client,
            headers,
            "tools/call",
            {"name": "read_span", "arguments": {"meeting_id": meeting_id, "span_id": "s-late"}},
        )
        graph = rpc(client, headers, "tools/call", {"name": "read_graph", "arguments": {"meeting_id": meeting_id}})
        resource = rpc(client, headers, "resources/read", {"uri": f"quotient://meetings/{meeting_id}/graph"})
        brief = rpc(client, headers, "resources/read", {"uri": f"quotient://meetings/{meeting_id}/brief"})
        meeting = rpc(client, headers, "tools/call", {"name": "get_meeting", "arguments": {"meeting_id": meeting_id}})

    early_body = early["result"]["structuredContent"]
    late_body = late["result"]["structuredContent"]
    assert early_body["raw_text"] == "alpha from audio"
    assert early_body["text"] == "alpha synthesized"
    assert late_body["raw_text"] == "beta from audio"
    assert late_body["text"] == "beta synthesized"

    page = graph["result"]["structuredContent"]
    assert page["raw_transcript"] == {
        "audio": "alpha from audio\nbeta from audio",
        "video": "first frame\nsecond frame",
    }
    assert [span["span_id"] for span in page["spans"]] == ["s-late", "s-gap", "s-early"]
    assert page["spans"][0]["raw_text"] == "beta from audio"
    assert page["spans"][0]["text"] == "beta synthesized"
    assert "observations" not in page
    assert "raw_transcript" not in meeting["result"]["structuredContent"]

    stored = json.loads(resource["result"]["contents"][0]["text"])
    assert stored["raw_transcript"] == page["raw_transcript"]
    assert stored["spans"][2]["raw_text"] == "alpha from audio"
    assert stored["spans"][2]["text"] == "alpha synthesized"
    published = json.loads(brief["result"]["contents"][0]["text"])
    assert "raw_transcript" not in published
