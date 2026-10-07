"""Publish gate, captions, and export resources."""

import json

from starlette.testclient import TestClient

from quotient.app import create_app
from quotient.export.captions import webvtt
from quotient.export.project import render_local
from quotient.graph.gate import project_meeting
from quotient.worker.memory import MemoryPort

from conftest import open_session, published_graph, rpc


def _resource(client, headers, uri: str) -> dict:
    body = rpc(client, headers, "resources/read", {"uri": uri})
    return json.loads(body["result"]["contents"][0]["text"])


def test_brief_withholds_unresolved_claims_and_captions_use_source_time():
    text = "Ship the report by Friday."
    cues = webvtt(
        [
            {
                "span_id": "s1",
                "kind": "speech",
                "start_ms": 1000,
                "end_ms": 1000,
                "text": text,
            }
        ]
    )
    assert cues.startswith("WEBVTT\n")
    assert "00:00:01.000 --> 00:00:01.001" in cues
    assert text in cues

    mismatched = published_graph("m1")
    mismatched["claims"].append(
        {
            "claim_id": "c2",
            "kind": "figure",
            "status": "supported",
            "text": "The budget increased 15%.",
            "origin": "model",
            "citations": [
                {
                    "quote": "15%",
                    "span_id": "s1",
                    "relation": "mentions",
                    "char_start": 0,
                    "char_end": 3,
                    "start_ms": 1000,
                    "end_ms": 4000,
                }
            ],
        }
    )
    projected = project_meeting({"meeting_id": "m1", "status": "ready", "prompt_release": "bad\nprompt", **mismatched})
    assert projected["status"] == "needs_review"
    assert projected["brief"]["withheld"] is True
    assert projected["prompt_release"] is None
    assert projected["brief"]["findings"] == []
    assert "15%" not in json.dumps(projected["brief"])
    assert projected["review"]["counts"]["unresolved"] == 1

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
                "arguments": {"object_key": "media/slice.mp4"},
                "task": {},
            },
        )
        task_id = created["result"]["task"]["taskId"]
        viewed = rpc(client, headers, "tasks/get", {"taskId": task_id})
        meeting_id = viewed["result"]["statusMessage"].split(" ", 2)[1]
        graph = published_graph(meeting_id)
        graph["claims"].append(
            {
                "claim_id": "c-open",
                "kind": "figure",
                "status": "unresolved",
                "text": "The budget increased 15%.",
                "origin": "model",
                "citations": [],
            }
        )
        port.settle(meeting_id, status="ready", graph=graph, prompt_release="registry-1")
        brief = _resource(client, headers, f"quotient://meetings/{meeting_id}/brief")
        review = _resource(client, headers, f"quotient://meetings/{meeting_id}/review")
        assert brief["withheld"] is True
        assert "15%" not in json.dumps(brief)
        assert review["claims"][0]["text"] == "The budget increased 15%."
        captions = rpc(
            client,
            headers,
            "resources/read",
            {"uri": f"quotient://meetings/{meeting_id}/exports/captions.vtt"},
        )
        assert "WEBVTT" in captions["result"]["contents"][0]["text"]
        burned = rpc(
            client,
            headers,
            "resources/read",
            {"uri": f"quotient://meetings/{meeting_id}/exports/burned.mp4"},
        )
        assert burned["error"]["code"] == -32002
        pdf = rpc(
            client,
            headers,
            "resources/read",
            {"uri": f"quotient://meetings/{meeting_id}/exports/brief.pdf"},
        )
        import base64

        blob = base64.b64decode(pdf["result"]["contents"][0]["blob"])
        assert blob.startswith(b"%PDF")
        assert b"15%" not in blob


def test_brief_exports_render_markdown_and_mermaid():
    prose = "The service split is <script>alert(1)</script>."
    flow = f"""{prose}

```mermaid
flowchart TD
  A[API] --> B[Store]
```
"""
    other = """```mermaid
classDiagram
  ClassA <|-- ClassB
```
"""
    brief = {
        "playback": "meetings/m1",
        "withheld": False,
        "dimensions": [],
        "synthesis": [
            {"text": flow, "playback": "meetings/m1?t=1"},
            {"text": other, "playback": "meetings/m1?t=2"},
        ],
        "actions": [],
        "omissions": [],
    }
    projected = {"brief": brief, "graph": {"actions": [], "spans": []}}
    mime, html_bytes = render_local("brief.html", projected)
    page = html_bytes.decode()
    assert mime.startswith("text/html")
    assert "<svg" in page
    assert "API" in page
    assert "Store" in page
    assert 'class="mermaid"' in page
    assert "classDiagram" in page
    assert "mermaid.esm.min.mjs" in page
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    _pdf_mime, pdf = render_local("brief.pdf", projected)
    assert pdf.startswith(b"%PDF")
    assert b"API" in pdf
    assert b"Store" in pdf
    assert b"classDiagram" in pdf
    assert b"none_in_transcript" not in pdf
    assert b"meetings/m1?t=" not in pdf
    assert b"At 0:00" in pdf
    assert b"Brief" in pdf
