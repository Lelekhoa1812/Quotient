"""MCP audit lines name the call and omit arguments."""

import json
import sys
from pathlib import Path

from starlette.testclient import TestClient

from quotient.app import create_app
from quotient.worker.memory import MemoryPort

from conftest import open_session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "worker"))


def test_mcp_audit_records_method_and_tool_name(monkeypatch, tmp_path):
    path = tmp_path / "audit.log"
    monkeypatch.setenv("QUOTIENT_AUDIT_LOG", str(path))
    app = create_app(auth_bypass=True, port=MemoryPort(), environ={})
    marker = "secret-meeting-marker"
    with TestClient(app) as client:
        headers = open_session(client)
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "read_graph", "arguments": {"meeting_id": marker}},
            },
        )
    assert response.status_code == 200
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    initialize = next(event for event in events if event.get("rpc") == "initialize")
    call = next(event for event in events if event.get("rpc") == "tools/call")
    assert initialize["service"] == "api"
    assert initialize["operation"] == "mcp"
    assert initialize["path"] == "/mcp"
    assert call["name"] == "read_graph"
    assert call["status"] == 200
    text = path.read_text(encoding="utf-8")
    assert marker not in text
    assert "authorization" not in text
