"""Task lifecycle, auth binding, and partner prompts."""

import json
from types import SimpleNamespace

from starlette.testclient import TestClient

from quotient.app import create_app
from quotient.worker.memory import MemoryPort
from quotient.mcp.jobs import _progress, _sync
from quotient.mcp.tasks import TaskRecord

from conftest import MapVerifier, open_session, published_graph, rpc


def _meeting_id(client, headers, task_id: str) -> str:
    viewed = rpc(client, headers, "tasks/get", {"taskId": task_id})
    message = viewed["result"]["statusMessage"]
    assert message.startswith("Meeting ")
    return message.split(" ", 2)[1]


def test_long_running_task_reports_same_phase_progress_updates():
    events = []
    session = SimpleNamespace(enqueue=events.append)
    runtime = SimpleNamespace(sessions=SimpleNamespace(get=lambda _session_id: session))
    task = TaskRecord(
        task_id="task-1",
        auth_subject="subject-1",
        session_id="session-1",
        status="working",
        status_message="Meeting m1 is queued.",
        created_at="2026-10-08T00:00:00Z",
        last_updated_at="2026-10-08T00:00:00Z",
        ttl_ms=60_000,
        poll_interval_ms=1000,
        progress_token="p1",
    )
    _progress(task, runtime, 2, "Extracting claims from the transcript")
    _progress(task, runtime, 2, "Analyzing all ten evidence lenses")
    assert task.progress == 2
    assert task.status_message == "Analyzing all ten evidence lenses"
    assert [event["params"]["message"] for event in events] == [
        "Extracting claims from the transcript",
        "Analyzing all ten evidence lenses",
    ]

    without_token = TaskRecord(
        task_id="task-no-token",
        auth_subject="subject-1",
        session_id="session-1",
        status="working",
        status_message="Meeting m1 is queued.",
        created_at="2026-10-08T00:00:00Z",
        last_updated_at="2026-10-08T00:00:00Z",
        ttl_ms=60_000,
        poll_interval_ms=1000,
    )
    _progress(without_token, runtime, 2, "Checking transcript coverage")
    assert without_token.status_message == "Checking transcript coverage"


def test_task_sync_forwards_persisted_worker_stage_changes():
    port = MemoryPort()
    meeting_id = port.submit(
        subject="subject-1",
        object_key="derivatives/source.mp4",
        context_names=(),
        idempotency_key=None,
    )
    port._rows[meeting_id]["status"] = "working"
    port._rows[meeting_id]["progress_message"] = "Checking transcript coverage"
    events = []
    session = SimpleNamespace(enqueue=events.append)
    runtime = SimpleNamespace(
        port=port,
        sessions=SimpleNamespace(get=lambda _session_id: session),
    )
    task = TaskRecord(
        task_id="task-stage",
        auth_subject="subject-1",
        session_id="session-1",
        status="working",
        status_message="Meeting queued",
        created_at="2026-10-08T00:00:00Z",
        last_updated_at="2026-10-08T00:00:00Z",
        ttl_ms=60_000,
        poll_interval_ms=1000,
        progress_token="stage-token",
        meeting_id=meeting_id,
    )

    assert _sync(task, runtime) is False
    port._rows[meeting_id]["progress_message"] = "Analyzing all ten evidence lenses"
    assert _sync(task, runtime) is False
    assert [event["params"]["message"] for event in events] == [
        "Checking transcript coverage",
        "Analyzing all ten evidence lenses",
    ]


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
        assert "digest" in text and "likely" in text and "context" in text
        for name in ("open_questions", "proposed_actions"):
            body = rpc(client, headers, "prompts/get", {"name": name, "arguments": {"meeting_id": meeting_id}})
            assert "digest" in body["result"]["messages"][0]["content"]["text"]


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


