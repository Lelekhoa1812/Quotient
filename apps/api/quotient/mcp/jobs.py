"""Motivation vs Logic

Motivation: submit_meeting returns a task and then waits on the worker port.
An incomplete upload has to pause in input_required until the client sends the
completed object key. The API must not run the claim and entailment loop.
Logic: The coroutine calls WorkerPort.submit, polls meeting status, and emits
progress plus tasks/status notifications on the session. ready and needs_review
both complete the task. The analysis poll does not enter input_required.
input_required is only the incomplete-upload elicitation.
"""

from __future__ import annotations

import asyncio
import secrets

from quotient.graph.gate import project_meeting, summary
from quotient.mcp.errors import RELATED_TASK
from quotient.mcp.tasks import TaskRecord, tool_error, tool_text
from quotient.mcp.tools import upload_incomplete, validate_submit_arguments
from quotient.worker.port import PortError

_POLL_SECONDS = 0.25
_ELICIT_ATTEMPTS = 3


async def run_submit(task: TaskRecord, arguments: dict, runtime: object) -> None:
    try:
        problem = validate_submit_arguments(arguments)
        if problem and not upload_incomplete(arguments):
            task.fail_tool(problem)
            _notify_status(task, runtime)
            return
        if upload_incomplete(arguments):
            supplied = await _collect_upload(task, runtime, arguments)
            if supplied is None:
                return
            arguments = {**arguments, **supplied}
            problem = validate_submit_arguments(arguments)
            if problem:
                task.fail_tool(problem)
                _notify_status(task, runtime)
                return
        key = str(arguments.get("object_key") or "").strip()
        if key.startswith("uploads/") and not key.startswith(f"uploads/{task.task_id}/"):
            # A browser upload is only ever analysed under the key the server issued to this very task.
            task.fail_tool("That upload does not belong to this request.")
            _notify_status(task, runtime)
            return
        batch = arguments.get("context_batch")
        # With an idempotency key the port decides: a retry of a request that already ran must return its
        # meeting even though that request consumed the batch.
        if isinstance(batch, str) and batch and not arguments.get("idempotency_key"):
            known = getattr(runtime.port, "context_items", None)  # type: ignore[attr-defined]
            if not callable(known) or known(task.auth_subject, batch) is None:
                task.fail_tool("The context you added was not found. Add it again and start the analysis.")
                _notify_status(task, runtime)
                return
        _progress(task, runtime, 1, "Recording the meeting.")
        extra = {}
        if isinstance(batch, str) and batch:
            extra["context_batch"] = batch
        if isinstance(arguments.get("purpose"), str) and arguments["purpose"].strip():
            extra["purpose"] = arguments["purpose"].strip()
        meeting_id = runtime.port.submit(  # type: ignore[attr-defined]
            subject=task.auth_subject,
            object_key=str(arguments.get("object_key")).strip(),
            context_names=_names(arguments.get("context_names")),
            idempotency_key=arguments.get("idempotency_key"),
            **extra,
        )
        task.meeting_id = meeting_id
        task.touch(f"Meeting {meeting_id} is queued.")
        _notify_status(task, runtime)
        notify_resources(runtime, task.auth_subject, meeting_id)
        while not task.terminal():
            if _sync(task, runtime):
                _notify_status(task, runtime)
                notify_resources(runtime, task.auth_subject, meeting_id)
                return
            await asyncio.sleep(_POLL_SECONDS)
    except asyncio.CancelledError:
        raise
    except PortError as exc:
        task.fail_tool(exc.message)
        _notify_status(task, runtime)
    except Exception:
        task.fail_tool("Meeting submission failed.")
        _notify_status(task, runtime)


def sync_task(task: TaskRecord, runtime: object) -> None:
    if task.meeting_id and task.status == "working":
        if _sync(task, runtime):
            _notify_status(task, runtime)
            notify_resources(runtime, task.auth_subject, task.meeting_id)


def cancel_meeting_tasks(runtime: object, subject: str, meeting_id: str) -> None:
    for record in runtime.tasks.for_meeting(subject, meeting_id):  # type: ignore[attr-defined]
        if not record.terminal():
            record.mark_cancelled("The meeting was cancelled.")
            _notify_status(record, runtime)


def _sync(task: TaskRecord, runtime: object) -> bool:
    raw = runtime.port.meeting(task.meeting_id, task.auth_subject)  # type: ignore[attr-defined]
    if raw is None:
        task.fail_tool("Meeting not found.")
        return True
    projected = project_meeting(raw)
    phase = raw.get("progress_message") if isinstance(raw.get("progress_message"), str) else None
    message = phase or f"Meeting {task.meeting_id} is {projected['status']}."
    status = projected["stored_status"]
    if status in {"queued", "working"} and projected["status"] in {"queued", "working"}:
        _progress(task, runtime, 2, message)
        return False
    task.touch(message)
    if projected["status"] in {"ready", "needs_review"}:
        _progress(task, runtime, 3, task.status_message)
        task.complete_tool(tool_text(summary(projected)))
        return True
    if status == "cancelled" or projected["status"] == "cancelled":
        task.mark_cancelled("The meeting was cancelled.")
        return True
    if status == "failed":
        task.fail_tool(projected.get("failure_message") or "Meeting failed.")
        return True
    return False


