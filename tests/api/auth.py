"""Authorization metadata and the default-off local bypass."""

from starlette.testclient import TestClient

from quotient.app import create_app
from quotient.worker.memory import MemoryPort

from conftest import base_headers


def test_bypass_off_by_default_and_metadata():
    app = create_app(auth_bypass=False, port=MemoryPort(), environ={})
    with TestClient(app) as client:
        denied = client.post(
            "/mcp",
            headers=base_headers(),
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        challenged = client.post(
            "/mcp",
            headers=base_headers("not-a-cognito-token"),
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        meta = client.get("/.well-known/oauth-protected-resource")
        nested = client.get("/.well-known/oauth-protected-resource/mcp")
    assert denied.status_code == 401
    assert "resource_metadata=" in denied.headers["www-authenticate"]
    assert "quotient:meetings" in denied.headers["www-authenticate"]
    assert challenged.status_code == 401
    assert 'error="invalid_token"' in challenged.headers["www-authenticate"]
    document = meta.json()
    assert document == nested.json()
    assert document["resource"].endswith("/mcp")
    assert document["bearer_methods_supported"] == ["header"]
    assert document["scopes_supported"] == ["quotient:meetings"]
    assert document["authorization_servers"] == [
        "https://cognito-idp.ap-southeast-2.amazonaws.com/unconfigured"
    ]
    assert "authorization_servers" in document
    assert len(document["authorization_servers"]) == 1


def test_staging_ignores_bypass_flag():
    app = create_app(
        auth_bypass=True,
        port=MemoryPort(),
        environ={"QUOTIENT_ENVIRONMENT": "staging", "QUOTIENT_AUTH_BYPASS": "1"},
    )
    with TestClient(app) as client:
        denied = client.post(
            "/mcp",
            headers=base_headers(),
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert denied.status_code == 401


def test_explicit_bypass_flag_from_env():
    app = create_app(
        port=MemoryPort(),
        environ={"QUOTIENT_AUTH_BYPASS": "1"},
    )
    with TestClient(app) as client:
        allowed = client.post(
            "/mcp",
            headers=base_headers(),
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "local", "version": "0"},
                },
            },
        )
    assert allowed.status_code == 200
