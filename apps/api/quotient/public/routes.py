"""Motivation vs Logic

Motivation: External apps need plain HTTP for a recording, a transcript, an
analysis, and the graph of spans, speakers, screens, and times. Streaming
can be turned off. The key that authorises them is minted only on this computer.
Logic: /v1/jobs requires the bearer key. /v1/keys accepts a loopback peer
or the portal token the settings route sends. stream true opens an event
stream with a 15 second comment heartbeat.
stream false answers 404 on that route. MCP routes are not part of this module.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from quotient.public.keys import KeyBusy, KeyMissing
from quotient.worker.port import PortError

_MAX_BODY = 1_000_000
_HEARTBEAT_SECONDS = 15.0
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def public_routes(runtime: object) -> list:
    from starlette.routing import Route

    async def keys_collection(request: Request) -> Response:
        if request.method == "OPTIONS":
            return _cors(Response(status_code=204))
        denied = _local_only(request, runtime)
        if denied is not None:
            return denied
        directory = runtime.directory  # type: ignore[attr-defined]
        if request.method == "GET":
            return _json(directory.view())
        try:
            row = directory.issue()
        except KeyBusy:
            return _error(409, "An API key is already active. Revoke it before generating another.")
        view = directory.view()
        view["key"] = {
            "key_id": row["key_id"],
            "token": row["token"],
            "created_at": row["created_at"],
            "revoked_at": None,
        }
        return _json(view, status=201)

    async def keys_revoke(request: Request) -> Response:
        if request.method == "OPTIONS":
            return _cors(Response(status_code=204))
        denied = _local_only(request, runtime)
        if denied is not None:
            return denied
        try:
            view = runtime.directory.revoke()  # type: ignore[attr-defined]
        except KeyMissing:
            return _error(404, "There is no active API key.")
        return _json(view)

    async def jobs_collection(request: Request) -> Response:
        if request.method == "OPTIONS":
            return _cors(Response(status_code=204))
        auth = _auth(request, runtime)
        if isinstance(auth, Response):
            return auth
        _key_id, subject = auth
        payload = await _body(request)
        if isinstance(payload, Response):
            return payload
        try:
            created = runtime.board.create(key_id=_key_id, subject=subject, body=payload)  # type: ignore[attr-defined]
        except ValueError as exc:
            return _error(400, str(exc))
        except PortError as exc:
            return _port(exc)
        return _json(created, status=202)

    async def job_item(request: Request) -> Response:
        if request.method == "OPTIONS":
            return _cors(Response(status_code=204))
        auth = _auth(request, runtime)
        if isinstance(auth, Response):
            return auth
        _key_id, subject = auth
        job_id = request.path_params["job_id"]
        try:
            if request.method == "DELETE":
                body = runtime.board.cancel(job_id, subject)  # type: ignore[attr-defined]
            else:
                body = runtime.board.sync(job_id, subject)  # type: ignore[attr-defined]
        except PortError as exc:
            return _port(exc)
        return _json(body)

    async def job_submit(request: Request) -> Response:
        if request.method == "OPTIONS":
            return _cors(Response(status_code=204))
        auth = _auth(request, runtime)
        if isinstance(auth, Response):
            return auth
        _key_id, subject = auth
        payload = await _body(request)
        if isinstance(payload, Response):
            return payload
        if payload.get("upload_complete") is not True:
            return _error(400, "upload_complete must be true.")
        try:
            body = runtime.board.submit(request.path_params["job_id"], subject)  # type: ignore[attr-defined]
        except PortError as exc:
            return _port(exc)
        return _json(body)

    async def job_events(request: Request) -> Response:
        if request.method == "OPTIONS":
            return _cors(Response(status_code=204))
        auth = _auth(request, runtime)
        if isinstance(auth, Response):
            return auth
        _key_id, subject = auth
        job_id = request.path_params["job_id"]
        row = runtime.board.owned_row(job_id, subject)  # type: ignore[attr-defined]
        if row is None:
            return _error(404, "Job not found.")
        if not row.get("stream"):
            return _error(404, "This job is not streaming. Poll the job instead.")
        board = runtime.board  # type: ignore[attr-defined]

        async def frames() -> AsyncIterator[bytes]:
            import asyncio
            import time

            seen = None
            heartbeat = time.monotonic()
            while True:
                try:
                    view = board.sync(job_id, subject)
                except PortError:
                    yield _event("result", {"job_id": job_id, "status": "failed", "failure_message": "Job not found."})
                    return
                message = view.get("progress_message") or view.get("status")
                if message != seen:
                    seen = message
                    yield _event("progress", {"job_id": job_id, "status": view.get("status"), "progress_message": view.get("progress_message") or ""})
                if view.get("status") in {"ready", "needs_review", "failed", "cancelled"}:
                    yield _event("result", _final(board, job_id, subject, view))
                    return
                now = time.monotonic()
                if now - heartbeat >= _HEARTBEAT_SECONDS:
                    heartbeat = now
                    yield b": keepalive\n\n"
                await asyncio.sleep(board.poll_seconds)

        return _cors(
            StreamingResponse(frames(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        )

    async def job_graph(request: Request) -> Response:
        if request.method == "OPTIONS":
            return _cors(Response(status_code=204))
        auth = _auth(request, runtime)
        if isinstance(auth, Response):
            return auth
        _key_id, subject = auth
        try:
            body = runtime.board.graph(request.path_params["job_id"], subject)  # type: ignore[attr-defined]
        except PortError as exc:
            return _port(exc)
        return _json(body)

    async def job_transcript(request: Request) -> Response:
        return await _product(request, runtime, "transcript")

    async def job_analysis(request: Request) -> Response:
        return await _product(request, runtime, "analysis")

    return [
        Route("/v1/keys", endpoint=keys_collection, methods=["GET", "POST", "OPTIONS"]),
        Route("/v1/keys/revoke", endpoint=keys_revoke, methods=["POST", "OPTIONS"]),
        Route("/v1/jobs", endpoint=jobs_collection, methods=["POST", "OPTIONS"]),
        Route("/v1/jobs/{job_id}", endpoint=job_item, methods=["GET", "DELETE", "OPTIONS"]),
        Route("/v1/jobs/{job_id}/submit", endpoint=job_submit, methods=["POST", "OPTIONS"]),
        Route("/v1/jobs/{job_id}/events", endpoint=job_events, methods=["GET", "OPTIONS"]),
        Route("/v1/jobs/{job_id}/graph", endpoint=job_graph, methods=["GET", "OPTIONS"]),
        Route("/v1/jobs/{job_id}/transcript", endpoint=job_transcript, methods=["GET", "OPTIONS"]),
        Route("/v1/jobs/{job_id}/analysis", endpoint=job_analysis, methods=["GET", "OPTIONS"]),
    ]


async def _product(request: Request, runtime: object, kind: str) -> Response:
    if request.method == "OPTIONS":
        return _cors(Response(status_code=204))
    auth = _auth(request, runtime)
    if isinstance(auth, Response):
        return auth
    _key_id, subject = auth
    try:
        body = runtime.board.result(request.path_params["job_id"], subject, kind)  # type: ignore[attr-defined]
    except PortError as exc:
        return _port(exc)
    return _json(body)


def _final(board: object, job_id: str, subject: str, view: dict) -> dict:
    status = view.get("status")
    if status in {"failed", "cancelled"}:
        return {"job_id": job_id, "status": status, "failure_message": view.get("failure_message") or view.get("progress_message") or ""}
    try:
        outputs = view.get("outputs") if isinstance(view.get("outputs"), dict) else {}
        payload: dict = {"job_id": job_id, "meeting_id": view.get("meeting_id"), "status": status}
        if outputs.get("transcript"):
            payload["transcript"] = board.result(job_id, subject, "transcript").get("transcript")  # type: ignore[attr-defined]
        if outputs.get("analysis"):
            payload["analysis"] = board.result(job_id, subject, "analysis").get("analysis")  # type: ignore[attr-defined]
        return payload
    except PortError:
        return {"job_id": job_id, "status": status}


def _auth(request: Request, runtime: object) -> tuple[str, str] | Response:
    token = _bearer(request.headers.get("authorization"))
    if token is None:
        return _error(401, "unauthorized")
    verified = runtime.directory.verify(token)  # type: ignore[attr-defined]
    if verified is None:
        return _error(401, "unauthorized")
    return verified


def _local_only(request: Request, runtime: object) -> Response | None:
    host = request.client.host if request.client else ""
    if host in _LOOPBACK or _portal_header(request, runtime):
        return None
    return _error(403, "API keys can be changed on this computer only.")


def _portal_header(request: Request, runtime: object) -> bool:
    # Bugs vs Fixes
    # Bug: Key admin compared the TCP peer to loopback. Behind the load
    # balancer that peer is the balancer, so Settings could not mint a key.
    # Fix: The portal route adds X-Quotient-Portal. Both sides are hashed so
    # a length mismatch still compares in constant time. An empty token never
    # matches, so a public caller without the header stays refused.
    expected = getattr(runtime, "portal_token", "") or ""
    supplied = request.headers.get("x-quotient-portal") or ""
    if not expected or not supplied:
        return False
    return hmac.compare_digest(
        hashlib.sha256(expected.encode()).digest(),
        hashlib.sha256(supplied.encode()).digest(),
    )


def _bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, rest = header.partition(" ")
    if scheme.lower() != "bearer" or not rest.strip():
        return None
    return rest.strip()


async def _body(request: Request) -> dict | Response:
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        return _error(413, "The request is too large.")
    try:
        payload = json.loads(raw or b"null")
    except (json.JSONDecodeError, UnicodeError):
        return _error(400, "The request could not be read.")
    if not isinstance(payload, dict):
        return _error(400, "The request could not be read.")
    return payload


def _port(exc: PortError) -> JSONResponse:
    status = {"invalid": 400, "not_found": 404, "conflict": 409, "unavailable": 503}.get(exc.code, 400)
    return _error(status, exc.message)


def _error(status: int, message: str) -> JSONResponse:
    return _json({"error": message}, status=status)


def _json(body: dict, status: int = 200) -> JSONResponse:
    return _cors(JSONResponse(body, status_code=status))


def _cors(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Max-Age"] = "600"
    return response


def _event(name: str, payload: dict) -> bytes:
    return f"event: {name}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()