class _UploadPort(MemoryPort):
    """A MemoryPort that signs uploads and reports which keys are stored."""

    def __init__(self, stored: dict | None = None):
        super().__init__()
        self.stored = stored or {}
        self.submitted = []

    def upload_target(self, task_id, filename, media_type, byte_size):
        key = f"uploads/{task_id}/{filename}"
        return {"upload_url": f"http://storage.test/{key}?sig=1", "method": "PUT", "headers": {"Content-Type": media_type}, "object_key": key}

    def uploaded_object(self, key):
        return self.stored.get(key)

    def submit(self, **kwargs):
        self.submitted.append(kwargs["object_key"])
        return super().submit(**kwargs)


def _submit_upload(client, headers):
    created = rpc(
        client,
        headers,
        "tools/call",
        {
            "name": "submit_meeting",
            "arguments": {"object_key": "", "upload_complete": False, "filename": "call.m4a", "media_type": "audio/mp4", "byte_size": 10},
            "task": {},
        },
    )
    return created["result"]["task"]["taskId"]


def _answer(client, headers, record, content):
    return client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": record.elicitation_id, "result": {"action": "accept", "content": content}},
    )


def test_portal_upload_gets_a_signed_target_and_only_the_issued_stored_key_is_analysed():
    port = _UploadPort()
    app = create_app(auth_bypass=False, port=port, verifier=MapVerifier({"alpha": "subject-a"}), environ={})
    with TestClient(app) as client:
        alpha = open_session(client, "alpha")
        task_id = _submit_upload(client, alpha)
        record = app.state.runtime.tasks.get(task_id, "subject-a")
        upload = record.elicitation_body["params"]["upload"]
        issued = f"uploads/{task_id}/call.m4a"
        assert upload["object_key"] == issued and upload["method"] == "PUT"
        assert upload["headers"] == {"Content-Type": "audio/mp4"}

        # Not stored yet: the claim of completion is not trusted, the task asks again.
        first = record.elicitation_id
        assert _answer(client, alpha, record, {"object_key": issued, "upload_complete": True}).status_code == 202
        import time

        for _ in range(100):
            if record.elicitation_id != first:
                break
            time.sleep(0.02)
        assert record.status == "input_required" and record.elicitation_id != first

        # Stored, but the client names a different key: the issued key is analysed, not the echo.
        port.stored[issued] = {"size": 10, "content_type": "audio/mp4"}
        assert _answer(client, alpha, record, {"object_key": "derivatives/someone-else.mp4", "upload_complete": True}).status_code == 202
        meeting_id = _meeting_id(client, alpha, task_id)
        assert meeting_id
        assert port.submitted == [issued]


def test_a_non_media_upload_is_refused_before_any_target_is_issued():
    from quotient.worker.port import PortError

    class Refusing(_UploadPort):
        def upload_target(self, task_id, filename, media_type, byte_size):
            raise PortError("invalid", "Only audio or video recordings can be uploaded.")

    app = create_app(auth_bypass=False, port=Refusing(), verifier=MapVerifier({"alpha": "subject-a"}), environ={})
    with TestClient(app) as client:
        alpha = open_session(client, "alpha")
        task_id = _submit_upload(client, alpha)
        viewed = rpc(client, alpha, "tasks/get", {"taskId": task_id})
        assert viewed["result"]["status"] == "failed"


def _submit_with_context(client, headers, batch, purpose="Review the order service"):
    created = rpc(client, headers, "tools/call", {
        "name": "submit_meeting",
        "arguments": {"object_key": "derivatives/call.mp4", "upload_complete": True, "context_batch": batch, "purpose": purpose},
        "task": {},
    })
    return created["result"]["task"]["taskId"]


class _ContextOwningPort(MemoryPort):
    def __init__(self):
        super().__init__()
        self.batches = {"b1": "subject-a"}
        self.submitted = []

    def context_items(self, subject, batch_id):
        return [] if self.batches.get(batch_id) == subject else None

    def submit(self, **kwargs):
        self.submitted.append({key: kwargs.get(key) for key in ("context_batch", "purpose")})
        return super().submit(**kwargs)


