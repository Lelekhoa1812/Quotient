"""Shared HTTP helpers for the Quotient MCP contract tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from quotient import PROTOCOL_VERSION, SCOPE  # noqa: E402
from quotient.auth.context import AuthContext  # noqa: E402

ACCEPT = "application/json, text/event-stream"


def base_headers(token: str | None = None) -> dict[str, str]:
    headers = {"Accept": ACCEPT, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def open_session(client, token: str | None = None) -> dict[str, str]:
    headers = base_headers(token)
    response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tasks": {"list": {}, "cancel": {}, "requests": {"tools": {"call": {}}}}
                },
                "clientInfo": {"name": "quotient-contract", "version": "0.0.0"},
            },
        },
    )
    assert response.status_code == 200, response.text
    headers["MCP-Session-Id"] = response.headers["mcp-session-id"]
    headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
    note = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert note.status_code == 202, note.text
    return headers


def rpc(client, headers: dict[str, str], method: str, params: dict | None = None, req_id: int = 1) -> dict:
    payload: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    response = client.post("/mcp", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


class MapVerifier:
    def __init__(self, subjects: dict[str, str]) -> None:
        self.subjects = subjects

    def verify(self, token: str) -> AuthContext | None:
        subject = self.subjects.get(token)
        if subject is None:
            return None
        return AuthContext(subject=subject, client_id="test", scopes=frozenset({SCOPE}))


def published_graph(meeting_id: str) -> dict:
    text = "Ship the report by Friday."
    return {
        "spans": [
            {
                "span_id": "s1",
                "meeting_id": meeting_id,
                "kind": "speech",
                "start_ms": 1000,
                "end_ms": 4000,
                "raw_text": text,
                "text": text,
                "coarse": False,
                "overlap": False,
                "speaker_hypothesis_id": "h1",
            }
        ],
        "claims": [
            {
                "claim_id": "c1",
                "kind": "decision",
                "status": "supported",
                "text": "The group will ship the report by Friday.",
                "origin": "model",
                "citations": [
                    {
                        "quote": text,
                        "span_id": "s1",
                        "relation": "entails",
                        "char_start": 0,
                        "char_end": len(text),
                        "start_ms": 1000,
                        "end_ms": 4000,
                    }
                ],
            }
        ],
        "findings": [
            {
                "finding_id": "f1",
                "dimension": "decision",
                "stance": "supports",
                "text": "The group decided to ship the report by Friday.",
                "claim_ids": ["c1"],
            }
        ],
        "synthesis": [
            {
                "sentence_id": "y1",
                "text": "The group decided to ship the report by Friday.",
                "finding_ids": ["f1"],
            }
        ],
        "actions": [
            {
                "action_id": "a1",
                "statement": "Ship the report by Friday.",
                "owner": "Alex",
                "owner_span_id": None,
                "agreement_span_id": "s1",
                "due_kind": "relative",
                "due_surface": "by Friday",
                "due_date": "2026-10-09",
                "anchor_date": None,
                "claim_ids": ["c1"],
                "origin": "model",
                "acceptance": "proposed",
            }
        ],
        "disagreements": [],
        "omissions": [],
    }
