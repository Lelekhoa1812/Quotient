"""Task lifecycle, auth binding, and partner prompts."""

import json

from starlette.testclient import TestClient

from quotient.app import create_app
from quotient.worker.memory import MemoryPort

from conftest import MapVerifier, open_session, published_graph, rpc


def _meeting_id(client, headers, task_id: str) -> str:
    viewed = rpc(client, headers, "tasks/get", {"taskId": task_id})
    message = viewed["result"]["statusMessage"]
    assert message.startswith("Meeting ")
    return message.split(" ", 2)[1]


def test_submit_task_reaches_ready_and_prompts_are_partner_workflows():
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
                "_meta": {"progressToken": "p1"},
            },
        )
        task = created["result"]["task"]
        assert task["status"] == "working"
        assert task["ttl"] == 60000
        assert task["pollInterval"] == 1000
        meeting_id = _meeting_id(client, headers, task["taskId"])
        port.settle(meeting_id, status="ready", graph=published_graph(meeting_id), prompt_release="registry-1")
        completed = rpc(client, headers, "tasks/get", {"taskId": task["taskId"]})
        assert completed["result"]["status"] == "completed"
        finished = rpc(client, headers, "tasks/result", {"taskId": task["taskId"]})
        summary = finished["result"]["structuredContent"]
        assert summary["meeting_id"] == meeting_id
        assert summary["status"] == "ready"
        assert summary["withheld"] is False
        assert finished["result"]["_meta"]["io.modelcontextprotocol/related-task"]["taskId"] == task["taskId"]
        graph = rpc(client, headers, "tools/call", {"name": "read_graph", "arguments": {"meeting_id": meeting_id}})
        page = graph["result"]["structuredContent"]
        assert [row["dimension"] for row in page["dimensions"]] == [
            "decision",
            "commitment",
            "temporal",
            "stakeholder",
            "cross_modal",
            "documentary",
            "risk",
            "gap",
            "dependency",
            "question",
        ]
        assert page["dimensions"][0]["state"] == "findings"
        assert all(row["state"] == "none_in_transcript" for row in page["dimensions"][1:])
        assert page["synthesis"][0]["finding_ids"] == ["f1"]
        assert page["synthesis"][0]["playback"] == f"meetings/{meeting_id}?t=1000"
        assert "owner" not in page["actions"][0]
        assert page["actions"][0]["owner_display"] == "not stated"
        assert page["actions"][0]["due_date"] is None
        assert "raw_transcript" not in summary
        assert page["raw_transcript"] == {"audio": "Ship the report by Friday.", "video": ""}
        assert page["spans"][0]["raw_text"] == "Ship the report by Friday."
        assert page["spans"][0]["text"] == "Ship the report by Friday."
        span = rpc(
            client,
            headers,
            "tools/call",
            {"name": "read_span", "arguments": {"meeting_id": meeting_id, "span_id": "s1"}},
        )
        span_body = span["result"]["structuredContent"]
        assert span_body["raw_text"] == "Ship the report by Friday."
        assert span_body["text"] == "Ship the report by Friday."
        prompts = rpc(client, headers, "prompts/list")
        assert [item["name"] for item in prompts["result"]["prompts"]] == [
            "brief_this_meeting",
            "open_questions",
            "proposed_actions",
        ]
        brief = rpc(
            client,
            headers,
            "prompts/get",
            {"name": "brief_this_meeting", "arguments": {"meeting_id": meeting_id}},
        )
        text = brief["result"]["messages"][0]["content"]["text"]
        assert meeting_id in text
        assert "review" in text
        assert "contracts/prompts" not in text


def test_incomplete_upload_is_input_required_and_tasks_are_auth_bound():
    port = MemoryPort()
    app = create_app(
        auth_bypass=False,
        port=port,
        verifier=MapVerifier({"alpha": "subject-a", "beta": "subject-b"}),
        environ={},
    )
    with TestClient(app) as client:
        alpha = open_session(client, "alpha")
        beta = open_session(client, "beta")
        created = rpc(
            client,
            alpha,
            "tools/call",
            {
                "name": "submit_meeting",
                "arguments": {"object_key": "", "upload_complete": False},
                "task": {},
            },
        )
        task_id = created["result"]["task"]["taskId"]
        viewed = rpc(client, alpha, "tasks/get", {"taskId": task_id})
        assert viewed["result"]["status"] == "input_required"
        hidden = rpc(client, beta, "tasks/get", {"taskId": task_id})
        assert hidden["error"]["code"] == -32602
        listed = rpc(client, beta, "tasks/list")
        assert listed["result"]["tasks"] == []
        record = app.state.runtime.tasks.get(task_id, "subject-a")
        resumed = client.post(
            "/mcp",
            headers=alpha,
            json={
                "jsonrpc": "2.0",
                "id": record.elicitation_id,
                "result": {
                    "action": "accept",
                    "content": {"object_key": "media/a.mp4", "upload_complete": True},
                },
            },
        )
        assert resumed.status_code == 202
        meeting_id = _meeting_id(client, alpha, task_id)
        foreign = rpc(
            client,
            beta,
            "tools/call",
            {"name": "get_meeting", "arguments": {"meeting_id": meeting_id}},
        )
        assert foreign["result"]["isError"] is True
        same = rpc(
            client,
            alpha,
            "tools/call",
            {"name": "get_meeting", "arguments": {"meeting_id": meeting_id}},
        )
        assert same["result"]["structuredContent"]["status"] == "queued"
        assert json.loads(same["result"]["content"][0]["text"])["meeting_id"] == meeting_id


def test_needs_review_completes_the_task():
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
        assert created["result"]["task"]["status"] == "working"
        meeting_id = _meeting_id(client, headers, task_id)
        port.settle(
            meeting_id,
            status="needs_review",
            graph=published_graph(meeting_id),
            prompt_release="registry-1",
        )
        completed = rpc(client, headers, "tasks/get", {"taskId": task_id})
        assert completed["result"]["status"] == "completed"
        finished = rpc(client, headers, "tasks/result", {"taskId": task_id})
        summary = finished["result"]["structuredContent"]
        assert summary["status"] == "needs_review"
        assert summary["withheld"] is True
