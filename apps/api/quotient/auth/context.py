"""Motivation vs Logic

Motivation: Every task and meeting is visible only inside the authorization
context that created it. Local development still needs a principal when Cognito
is not wired, and that path must stay off unless a flag says otherwise.
Logic: AuthContext is a frozen subject/client/scope triple. RejectingVerifier
accepts no bearer token. local_context is used only after the bypass flag passes
the environment guard in the HTTP layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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
    """Stub resource-server check. Cognito JWKS validation is not performed."""

    def verify(self, token: str) -> AuthContext | None:
        del token
        return None
