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

    def document(self) -> dict:
        return {
            "resource": self.resource_url,
            "authorization_servers": [self.authorization_server],
            "bearer_methods_supported": ["header"],
            "scopes_supported": [SCOPE],
            "resource_name": "Quotient",
        }

    def challenge(self, *, error: str | None = None) -> str:
        parts = [
            "Bearer",
            f'resource_metadata="{self.metadata_url}"',
            f'scope="{SCOPE}"',
        ]
        header = parts[0] + " " + ", ".join(parts[1:])
        if error:
            header += f', error="{error}"'
        return header


def _csv_origins(raw: str) -> frozenset[str]:
    return frozenset(piece.strip() for piece in raw.split(",") if piece.strip())


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
    resource = env.get("QUOTIENT_RESOURCE_URL", "").strip() or "http://127.0.0.1:8080/mcp"
    issuer = env.get("QUOTIENT_AUTHORIZATION_SERVER", "").strip()
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
    enabled = bypass_requested(env, auth_bypass) and not environment_locks_bypass(env)
    return AuthSettings(
        resource_url=resource,
        authorization_server=issuer,
        metadata_url=_metadata_url(resource),
        allowed_origins=origins,
        auth_bypass=enabled,
    )