async def _collect_upload(task: TaskRecord, runtime: object, arguments: dict | None = None) -> dict | None:
    """Pause in input_required until the upload is stored.

    Bugs vs Fixes
    Bug: The elicitation carried no upload target, so a browser had nowhere to send the
    file, and the server accepted any object key the client echoed back.
    Fix: When the worker port can sign uploads, the elicitation carries a signed PUT for a
    key the server minted (uploads/<task_id>/<name>). Completion is accepted only for that
    key and only once the stored object exists and is not empty. Without object storage
    (CLI use) the previous contract stands: the client names a completed key.
    """
    arguments = arguments or {}
    port = runtime.port  # type: ignore[attr-defined]
    target = None
    signer = getattr(port, "upload_target", None)
    if callable(signer):
        try:
            target = signer(task.task_id, arguments.get("filename"), arguments.get("media_type"), arguments.get("byte_size"))
        except PortError as exc:
            task.fail_tool(exc.message)
            _notify_status(task, runtime)
            return None
    for _attempt in range(_ELICIT_ATTEMPTS):
        if task.terminal():
            return None
        body = _elicitation(task.task_id, target)
        future = task.mark_input_required("Waiting for the recording to upload.", body)
        _notify_status(task, runtime)
        _fanout(runtime, task.session_id, body)
        try:
            response = await asyncio.wait_for(future, timeout=task.ttl_ms / 1000)
        except TimeoutError:
            task.fail_tool("Timed out waiting for the upload.")
            _notify_status(task, runtime)
            return None
        if task.terminal():
            return None
        if not isinstance(response, dict) or response.get("action") != "accept":
            task.fail_tool("Upload was not completed.")
            _notify_status(task, runtime)
            return None
        content = response.get("content") if isinstance(response.get("content"), dict) else {}
        complete = content.get("upload_complete") is True
        if target is not None:
            if not complete:
                continue
            stored = _stored(port, target["object_key"])
            if stored is None or stored.get("size", 0) <= 0:
                continue
            key = target["object_key"]
            task.mark_working("Upload received.")
            _notify_status(task, runtime)
            return {"object_key": key, "upload_complete": True}
        key = content.get("object_key")
        if isinstance(key, str) and key.strip() and complete:
            task.mark_working("Upload received.")
            _notify_status(task, runtime)
            return {"object_key": key.strip(), "upload_complete": True}
    task.fail_tool("Upload was not completed.")
    _notify_status(task, runtime)
    return None


def _stored(port: object, key: str) -> dict | None:
    probe = getattr(port, "uploaded_object", None)
    if not callable(probe):
        return {"size": 1}
    try:
        return probe(key)
    except Exception:
        return None


def _elicitation(task_id: str, target: dict | None = None) -> dict:
    params: dict = {
        "_meta": {RELATED_TASK: {"taskId": task_id}},
        "mode": "form",
        "message": "The media upload is incomplete. Send the completed object key to continue.",
        "requestedSchema": {
            "type": "object",
            "properties": {
                "object_key": {
                    "type": "string",
                    "description": "Object key of the completed upload.",
                },
                "upload_complete": {
                    "type": "boolean",
                    "description": "True only when the object is fully stored.",
                },
            },
            "required": ["object_key", "upload_complete"],
        },
    }
    if target is not None:
        params["message"] = "Upload the recording to the signed URL, then confirm."
        params["upload"] = dict(target)
    return {
        "jsonrpc": "2.0",
        "id": secrets.token_urlsafe(12),
        "method": "elicitation/create",
        "params": params,
    }


def _names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _progress(task: TaskRecord, runtime: object, progress: int, message: str) -> None:
    if progress < task.progress:
        return
    if progress == task.progress and task.status_message == message:
        return
    task.progress = progress
    task.touch(message)
    if task.progress_token is None:
        return
    _fanout(
        runtime,
        task.session_id,
        {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {
                "_meta": {RELATED_TASK: {"taskId": task.task_id}},
                "progressToken": task.progress_token,
                "progress": progress,
                "total": 3,
                "message": message,
            },
        },
    )


def _notify_status(task: TaskRecord, runtime: object) -> None:
    _fanout(
        runtime,
        task.session_id,
        {"jsonrpc": "2.0", "method": "notifications/tasks/status", "params": task.public()},
    )


def notify_resources(runtime: object, subject: str, meeting_id: str) -> None:
    from quotient.mcp.resources import meeting_uris

    uris = meeting_uris(meeting_id)
    for session in runtime.sessions.for_subject(subject):  # type: ignore[attr-defined]
        session.enqueue({"jsonrpc": "2.0", "method": "notifications/resources/list_changed"})
        for uri in session.subscriptions:
            if uri in uris:
                session.enqueue(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/resources/updated",
                        "params": {"uri": uri},
                    }
                )


def _fanout(runtime: object, session_id: str, message: dict) -> None:
    session = runtime.sessions.get(session_id)  # type: ignore[attr-defined]
    if session is not None:
        session.enqueue(message)


def resolve_client_response(runtime: object, subject: str, message: dict) -> None:
    request_id = message.get("id")
    if not isinstance(request_id, str):
        return
    record = runtime.tasks.for_elicitation(subject, request_id)  # type: ignore[attr-defined]
    if record is None:
        return
    future = record.input_future
    if future is None or future.done():
        return
    if "error" in message:
        future.set_result({"action": "cancel"})
    else:
        result = message.get("result")
        future.set_result(result if isinstance(result, dict) else {"action": "cancel"})
