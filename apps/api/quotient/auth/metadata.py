"""Motivation vs Logic

Motivation: MCP HTTP authorization discovers the authorization server from
OAuth 2.0 Protected Resource Metadata (RFC 9728). Cognito is that server.
Logic: Build the metadata document and the WWW-Authenticate challenge from
configured issuer and resource URLs. This module does not exchange codes,
store client secrets, or read model credentials.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from quotient import SCOPE


@dataclass(frozen=True)
class AuthSettings:
    resource_url: str
    authorization_server: str
    metadata_url: str
    allowed_origins: frozenset[str]
    auth_bypass: bool
    # Bugs vs Fixes
    # Bug: The process always challenged quotient:meetings. Cognito issues the
    # resource-server scope quotient/mcp, so every staging access token was
    # insufficient_scope.
    # Fix: COGNITO_SCOPE, when set, is the scope in the metadata document, the
    # challenge, and the allow check. Unset keeps quotient:meetings.
    oauth_scope: str = SCOPE

    def document(self) -> dict:
        return {
            "resource": self.resource_url,
            "authorization_servers": [self.authorization_server],
            "bearer_methods_supported": ["header"],
            "scopes_supported": [self.oauth_scope],
            "resource_name": "Quotient",
        }

    def challenge(self, *, error: str | None = None) -> str:
        parts = [
            "Bearer",
            f'resource_metadata="{self.metadata_url}"',
            f'scope="{self.oauth_scope}"',
        ]
        header = parts[0] + " " + ", ".join(parts[1:])
        if error:
            header += f', error="{error}"'
        return header


def _csv_origins(raw: str) -> frozenset[str]:
    return frozenset(piece.strip() for piece in raw.split(",") if piece.strip())


def _resource_origin(resource_url: str) -> str:
    parts = urlsplit(resource_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def _metadata_url(resource_url: str) -> str:
    parts = urlsplit(resource_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    return origin + "/.well-known/oauth-protected-resource"


def bypass_requested(env: Mapping[str, str], explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    return env.get("QUOTIENT_AUTH_BYPASS", "").strip().lower() in {"1", "true", "yes"}


def environment_locks_bypass(env: Mapping[str, str]) -> bool:
    return env.get("QUOTIENT_ENVIRONMENT", "").strip().lower() in {"staging", "production"}


def load_auth_settings(env: Mapping[str, str], *, auth_bypass: bool | None) -> AuthSettings:
    resource = (
        env.get("QUOTIENT_RESOURCE_URL", "").strip()
        or env.get("MCP_RESOURCE_URL", "").strip()
        or "http://127.0.0.1:8080/mcp"
    )
    issuer = env.get("QUOTIENT_AUTHORIZATION_SERVER", "").strip() or env.get("COGNITO_ISSUER", "").strip()
    if not issuer:
        issuer = "https://cognito-idp.ap-southeast-2.amazonaws.com/unconfigured"
    origins = _csv_origins(env.get("QUOTIENT_ALLOWED_ORIGINS", ""))
    if not origins:
        origins = frozenset(
            {
                "http://127.0.0.1:3000",
                "http://localhost:3000",
                "http://127.0.0.1:8080",
                "http://localhost:8080",
            }
        )
    # Bugs vs Fixes
    # Bug: The browser on the load balancer sends Origin http://<alb>. That
    # origin was absent from the allow list, so a portal session died with
    # origin_not_allowed after authorization.
    # Fix: The resource URL's own origin is always allowed. Loopback defaults
    # stay in the set for the local portal.
    resource_origin = _resource_origin(resource)
    if resource_origin:
        origins = origins | frozenset({resource_origin})
    # Motivation vs Logic
    # Motivation: The bypass makes every caller the shared subject "local-dev". It was locked
    # only for staging and production, so an unset or misspelled QUOTIENT_ENVIRONMENT ("prod")
    # failed open.
    # Logic: The QUOTIENT_AUTH_BYPASS environment flag is honoured only when
    # QUOTIENT_ENVIRONMENT is exactly "local". An explicit auth_bypass=True argument (tests,
    # embedding code) still works except in staging and production.
    environment = env.get("QUOTIENT_ENVIRONMENT", "").strip().lower()
    if auth_bypass is None:
        enabled = bypass_requested(env, None) and environment == "local"
    else:
        enabled = bypass_requested(env, auth_bypass) and not environment_locks_bypass(env)
    enabled = enabled and not environment_locks_bypass(env)
    return AuthSettings(
        resource_url=resource,
        authorization_server=issuer,
        metadata_url=_metadata_url(resource),
        allowed_origins=origins,
        auth_bypass=enabled,
        oauth_scope=env.get("COGNITO_SCOPE", "").strip() or SCOPE,
    )
