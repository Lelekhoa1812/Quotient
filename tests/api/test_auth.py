"""Authorization metadata and the default-off local bypass."""

import time
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from quotient import SCOPE
from quotient.auth.context import CognitoVerifier
from quotient.app import create_app
from quotient.worker.memory import MemoryPort

from conftest import base_headers


ISSUER = "https://cognito-idp.ap-southeast-2.amazonaws.com/ap-southeast-2_test"
RESOURCE = "https://quotient.example.com/mcp"
CLIENT_ID = "test-client"


class StaticJwks:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, token):
        del token
        return SimpleNamespace(key=self.key)


def signed_token(private_key, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "user-123",
        "client_id": CLIENT_ID,
        "token_use": "access",
        "iat": now,
        "exp": now + 300,
        "scope": SCOPE,
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "key-1"})


def verifier(public_key):
    return CognitoVerifier(
        issuer=ISSUER,
        resource_url=RESOURCE,
        client_ids=frozenset({CLIENT_ID}),
        jwks_client=StaticJwks(public_key),
    )


def test_cognito_access_token_signature_and_scope_are_verified():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = signed_token(private_key)
    context = verifier(private_key.public_key()).verify(token)
    assert context is not None
    assert context.subject == "user-123"
    assert context.client_id == CLIENT_ID
    assert context.allows(SCOPE)


def test_cognito_verifier_rejects_bad_signature_wrong_audience_and_id_token():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    check = verifier(private_key.public_key())
    assert check.verify(signed_token(other_key)) is None
    assert check.verify(signed_token(private_key, aud="https://other.example/mcp")) is None
    assert check.verify(signed_token(private_key, token_use="id")) is None


def test_cognito_verifier_binds_access_token_to_client_when_audience_is_absent():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = signed_token(private_key, client_id="unlisted-client")
    assert verifier(private_key.public_key()).verify(token) is None


def test_cognito_verifier_accepts_resource_audience_without_client_allowlist():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    check = CognitoVerifier(
        issuer=ISSUER,
        resource_url=RESOURCE,
        jwks_client=StaticJwks(private_key.public_key()),
    )
    context = check.verify(signed_token(private_key, aud=RESOURCE))
    assert context is not None


def test_cognito_verifier_rejects_unconfigured_issuer():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    check = CognitoVerifier(
        issuer="https://cognito-idp.ap-southeast-2.amazonaws.com/unconfigured",
        resource_url=RESOURCE,
        jwks_client=StaticJwks(private_key.public_key()),
    )
    assert check.verify(signed_token(private_key)) is None


def test_cognito_verifier_rejects_expired_and_oversized_tokens():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    check = verifier(private_key.public_key())
    assert check.verify(signed_token(private_key, exp=int(time.time()) - 60)) is None
    assert check.verify("x" * 16_385) is None


def test_staging_cognito_environment_wires_resource_and_client_validation():
    app = create_app(
        port=MemoryPort(),
        environ={
            "QUOTIENT_ENVIRONMENT": "staging",
            "MCP_RESOURCE_URL": RESOURCE,
            "COGNITO_ISSUER": ISSUER,
            "COGNITO_CLIENT_ID": CLIENT_ID,
        },
    )
    check = app.state.runtime.verifier
    assert isinstance(check, CognitoVerifier)
    assert check.issuer == ISSUER
    assert check.resource_url == RESOURCE
    assert check.client_ids == frozenset({CLIENT_ID})


def test_mcp_authorization_accepts_verified_scope_and_rejects_missing_scope():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = create_app(
        verifier=verifier(private_key.public_key()),
        port=MemoryPort(),
        environ={"QUOTIENT_RESOURCE_URL": RESOURCE},
    )
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    with TestClient(app) as client:
        accepted = client.post(
            "/mcp",
            headers={**base_headers(), "Authorization": f"Bearer {signed_token(private_key)}"},
            json=initialize,
        )
        denied = client.post(
            "/mcp",
            headers={
                **base_headers(),
                "Authorization": f'Bearer {signed_token(private_key, scope="openid")}',
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
        )
    assert accepted.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["error"] == "insufficient_scope"


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


def test_bypass_flag_without_a_local_environment_fails_closed():
    for environ in ({"QUOTIENT_AUTH_BYPASS": "1"}, {"QUOTIENT_AUTH_BYPASS": "1", "QUOTIENT_ENVIRONMENT": "prod"}):
        app = create_app(port=MemoryPort(), environ=environ)
        with TestClient(app) as client:
            denied = client.post(
                "/mcp",
                headers=base_headers(),
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
        assert denied.status_code == 401, environ


def test_explicit_bypass_flag_from_env():
    app = create_app(
        port=MemoryPort(),
        environ={"QUOTIENT_AUTH_BYPASS": "1", "QUOTIENT_ENVIRONMENT": "local"},
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


def test_an_oversized_request_body_is_rejected_without_being_buffered():
    app = create_app(auth_bypass=True, port=MemoryPort(), environ={"QUOTIENT_ENVIRONMENT": "local"})
    with TestClient(app) as client:
        by_header = client.post("/mcp", headers=base_headers(), content=b"x" * 2_000_000)
        assert by_header.status_code == 413

        def chunks():  # no Content-Length: the stream itself must be capped
            for _ in range(40):
                yield b"y" * 100_000

        streamed = client.post("/mcp", headers=base_headers(), content=chunks())
        assert streamed.status_code == 413
        ok = client.post(
            "/mcp",
            headers=base_headers(),
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        )
        assert ok.status_code == 200


def test_the_session_store_is_bounded():
    from quotient.auth.context import AuthContext
    from quotient.mcp import session as sessions

    store = sessions.SessionStore()
    auth = AuthContext(subject="s", scopes=frozenset(), client_id="c")
    first = store.create(auth)
    for _ in range(sessions.MAX_SESSIONS + 5):
        store.create(auth)
    assert len(store._items) == sessions.MAX_SESSIONS
    assert store.get(first.session_id) is None and first.closed
