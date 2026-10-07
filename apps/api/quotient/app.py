"""Motivation vs Logic

Motivation: The process exposes one ASGI app: Streamable HTTP MCP plus the
protected-resource metadata document. Staging and production ignore the local
auth bypass even if the flag is present.
Logic: create_app wires settings, the rejecting verifier, and either an injected
port or the worker loader. The module-level app is built on first attribute
access so tests can construct isolated apps.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import asynccontextmanager

from starlette.applications import Starlette

from quotient.auth.context import RejectingVerifier, TokenVerifier
from quotient.auth.metadata import load_auth_settings
from quotient.mcp.server import mcp_routes
from quotient.worker.port import WorkerPort, load_worker_port


def create_app(
    *,
    auth_bypass: bool | None = None,
    verifier: TokenVerifier | None = None,
    port: WorkerPort | None = None,
    environ: Mapping[str, str] | None = None,
) -> Starlette:
    env = os.environ if environ is None else environ
    settings = load_auth_settings(env, auth_bypass=auth_bypass)
    runtime = _Runtime(
        settings=settings,
        port=port if port is not None else load_worker_port(),
        verifier=verifier if verifier is not None else RejectingVerifier(),
    )

    @asynccontextmanager
    async def lifespan(app: Starlette):
        del app
        yield
        jobs = list(runtime.background)
        for job in jobs:
            job.cancel()
        if jobs:
            import asyncio

            await asyncio.gather(*jobs, return_exceptions=True)

    app = Starlette(routes=mcp_routes(runtime), lifespan=lifespan)
    app.state.runtime = runtime
    return app


class _Runtime:
    def __init__(self, *, settings, port: WorkerPort, verifier: TokenVerifier) -> None:
        from quotient.mcp.session import SessionStore
        from quotient.mcp.tasks import TaskBoard

        self.settings = settings
        self.port = port
        self.verifier = verifier
        self.sessions = SessionStore()
        self.tasks = TaskBoard()
        self.background: set = set()


def __getattr__(name: str):
    if name == "app":
        global _app
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)


_app = None
