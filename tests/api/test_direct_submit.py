"""Tests for direct and task-augmented submit_meeting invocations."""

import json
from starlette.testclient import TestClient
from quotient.app import create_app
from quotient.worker.memory import MemoryPort
from conftest import open_session, rpc


class _StoragePort(MemoryPort):
    def upload_target(self, task_id, filename, media_type, byte_size):
        return {
            "upload_url": f"https://s3.example.com/uploads/{task_id}/{filename}",
            "method": "PUT",
            "headers": {"Content-Type": media_type or "video/mp4"},
            "object_key": f"uploads/{task_id}/{filename}",
        }


def test_submit_meeting_direct_upload_target():
    app = create_app(auth_bypass=True, port=_StoragePort(), environ={})
    with TestClient(app) as client:
        headers = open_session(client)
        call = rpc(
            client,
            headers,
            "tools/call",
            {
                "name": "submit_meeting",
                "arguments": {"filename": "meeting.mp4", "media_type": "video/mp4"},
            },
        )
        assert "result" in call
        content = call["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data["status"] == "upload_target_issued"
        assert "upload_url" in data
        assert "object_key" in data
        assert data["object_key"].startswith("uploads/")


def test_submit_meeting_direct_submit():
    port = MemoryPort()
    app = create_app(auth_bypass=True, port=port, environ={})
    with TestClient(app) as client:
        headers = open_session(client)
        call = rpc(
            client,
            headers,
            "tools/call",
            {
                "name": "submit_meeting",
                "arguments": {
                    "object_key": "derivatives/meeting.mp4",
                    "upload_complete": True,
                },
            },
        )
        assert "result" in call
        content = call["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data["status"] == "submitted"
        assert "meeting_id" in data


def test_submit_meeting_task_augmented_backwards_compatible():
    port = MemoryPort()
    app = create_app(auth_bypass=True, port=port, environ={})
    with TestClient(app) as client:
        headers = open_session(client)
        call = rpc(
            client,
            headers,
            "tools/call",
            {
                "name": "submit_meeting",
                "arguments": {
                    "object_key": "derivatives/meeting.mp4",
                    "upload_complete": True,
                },
                "task": {"ttl": 3600000},
            },
        )
        assert "result" in call
        assert "task" in call["result"]
        assert "taskId" in call["result"]["task"]
