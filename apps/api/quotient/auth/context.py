"""Cognito access-token verification and the explicitly local auth context."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Any
from urllib.error import URLError
from typing import Protocol

import jwt
from jwt import PyJWKClient, PyJWKClientError
from jwt.exceptions import PyJWTError

from quotient import SCOPE

LOCAL_SUBJECT = "local-dev"
LOCAL_CLIENT = "quotient-local-bypass"


@dataclass(frozen=True)
class AuthContext:
    subject: str
    client_id: str
    scopes: frozenset[str]

    def allows(self, scope: str) -> bool:
        return scope in self.scopes


def local_context() -> AuthContext:
    return AuthContext(
        subject=LOCAL_SUBJECT,
        client_id=LOCAL_CLIENT,
        scopes=frozenset({SCOPE}),
    )


class TokenVerifier(Protocol):
    def verify(self, token: str) -> AuthContext | None:
        """Return a context for a signature-checked access token, or None."""


class RejectingVerifier:
    """Explicit deny-all verifier for unconfigured environments and tests."""

    def verify(self, token: str) -> AuthContext | None:
        del token
        return None


class CognitoVerifier:
    """Verify Cognito RS256 access tokens against the configured resource.

    Access tokens without an ``aud`` claim must identify an explicitly allowed
    app client. Tokens with ``aud`` must target this MCP resource exactly.
    """

    def __init__(
        self,
        *,
        issuer: str,
        resource_url: str,
        client_ids: frozenset[str] = frozenset(),
        jwks_client: Any | None = None,
        leeway_seconds: int = 30,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.resource_url = resource_url
        self.client_ids = client_ids
        self._jwks_client = jwks_client
        self.leeway_seconds = leeway_seconds

    @cached_property
    def jwks_client(self) -> PyJWKClient | Any:
        if self._jwks_client is not None:
            return self._jwks_client
        return PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json",
            cache_jwk_set=True,
            lifespan=300,
            timeout=3,
        )

    def verify(self, token: str) -> AuthContext | None:
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 16_384
            or not self.issuer.startswith("https://")
            or self.issuer.endswith("/unconfigured")
        ):
            return None
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                return None
            key = self.jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.issuer,
                leeway=self.leeway_seconds,
                options={
                    "verify_aud": False,
                    "require": ["iss", "sub", "exp", "iat", "token_use"],
                },
            )
        except (PyJWTError, PyJWKClientError, URLError, TimeoutError, OSError, ValueError):
            return None

        if claims.get("token_use") != "access":
            return None
        subject = claims.get("sub")
        client_id = claims.get("client_id")
        audience = claims.get("aud")
        if not isinstance(subject, str) or not subject or not isinstance(client_id, str) or not client_id:
            return None
        if audience is not None:
            audiences = audience if isinstance(audience, list) else [audience]
            if self.resource_url not in audiences:
                return None
        elif client_id not in self.client_ids:
            return None
        scope_claim = claims.get("scope", "")
        if not isinstance(scope_claim, str):
            return None
        return AuthContext(subject=subject, client_id=client_id, scopes=frozenset(scope_claim.split()))
