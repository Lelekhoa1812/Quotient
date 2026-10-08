"""Motivation vs Logic

Motivation: Partners reach Quotient only through MCP Streamable HTTP. Tasks,
tools, resources, and prompts share one authorization context per session.
Logic: POST /mcp accepts one JSON-RPC message. Initialize issues MCP-Session-Id.
Later calls require that header and MCP-Protocol-Version 2025-11-25. Long
submit_meeting work is a background task; the HTTP handler returns CreateTaskResult
immediately. GET /mcp carries server notifications.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from quotient import PROTOCOL_VERSION, SCOPE, SERVER_NAME, SERVER_TITLE, SERVER_VERSION
from quotient.auth.context import AuthContext, local_context
from quotient.mcp.errors import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    error,
    result,
)
from quotient.mcp.jobs import (
    cancel_meeting_tasks,
    notify_resources,
    resolve_client_response,
    run_submit,
    sync_task,
)
from quotient.mcp.page import decode_cursor, encode_cursor
from quotient.mcp.prompts import get_prompt, list_prompts
from quotient.mcp.resources import list_resources, list_templates, read_resource, reject_cursor, subscribe, unsubscribe
from quotient.mcp.session import Session
from quotient.mcp.tasks import LimitError, clamp_ttl, missing_task
from quotient.mcp.tools import (
    TOOLS,
    call_immediate,
    list_tools,
    task_mode_error,
    upload_incomplete,
    validate_submit_arguments,
)

_MAX_BODY = 1_000_000
_TASK_PAGE = 50
_INSTRUCTIONS = (
    "Quotient analyzes one meeting at a time through MCP tools. "
    "Call submit_meeting as a task. Read the brief resource for published findings. "
    "Leave the review queue out of any answer. Quotient does not provide model credentials."
)


# Motivation vs Logic
# Motivation: --logs needs the MCP method and tool name, not the meeting payload.
# Logic: After the handler returns, append status and timing when the audit path is set.
async def _audit_http(request: Request, response: Response, started: float, *, operation: str) -> None:
    if not os.environ.get("QUOTIENT_AUDIT_LOG"):
        return
    fields: dict[str, object] = {
        "http_method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "ms": int((time.perf_counter() - started) * 1000),
    }
    if request.method == "POST":
        try:
            payload = json.loads(await request.body() or b"null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        if isinstance(payload, dict):
            rpc = payload.get("method")
            if isinstance(rpc, str):
                fields["rpc"] = rpc
            params = payload.get("params")
            if isinstance(params, dict) and isinstance(params.get("name"), str):
                fields["name"] = params["name"]
    try:
        from audit import record
    except ImportError:
        return
    record("api", operation, **fields)


def mcp_routes(runtime: object) -> list:
    from starlette.routing import Route

    async def endpoint(request: Request) -> Response:
        if request.method == "OPTIONS":
            return _cors(request, runtime, Response(status_code=204))
        started = time.perf_counter()
        if request.method == "GET":
            response = _cors(request, runtime, await _get(request, runtime))
        elif request.method == "DELETE":
            response = _cors(request, runtime, await _delete(request, runtime))
        elif request.method == "POST":
            response = _cors(request, runtime, await _post(request, runtime))
        else:
            response = _cors(request, runtime, Response(status_code=405))
        await _audit_http(request, response, started, operation="mcp")
        return response

    async def metadata(request: Request) -> Response:
        if request.method == "OPTIONS":
            return _cors(request, runtime, Response(status_code=204))
        started = time.perf_counter()
        response = _cors(
            request,
            runtime,
            JSONResponse(runtime.settings.document()),  # type: ignore[attr-defined]
        )
        await _audit_http(request, response, started, operation="metadata")
        return response

    return [
        Route("/mcp", endpoint=endpoint, methods=["POST", "GET", "DELETE", "OPTIONS"]),
        Route("/.well-known/oauth-protected-resource", endpoint=metadata, methods=["GET", "OPTIONS"]),
        Route(
            "/.well-known/oauth-protected-resource/mcp",
            endpoint=metadata,
            methods=["GET", "OPTIONS"],
        ),
    ]


async def _post(request: Request, runtime: object) -> Response:
    auth = _authorize(request, runtime)
    if isinstance(auth, Response):
        return auth
    origin = _origin(request, runtime)
    if origin is not None:
        return origin
    accepted = _accepts(request.headers.get("accept"), both=True)
    if accepted is not None:
        return accepted
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("application/json"):
        return _json(error(INVALID_REQUEST, "Content-Type must be application/json", None), status=400)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > _MAX_BODY:
        return _json(error(INVALID_REQUEST, "Request body is too large", None), status=413)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_BODY:  # stop reading; do not buffer an unbounded upload
            return _json(error(INVALID_REQUEST, "Request body is too large", None), status=413)
    body = bytes(body)
    request._body = body  # later request.body() calls (audit, parsing) read the same bytes
    if len(body) > _MAX_BODY:
        return _json(error(INVALID_REQUEST, "Request body is too large", None), status=400)
    try:
        payload = json.loads(body or b"null")
    except json.JSONDecodeError:
        return _json(error(PARSE_ERROR, "Parse error", None), status=400)
    if isinstance(payload, list):
        return _json(error(INVALID_REQUEST, "JSON-RPC batches are not supported", None), status=400)
    kind = _classify(payload)
    if kind == "invalid":
        return _json(error(INVALID_REQUEST, "Invalid request", None), status=400)
    if kind == "request" and payload.get("method") == "initialize":
        return await _initialize(payload, auth, runtime)
    session_error = _session(request, runtime, auth)
    if isinstance(session_error, Response):
        return session_error
    session = session_error
    if kind == "response":
        resolve_client_response(runtime, auth.subject, payload)
        return _empty(session)
    if kind == "notification":
        if payload.get("method") == "notifications/initialized":
            session.ready = True
        return _empty(session)
    if not session.ready and payload.get("method") != "ping":
        return _json(error(INVALID_REQUEST, "Server session is not initialized", payload.get("id")), session=session)
    await asyncio.sleep(0)
    try:
        message = await _dispatch(payload, session, runtime)
    except Exception:
        message = error(INTERNAL_ERROR, "Internal error", payload.get("id"))
    if message is None:
        return _empty(session)
    if payload.get("method") == "tasks/result" and message.get("__sse__"):
        return _sse_response(message["events"], session)
    return _json(message, session=session)


async def _get(request: Request, runtime: object) -> Response:
    auth = _authorize(request, runtime)
    if isinstance(auth, Response):
        return auth
    origin = _origin(request, runtime)
    if origin is not None:
        return origin
    accepted = _accepts(request.headers.get("accept"), both=False)
    if accepted is not None:
        return accepted
    session = _session(request, runtime, auth)
    if isinstance(session, Response):
        return session
    last_raw = request.headers.get("last-event-id")
    try:
        cursor = int(last_raw) if last_raw else 0
    except ValueError:
        cursor = 0

    async def generate() -> AsyncIterator[bytes]:
        queue = session.add_waiter()
        seen = cursor
        try:
            yield b": connected\n\n"
            while not session.closed:
                for event_id, message in session.since(seen):
                    seen = event_id
                    yield _frame(event_id, message)
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield b": keepalive\n\n"
                    continue
                if item is None:
                    break
                event_id, message = item
                if event_id <= seen:
                    continue
                seen = event_id
                yield _frame(event_id, message)
        finally:
            session.remove_waiter(queue)

    return _sse_response(generate(), session)


async def _delete(request: Request, runtime: object) -> Response:
    auth = _authorize(request, runtime)
    if isinstance(auth, Response):
        return auth
    session = _session(request, runtime, auth)
    if isinstance(session, Response):
        return session
    runtime.sessions.drop(session.session_id)  # type: ignore[attr-defined]
    return Response(status_code=204, headers={"MCP-Protocol-Version": PROTOCOL_VERSION})


async def _initialize(payload: dict, auth: AuthContext, runtime: object) -> Response:
    params = payload.get("params")
    if not isinstance(params, dict) or not isinstance(params.get("clientInfo"), dict):
        return _json(error(INVALID_PARAMS, "initialize requires clientInfo", payload.get("id")))
    if "protocolVersion" not in params:
        return _json(error(INVALID_PARAMS, "protocolVersion is required", payload.get("id")))
    session = runtime.sessions.create(auth)  # type: ignore[attr-defined]
    body = result(
        payload.get("id"),
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": True, "listChanged": True},
                "prompts": {"listChanged": False},
                "tasks": {"list": {}, "cancel": {}, "requests": {"tools": {"call": {}}}},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "title": SERVER_TITLE,
                "version": SERVER_VERSION,
            },
            "instructions": _INSTRUCTIONS,
        },
    )
    return _json(body, session=session)


async def _dispatch(payload: dict, session: Session, runtime: object) -> dict | None:
    method = payload.get("method")
    request_id = payload.get("id")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    if method == "ping":
        return result(request_id, {})
    if method == "tools/list":
        rejected = reject_cursor(params.get("cursor"), request_id)
        if rejected:
            return rejected
        return result(request_id, list_tools())
    if method == "tools/call":
        return await _tools_call(params, request_id, session, runtime)
    if method == "resources/list":
        return list_resources(runtime.port, session.auth.subject, params.get("cursor"), request_id)  # type: ignore[attr-defined]
    if method == "resources/templates/list":
        rejected = reject_cursor(params.get("cursor"), request_id)
        if rejected:
            return rejected
        return result(request_id, list_templates())
    if method == "resources/read":
        return read_resource(runtime.port, session.auth.subject, params.get("uri"), request_id)  # type: ignore[attr-defined]
    if method == "resources/subscribe":
        return subscribe(runtime.port, session.auth.subject, params.get("uri"), session, request_id)  # type: ignore[attr-defined]
    if method == "resources/unsubscribe":
        return unsubscribe(params.get("uri"), session, request_id)
    if method == "prompts/list":
        rejected = reject_cursor(params.get("cursor"), request_id)
        if rejected:
            return rejected
        return result(request_id, list_prompts())
    if method == "prompts/get":
        found = get_prompt(params.get("name"), params.get("arguments"))
        if found is None:
            return error(INVALID_PARAMS, "Unknown prompt", request_id)
        return result(request_id, found)
    if method == "tasks/get":
        return _tasks_get(params, request_id, session, runtime)
    if method == "tasks/list":
        return _tasks_list(params, request_id, session, runtime)
    if method == "tasks/cancel":
        return _tasks_cancel(params, request_id, session, runtime)
    if method == "tasks/result":
        return await _tasks_result(params, request_id, session, runtime)
    return error(METHOD_NOT_FOUND, f"Method not found: {method}", request_id)


async def _tools_call(params: dict, request_id: object, session: Session, runtime: object) -> dict:
    name = params.get("name")
    if not isinstance(name, str) or name not in {tool["name"] for tool in TOOLS}:
        return error(INVALID_PARAMS, f"Unknown tool: {name}", request_id)
    mode = task_mode_error(name, params, request_id)
    if mode is not None:
        return mode
    if name == "submit_meeting":
        return await _submit(params, request_id, session, runtime)
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else params.get("arguments")
    message = call_immediate(
        name,
        arguments if isinstance(arguments, dict) else {},
        subject=session.auth.subject,
        port=runtime.port,  # type: ignore[attr-defined]
        request_id=request_id,
    )
    if name in {"accept_action", "revise_speaker", "cancel_meeting"}:
        if not (message.get("result") or {}).get("isError"):
            meeting_id = arguments.get("meeting_id") if isinstance(arguments, dict) else None
            if isinstance(meeting_id, str):
                notify_resources(runtime, session.auth.subject, meeting_id)
            if name == "cancel_meeting" and isinstance(meeting_id, str):
                cancel_meeting_tasks(runtime, session.auth.subject, meeting_id)
    return message


async def _submit(params: dict, request_id: object, session: Session, runtime: object) -> dict:
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return error(INVALID_PARAMS, "arguments must be an object", request_id)
    problem = validate_submit_arguments(arguments)
    if problem and not upload_incomplete(arguments):
        return error(INVALID_PARAMS, problem, request_id)
    token = _progress_token(params.get("_meta"))
    try:
        task = runtime.tasks.create(  # type: ignore[attr-defined]
            subject=session.auth.subject,
            session_id=session.session_id,
            ttl_ms=clamp_ttl((params.get("task") or {}).get("ttl")),
            progress_token=token,
        )
    except LimitError as exc:
        return error(INTERNAL_ERROR, str(exc), request_id)
    snapshot = task.public()
    job = asyncio.create_task(run_submit(task, arguments, runtime))
    runtime.background.add(job)  # type: ignore[attr-defined]
    job.add_done_callback(runtime.background.discard)  # type: ignore[attr-defined]
    await asyncio.sleep(0)
    return result(
        request_id,
        {
            "task": snapshot,
            "_meta": {
                "io.modelcontextprotocol/model-immediate-response": (
                    "Meeting submission is in progress. Poll tasks/get, then read tasks/result. "
                    "The brief stays withheld until the meeting status is ready."
                )
            },
        },
    )


def _tasks_get(params: dict, request_id: object, session: Session, runtime: object) -> dict:
    task = runtime.tasks.get(params.get("taskId"), session.auth.subject)  # type: ignore[attr-defined]
    if task is None:
        return missing_task(request_id)
    sync_task(task, runtime)
    return result(request_id, task.public())


def _tasks_list(params: dict, request_id: object, session: Session, runtime: object) -> dict:
    offset = decode_cursor(params.get("cursor"), request_id)
    if isinstance(offset, dict):
        return offset
    page, next_offset = runtime.tasks.list_for(session.auth.subject, offset, _TASK_PAGE)  # type: ignore[attr-defined]
    for task in page:
        sync_task(task, runtime)
    payload: dict = {"tasks": [task.public() for task in page]}
    if next_offset is not None:
        payload["nextCursor"] = encode_cursor(next_offset)
    return result(request_id, payload)


def _tasks_cancel(params: dict, request_id: object, session: Session, runtime: object) -> dict:
    task = runtime.tasks.get(params.get("taskId"), session.auth.subject)  # type: ignore[attr-defined]
    if task is None:
        return missing_task(request_id)
    if task.terminal():
        return error(INVALID_PARAMS, f"Cannot cancel task: already in terminal status '{task.status}'", request_id)
    task.mark_cancelled("The task was cancelled by request.")
    if task.meeting_id:
        try:
            runtime.port.cancel(task.meeting_id, session.auth.subject)  # type: ignore[attr-defined]
        except Exception:
            pass
        notify_resources(runtime, session.auth.subject, task.meeting_id)
    return result(request_id, task.public())


async def _tasks_result(params: dict, request_id: object, session: Session, runtime: object) -> dict:
    task = runtime.tasks.get(params.get("taskId"), session.auth.subject)  # type: ignore[attr-defined]
    if task is None:
        return missing_task(request_id)
    sync_task(task, runtime)
    if task.terminal():
        return task.result_message(request_id)

    async def events() -> AsyncIterator[bytes]:
        index = 1
        if task.status == "input_required" and task.elicitation_body is not None:
            yield _frame(index, task.elicitation_body)
            index += 1
        await task.done.wait()
        yield _frame(index, task.result_message(request_id))

    return {"__sse__": True, "events": events()}


def _authorize(request: Request, runtime: object) -> AuthContext | Response:
    settings = runtime.settings  # type: ignore[attr-defined]
    if settings.auth_bypass:
        return local_context()
    header = request.headers.get("authorization")
    token = _bearer(header)
    if token is None:
        return _unauthorized(settings, error_code=None)
    context = runtime.verifier.verify(token)  # type: ignore[attr-defined]
    if context is None:
        return _unauthorized(settings, error_code="invalid_token")
    if not context.allows(SCOPE):
        return JSONResponse(
            {"error": "insufficient_scope"},
            status_code=403,
            headers={"WWW-Authenticate": settings.challenge(error="insufficient_scope")},
        )
    return context


def _unauthorized(settings: object, *, error_code: str | None) -> JSONResponse:
    return JSONResponse(
        {"error": "unauthorized"},
        status_code=401,
        headers={"WWW-Authenticate": settings.challenge(error=error_code)},  # type: ignore[attr-defined]
    )


def _bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, rest = header.partition(" ")
    if scheme.lower() != "bearer" or not rest.strip():
        return None
    return rest.strip()


def _origin(request: Request, runtime: object) -> Response | None:
    origin = request.headers.get("origin")
    if origin is None:
        return None
    allowed = runtime.settings.allowed_origins  # type: ignore[attr-defined]
    if origin in allowed:
        return None
    return JSONResponse({"error": "origin_not_allowed"}, status_code=403)


def _session(request: Request, runtime: object, auth: AuthContext) -> Session | Response:
    header = request.headers.get("mcp-session-id")
    if not header:
        return _json(error(INVALID_REQUEST, "MCP-Session-Id header is required", None), status=400)
    version = request.headers.get("mcp-protocol-version")
    if version != PROTOCOL_VERSION:
        return _json(error(INVALID_REQUEST, "MCP-Protocol-Version must be 2025-11-25", None), status=400)
    session = runtime.sessions.get(header)  # type: ignore[attr-defined]
    if session is None:
        return _json(error(INVALID_REQUEST, "Session not found", None), status=404)
    if session.auth.subject != auth.subject:
        return JSONResponse(
            {"error": "insufficient_scope"},
            status_code=403,
            headers={"WWW-Authenticate": runtime.settings.challenge(error="insufficient_scope")},  # type: ignore[attr-defined]
        )
    return session


def _accepts(header: str | None, *, both: bool) -> Response | None:
    parts = set()
    if header:
        parts = {piece.split(";", 1)[0].strip().lower() for piece in header.split(",")}
    if both:
        ok = "application/json" in parts and "text/event-stream" in parts
    else:
        ok = "text/event-stream" in parts
    if ok:
        return None
    return _json(error(INVALID_REQUEST, "Accept must include the required media types", None), status=406)


def _classify(payload: object) -> str:
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return "invalid"
    if "method" in payload:
        return "notification" if "id" not in payload else "request"
    if "id" in payload and ("result" in payload or "error" in payload):
        return "response"
    return "invalid"


def _progress_token(meta: object) -> str | int | None:
    if not isinstance(meta, dict):
        return None
    token = meta.get("progressToken")
    if isinstance(token, bool) or not isinstance(token, (str, int)):
        return None
    return token


def _json(payload: dict, *, status: int = 200, session: Session | None = None) -> JSONResponse:
    headers = {"MCP-Protocol-Version": PROTOCOL_VERSION}
    if session is not None:
        headers["MCP-Session-Id"] = session.session_id
    return JSONResponse(payload, status_code=status, headers=headers)


def _empty(session: Session) -> Response:
    return Response(
        status_code=202,
        headers={
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "MCP-Session-Id": session.session_id,
        },
    )


def _sse_response(events: AsyncIterator[bytes], session: Session) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "MCP-Session-Id": session.session_id,
        },
    )


def _frame(event_id: int, message: dict) -> bytes:
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: message\ndata: {data}\n\n".encode()


def _cors(request: Request, runtime: object, response: Response) -> Response:
    origin = request.headers.get("origin")
    allowed = runtime.settings.allowed_origins  # type: ignore[attr-defined]
    if origin and origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, Accept, MCP-Protocol-Version, MCP-Session-Id, Last-Event-ID"
        )
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response.headers["Access-Control-Expose-Headers"] = "MCP-Session-Id, MCP-Protocol-Version"
        response.headers["Access-Control-Max-Age"] = "600"
    return response
