"""GET /v1/jobs/{id}/graph returns spans, speakers, screens, and times."""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from quotient.app import create_app
from quotient.auth.context import RejectingVerifier
from quotient.public.jobs import JobBoard
from quotient.public.keys import MemoryDirectory
from quotient.worker.memory import MemoryPort


def _stack():
    port = MemoryPort()
    directory = MemoryDirectory()
    board = JobBoard(port, poll_seconds=0.05)
    app = create_app(
        auth_bypass=False,
        verifier=RejectingVerifier(),
        port=port,
        directory=directory,
        board=board,
        environ={},
    )
    return app, port


def _token(client: TestClient) -> str:
    response = client.post("/v1/keys")
    assert response.status_code == 201, response.text
    return response.json()["key"]["token"]


def test_graph_route_returns_spans_speakers_screens_and_times():
    app, port = _stack()
    with TestClient(app, client=("127.0.0.1", 9)) as local, TestClient(app) as remote:
        token = _token(local)
        created = remote.post(
            "/v1/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "media": {"object_key": "uploads/demo/call.mp4"},
                "outputs": {"transcript": True},
                "stream": False,
            },
        )
        assert created.status_code == 202
        job_id = created.json()["job_id"]
        submitted = remote.post(
            f"/v1/jobs/{job_id}/submit",
            headers={"Authorization": f"Bearer {token}"},
            json={"upload_complete": True},
        )
        assert submitted.status_code == 200
        meeting_id = submitted.json()["meeting_id"]
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
                        "speaker_hypothesis_id": "spk_1",
                    }
                ],
                "screens": [
                    {
                        "id": "sc1",
                        "kind": "slide",
                        "title": "Friday",
                        "text": "Ship Friday",
                        "details": "",
                        "start_ms": 100,
                        "end_ms": 400,
                    }
                ],
                "identities": {"spk_1": {"name": "Ada", "source": "audio", "confidence": 0.8}},
                "observations": [{"statement": "A slide says Friday.", "start_ms": 100, "end_ms": 400}],
            },
        )
        denied = remote.get(f"/v1/jobs/{job_id}/graph")
        assert denied.status_code == 401
        response = remote.get(f"/v1/jobs/{job_id}/graph", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["spans"][0]["span_id"] == "s1"
        assert body["spans"][0]["speaker_hypothesis_id"] == "spk_1"
        assert body["speakers"][0]["speaker_hypothesis_id"] == "spk_1"
        assert body["speakers"][0]["name"] == "Ada"
        assert body["screens"][0]["id"] == "sc1"
        assert body["screens"][0]["start_ms"] == 100
        assert {"id": "s1", "kind": "speech", "start_ms": 0, "end_ms": 1200} in body["times"]
        assert {"id": "sc1", "kind": "screen", "start_ms": 100, "end_ms": 400} in body["times"]
        encoded = json.dumps(body)
        assert "X-Amz-" not in encoded
        assert "https://" not in encoded
        assert "playback" not in body
        assert "url" not in body