def test_context_and_purpose_reach_the_port_for_the_batch_owner():
    port = _ContextOwningPort()
    app = create_app(auth_bypass=False, port=port, verifier=MapVerifier({"alpha": "subject-a"}), environ={})
    with TestClient(app) as client:
        alpha = open_session(client, "alpha")
        task_id = _submit_with_context(client, alpha, "b1")
        assert _meeting_id(client, alpha, task_id)
        assert port.submitted == [{"context_batch": "b1", "purpose": "Review the order service"}]


def test_an_unknown_or_foreign_context_batch_stops_the_submission_with_a_plain_message():
    port = _ContextOwningPort()
    app = create_app(auth_bypass=False, port=port, verifier=MapVerifier({"alpha": "subject-a", "beta": "subject-b"}), environ={})
    with TestClient(app) as client:
        for token, batch in (("alpha", "missing"), ("beta", "b1")):
            headers = open_session(client, token)
            task_id = _submit_with_context(client, headers, batch)
            viewed = rpc(client, headers, "tasks/get", {"taskId": task_id})["result"]
            assert viewed["status"] == "failed" and "context you added was not found" in viewed["statusMessage"]
        assert port.submitted == []  # nothing was started


def test_a_malformed_context_batch_or_purpose_is_rejected_up_front():
    app = create_app(auth_bypass=True, port=MemoryPort(), environ={})
    with TestClient(app) as client:
        headers = open_session(client)
        for arguments in ({"context_batch": "../x"}, {"context_batch": 5}, {"purpose": "x" * 2001}, {"purpose": 7}):
            created = rpc(client, headers, "tools/call", {"name": "submit_meeting", "arguments": {"object_key": "derivatives/a.mp4", "upload_complete": True, **arguments}, "task": {}})
            assert "error" in created and "task" not in created.get("result", {})  # refused before any task exists


def test_a_client_cannot_point_a_submission_at_another_requests_upload():
    app = create_app(auth_bypass=True, port=MemoryPort(), environ={})
    with TestClient(app) as client:
        headers = open_session(client)
        created = rpc(client, headers, "tools/call", {"name": "submit_meeting", "arguments": {"object_key": "uploads/someone-elses-task/rec.mp4", "upload_complete": True}, "task": {}})
        task_id = created["result"]["task"]["taskId"]
        viewed = rpc(client, headers, "tasks/get", {"taskId": task_id})["result"]
        assert viewed["status"] == "failed" and "does not belong" in viewed["statusMessage"]


def test_a_task_past_its_ttl_is_dropped_only_once_it_has_finished():
    from quotient.mcp.tasks import TaskBoard

    def make(status):
        return TaskRecord(task_id=status, auth_subject="s", session_id="x", status=status, status_message="", created_at="2020-01-01T00:00:00Z",
                          last_updated_at="2020-01-01T00:00:00Z", ttl_ms=1000, poll_interval_ms=1000, progress_token=None)

    store = TaskBoard()
    for status in ("working", "input_required", "completed", "failed", "cancelled"):
        store._items[status] = make(status)
    store._drop_expired_locked()
    assert sorted(store._items) == ["input_required", "working"]  # the live ones stay, however old


def test_a_context_file_name_loses_hidden_and_direction_override_characters():
    from quotient.mcp.tools import _prepare_context

    seen = []

    class Port:
        def prepare_context(self, subject, files):
            seen.extend(files)
            return {"batch_id": "b1", "uploads": []}

    hidden = "".join(chr(0xE0000 + ord(c)) for c in "x")
    _prepare_context({"files": [{"filename": f"notes‮gpj.md{hidden}\x00"}]}, "s", Port())
    assert seen[0]["filename"] == "notesgpj.md"
    try:
        _prepare_context({"files": [{"filename": "‮‭"}]}, "s", Port())
    except ValueError:
        pass
    else:
        raise AssertionError("a name that is only hidden characters must be refused")
