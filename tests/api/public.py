"""Integration key and /v1 job contract."""

from __future__ import annotations

import time

from starlette.testclient import TestClient

from conftest import base_headers
from quotient.app import create_app
from quotient.auth.context import RejectingVerifier
from quotient.public.jobs import JobBoard
from quotient.public.keys import MemoryDirectory
from quotient.worker.memory import MemoryPort
from quotient.worker.port import PortError


def _stack(port: MemoryPort | None = None, *, poll: float = 0.05, environ: dict | None = None):
    port = port or MemoryPort()
    directory = MemoryDirectory()
    board = JobBoard(port, poll_seconds=poll)
    app = create_app(
        auth_bypass=False,
        verifier=RejectingVerifier(),
        port=port,
        directory=directory,
        board=board,
        environ=environ or {},
    )
    return app, port, directory, board


def _token(client: TestClient) -> str:
    response = client.post("/v1/keys")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["scope"] == "local"
    assert body["key"]["revoked_at"] is None
    assert "expires" not in body["key"]
    return body["key"]["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _recording(**outputs) -> dict:
    body = {
        "media": {"object_key": "uploads/demo/call.mp4"},
        "outputs": outputs or {"transcript": True},
        "stream": False,
    }
    return body


def _finish(port: MemoryPort, meeting_id: str) -> None:
    port.settle(
        meeting_id,
        status="ready",
        prompt_release="meeting.digest.v1",
        graph={
            "spans": [
                {
                    "span_id": "s1",
                    "kind": "speech",
                    "raw_text": "We will ship on Friday.",
                    "text": "We will ship on Friday.",
                    "start_ms": 0,
                    "end_ms": 1200,
                }
            ],
            "observations": [{"statement": "A slide says Friday.", "start_ms": 100, "end_ms": 400}],
            "claims": [
                {
                    "claim_id": "c1",
                    "kind": "commitment",
                    "status": "supported",
                    "text": "Ship on Friday",
                    "origin": "model",
                    "citations": [
                        {
                            "span_id": "s1",
                            "quote": "We will ship on Friday.",
                            "start_ms": 0,
                            "end_ms": 1200,
                            "relation": "entails",
                        }
                    ],
                }
            ],
            "findings": [
                {
                    "finding_id": "f1",
                    "dimension": "commitment",
                    "stance": "supports",
                    "text": "The group will ship on Friday.",
                    "claim_ids": ["c1"],
                }
            ],
            "digest": {
                "title": "Friday ship",
                "content_type": "meeting",
                "summary": [{"text": "The group will ship on Friday.", "span_ids": ["s1"]}],
                "decisions": [{"statement": "Ship on Friday.", "span_ids": ["s1"]}],
                "actions": [{"task": "Ship the build.", "span_ids": ["s1"]}],
                "open_questions": [{"question": "Who ships?", "span_ids": ["s1"], "answered": False}],
            },
        },
    )


class _UploadPort(MemoryPort):
    def __init__(self) -> None:
        super().__init__()
        self.uploads = 0

    def upload_target(self, task_id, filename, media_type, byte_size):
        del task_id, filename, media_type, byte_size
        self.uploads += 1
        raise PortError("invalid", "Only audio or video recordings can be uploaded.")


def test_a_key_never_expires_and_a_revoked_key_is_rejected():
    app, _port, _directory, _board = _stack()
    with TestClient(app) as remote, TestClient(app, client=("127.0.0.1", 9)) as local:
        assert remote.post("/v1/keys").status_code == 403
        token = _token(local)
        again = local.get("/v1/keys")
        assert again.status_code == 200
        assert again.json()["key"]["token"] == token
        created = remote.post("/v1/jobs", headers=_auth(token), json=_recording())
        assert created.status_code == 202
        assert local.post("/v1/keys").status_code == 409
        revoked = local.post("/v1/keys/revoke")
        assert revoked.status_code == 200
        assert "token" not in revoked.json()["key"]
        assert revoked.json()["key"]["revoked_at"]
        assert remote.post("/v1/jobs", headers=_auth(token), json=_recording()).status_code == 401
        replacement = _token(local)
        assert replacement != token
        assert remote.post("/v1/jobs", headers=_auth(replacement), json=_recording()).status_code == 202


def test_another_key_cannot_read_the_job():
    app, _port, _directory, _board = _stack()
    with TestClient(app, client=("127.0.0.1", 9)) as local, TestClient(app) as remote:
        first = _token(local)
        created = remote.post("/v1/jobs", headers=_auth(first), json=_recording())
        job_id = created.json()["job_id"]
        assert local.post("/v1/keys/revoke").status_code == 200
        second = _token(local)
        assert remote.get(f"/v1/jobs/{job_id}", headers=_auth(second)).status_code == 404
        assert remote.get(f"/v1/jobs/{job_id}", headers=_auth(first)).status_code == 401


def test_a_bad_output_spec_is_rejected_before_an_upload_target():
    port = _UploadPort()
    app, _port, _directory, _board = _stack(port)
    with TestClient(app, client=("127.0.0.1", 9)) as local, TestClient(app) as remote:
        token = _token(local)
        response = remote.post(
            "/v1/jobs",
            headers=_auth(token),
            json={
                "media": {"filename": "call.mp4", "media_type": "video/mp4", "byte_size": 10},
                "outputs": {},
                "stream": False,
            },
        )
        assert response.status_code == 400
        assert port.uploads == 0


def test_context_may_be_omitted_and_sections_follow_the_spec():
    app, port, _directory, _board = _stack()
    with TestClient(app, client=("127.0.0.1", 9)) as local, TestClient(app) as remote:
        token = _token(local)
        created = remote.post(
            "/v1/jobs",
            headers=_auth(token),
            json={
                "media": {"object_key": "uploads/demo/call.mp4"},
                "outputs": {"transcript": True, "analysis": {"summary": True, "findings": True}},
                "stream": False,
            },
        )
        assert created.status_code == 202
        assert "context_uploads" not in created.json()
        job_id = created.json()["job_id"]
        started = remote.post(f"/v1/jobs/{job_id}/submit", headers=_auth(token), json={"upload_complete": True})
        assert started.status_code == 200
        meeting_id = started.json()["meeting_id"]
        _finish(port, meeting_id)
        transcript = remote.get(f"/v1/jobs/{job_id}/transcript", headers=_auth(token))
        assert transcript.status_code == 200
        assert transcript.json()["transcript"]["audio"] == "We will ship on Friday."
        assert transcript.json()["transcript"]["video"] == "A slide says Friday."
        assert "analysis" not in transcript.json()
        analysis = remote.get(f"/v1/jobs/{job_id}/analysis", headers=_auth(token))
        assert analysis.status_code == 200
        body = analysis.json()["analysis"]
        assert body["summary"][0]["text"] == "The group will ship on Friday."
        assert body["findings"][0]["finding_id"] == "f1"
        assert "decisions" not in body
        assert "actions" not in body
        both = remote.post(
            "/v1/jobs",
            headers=_auth(token),
            json={
                "media": {"object_key": "uploads/demo/other.mp4"},
                "outputs": {"transcript": True, "analysis": True},
                "stream": False,
            },
        )
        other = both.json()["job_id"]
        submitted = remote.post(f"/v1/jobs/{other}/submit", headers=_auth(token), json={"upload_complete": True})
        _finish(port, submitted.json()["meeting_id"])
        full = remote.get(f"/v1/jobs/{other}/analysis", headers=_auth(token)).json()["analysis"]
        assert full["decisions"][0]["statement"] == "Ship on Friday."
        assert full["actions"][0]["task"] == "Ship the build."
        assert full["questions"][0]["question"] == "Who ships?"


def test_transcript_only_hides_analysis():
    app, port, _directory, _board = _stack()
    with TestClient(app, client=("127.0.0.1", 9)) as local, TestClient(app) as remote:
        token = _token(local)
        created = remote.post("/v1/jobs", headers=_auth(token), json=_recording(transcript=True))
        job_id = created.json()["job_id"]
        started = remote.post(f"/v1/jobs/{job_id}/submit", headers=_auth(token), json={"upload_complete": True})
        _finish(port, started.json()["meeting_id"])
        assert remote.get(f"/v1/jobs/{job_id}/analysis", headers=_auth(token)).status_code == 404
        body = remote.get(f"/v1/jobs/{job_id}/transcript", headers=_auth(token)).json()
        assert "analysis" not in body
        assert "Friday" in body["transcript"]["audio"]


def test_stream_false_has_no_event_route_and_stream_true_emits_progress_then_result():
    app, port, _directory, _board = _stack()
    with TestClient(app, client=("127.0.0.1", 9)) as local, TestClient(app) as remote:
        token = _token(local)
        quiet = remote.post("/v1/jobs", headers=_auth(token), json=_recording())
        assert remote.get(f"/v1/jobs/{quiet.json()['job_id']}/events", headers=_auth(token)).status_code == 404
        created = remote.post(
            "/v1/jobs",
            headers=_auth(token),
            json={
                "media": {"object_key": "uploads/demo/live.mp4"},
                "outputs": {"transcript": True},
                "stream": True,
            },
        )
        job_id = created.json()["job_id"]
        assert created.json()["events_url"] == f"/v1/jobs/{job_id}/events"
        started = remote.post(f"/v1/jobs/{job_id}/submit", headers=_auth(token), json={"upload_complete": True})
        meeting_id = started.json()["meeting_id"]

        def settle() -> None:
            time.sleep(0.15)
            _finish(port, meeting_id)

        import threading

        threading.Thread(target=settle, daemon=True).start()
        with remote.stream("GET", f"/v1/jobs/{job_id}/events", headers=_auth(token)) as response:
            assert response.status_code == 200
            text = response.read().decode()
        assert "event: progress" in text
        assert "event: result" in text
        assert "We will ship on Friday." in text


def test_a_portal_token_reads_keys_from_a_remote_peer_and_a_wrong_token_does_not():
    app, _port, _directory, _board = _stack(environ={"QUOTIENT_PORTAL_TOKEN": "portal-secret"})
    with TestClient(app) as remote:
        assert remote.get("/v1/keys").status_code == 403
        assert remote.get("/v1/keys", headers={"X-Quotient-Portal": "nope"}).status_code == 403
        opened = remote.get("/v1/keys", headers={"X-Quotient-Portal": "portal-secret"})
        assert opened.status_code == 200, opened.text
        issued = remote.post("/v1/keys", headers={"X-Quotient-Portal": "portal-secret"})
        assert issued.status_code == 201, issued.text


def test_mcp_rejects_the_integration_key_and_health_stays_open():
    app, _port, _directory, _board = _stack()
    with TestClient(app, client=("127.0.0.1", 9)) as local, TestClient(app) as remote:
        token = _token(local)
        assert remote.get("/health").status_code == 200
        response = remote.post(
            "/mcp",
            headers=base_headers(token),
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert response.status_code == 401


def test_a_missing_meeting_fails_the_job_on_startup():
    port = MemoryPort()
    board = JobBoard(port)
    board._jobs["abc123"] = {
        "job_id": "abc123",
        "key_id": "k",
        "subject": "key:k",
        "status": "working",
        "meeting_id": "missing",
        "stream": False,
        "outputs": {"transcript": True, "analysis": []},
        "progress_message": "",
        "failure_message": None,
        "updated_at": "2020-01-01T00:00:00Z",
    }
    app = create_app(
        auth_bypass=False,
        verifier=RejectingVerifier(),
        port=port,
        directory=MemoryDirectory(),
        board=board,
        environ={},
    )
    with TestClient(app):
        pass
    assert board._jobs["abc123"]["status"] == "failed"
    assert "no longer on this server" in board._jobs["abc123"]["failure_message"]
