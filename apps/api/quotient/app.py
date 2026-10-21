"""Motivation vs Logic

Motivation: The process exposes one ASGI app: Streamable HTTP MCP, the
protected-resource metadata document, and the /v1 integration API. Staging
and production ignore the local auth bypass even if the flag is present.
Logic: create_app wires settings, the rejecting verifier, and either an injected
port or the worker loader. An injected port with no key table keeps the
integration key in memory so contract tests do not touch the local file. The
module-level app is built on first attribute access so tests can construct
isolated apps.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import asynccontextmanager

from starlette.applications import Starlette

from quotient.auth.context import CognitoVerifier, RejectingVerifier, TokenVerifier
from quotient.auth.metadata import load_auth_settings
from quotient.mcp.server import mcp_routes
from quotient.public.disk import Disk, default_path
from quotient.public.jobs import JobBoard, load_board
from quotient.public.keys import KeyDirectory, MemoryDirectory, load_directory
from quotient.public.routes import public_routes
from quotient.worker.port import WorkerPort, load_worker_port


def create_app(
    *,
    auth_bypass: bool | None = None,
    verifier: TokenVerifier | None = None,
    port: WorkerPort | None = None,
    directory: KeyDirectory | None = None,
    board: JobBoard | None = None,
    environ: Mapping[str, str] | None = None,
) -> Starlette:
    env = os.environ if environ is None else environ
    settings = load_auth_settings(env, auth_bypass=auth_bypass)
    resolved = port if port is not None else load_worker_port()
    disk = _disk(env, port is not None)
    if directory is None:
        directory = MemoryDirectory() if disk is None and _isolated(env, port is not None) else load_directory(env, disk)
    if board is None:
        board = JobBoard(resolved) if disk is None and _isolated(env, port is not None) else load_board(resolved, env, disk)
    runtime = _Runtime(
        settings=settings,
        port=resolved,
        verifier=verifier if verifier is not None else _load_verifier(env, settings),
        directory=directory,
        board=board,
        portal_token=(env.get("QUOTIENT_PORTAL_TOKEN") or "").strip(),
    )

    @asynccontextmanager
    async def lifespan(app: Starlette):
        del app
        runtime.board.fail_orphans()
        yield
        jobs = list(runtime.background)
        for job in jobs:
            job.cancel()
        if jobs:
            import asyncio

            await asyncio.gather(*jobs, return_exceptions=True)
        flush_fn = getattr(runtime.port, "flush_storage", None)
        if callable(flush_fn):
            flush_fn()

    app = Starlette(routes=[*mcp_routes(runtime), *public_routes(runtime)], lifespan=lifespan)
    app.state.runtime = runtime
    return app


class _Runtime:
    def __init__(
        self,
        *,
        settings,
        port: WorkerPort,
        verifier: TokenVerifier,
        directory: KeyDirectory,
        board: JobBoard | None,
        portal_token: str = "",
    ) -> None:
        from quotient.mcp.session import SessionStore
        from quotient.mcp.tasks import TaskBoard

        self.settings = settings
        self.port = port
        self.verifier = verifier
        self.directory = directory
        self.board = board
        self.portal_token = portal_token
        self.sessions = SessionStore()
        self.tasks = TaskBoard()
        self.background: set = set()


def _isolated(env: Mapping[str, str], explicit_port: bool) -> bool:
    """Contract tests inject a port and carry no table names. They must not open the local file."""

    return explicit_port and not (env.get("KEYS_TABLE") or "").strip() and not (env.get("JOBS_TABLE") or "").strip()


def _disk(env: Mapping[str, str], explicit_port: bool) -> Disk | None:
    if _isolated(env, explicit_port):
        return None
    if (env.get("KEYS_TABLE") or "").strip() and (env.get("JOBS_TABLE") or "").strip():
        return None
    return Disk(default_path())


def __getattr__(name: str):
    if name == "app":
        global _app
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)


_app = None


def _load_verifier(env: Mapping[str, str], settings) -> TokenVerifier:
    issuer = settings.authorization_server.rstrip("/")
    if not issuer.startswith("https://") or issuer.endswith("/unconfigured"):
        return RejectingVerifier()
    clients = frozenset(
        value.strip()
        for value in (
            env.get("QUOTIENT_OAUTH_CLIENT_IDS", "") or env.get("COGNITO_CLIENT_ID", "")
        ).split(",")
        if value.strip()
    )
    return CognitoVerifier(
        issuer=issuer,
        resource_url=settings.resource_url,
        client_ids=clients,
    )
