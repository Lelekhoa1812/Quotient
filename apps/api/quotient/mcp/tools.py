"""Motivation vs Logic

Motivation: The eight tools are the only meeting operations partners can call.
submit_meeting has to run as a task. Reads are read-only. Cancel is destructive.
Logic: TOOLS is the tools/list catalog. call_tool enforces taskSupport before
it touches arguments, then dispatches the read and edit tools. submit_meeting
is started by jobs.run_submit so this module does not contain a model loop.
"""

from __future__ import annotations

from collections.abc import Callable

from quotient.graph.gate import page_graph, project_meeting, summary
from quotient.mcp.errors import INVALID_PARAMS, METHOD_NOT_FOUND, error
from quotient.mcp.page import decode_cursor, encode_cursor
from quotient.mcp.tasks import tool_text
from quotient.worker.port import PortError

PAGE_SIZE = 50

_OBJECT = "object"


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": _OBJECT, "properties": properties, "required": required}


_MEETING = {"type": "string", "description": "Meeting id returned for this authorization context."}

TOOLS: list[dict] = [
    {
        "name": "submit_meeting",
        "title": "Submit meeting",
        "description": (
            "Start analysis of one uploaded media object already stored under an object key. "
            "Upload filenames are not speaker names or action owners. "
            "Call this tool as a task. Poll tasks/get with the same access token until the task "
            "reaches a terminal status, then read tasks/result. "
            "An incomplete upload moves the task to input_required."
        ),
        "inputSchema": _schema(
            {
                "object_key": {
                    "type": "string",
                    "description": "Object key of the uploaded media in the Quotient media bucket.",
                },
                "upload_complete": {
                    "type": "boolean",
                    "description": "False while the multipart upload is still open.",
                },
                "context_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional short proper nouns passed through to the worker as context. Not a transcript rewrite.",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "Optional retry key. The same key and authorization context return the same meeting.",
                },
                "filename": {
                    "type": "string",
                    "description": "Name of the file to upload. With an empty object_key the task returns a signed upload target.",
                },
                "media_type": {
                    "type": "string",
                    "description": "audio/* or video/* type of the file to upload.",
                },
                "byte_size": {"type": "integer", "description": "Size of the file to upload, in bytes."},
                "context_batch": {
                    "type": "string",
                    "description": "Optional batch id returned by prepare_context after its files were uploaded: reference material for the analysis.",
                },
                "purpose": {
                    "type": "string",
                    "description": "Optional, at most 2000 characters: what the meeting is about, in the person's words. Reference only.",
                },
            },
            ["object_key"],
        ),
        "execution": {"taskSupport": "required"},
        "annotations": {
            "title": "Submit meeting",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "prepare_context",
        "title": "Prepare context upload",
        "description": (
            "Reserve signed upload targets for reference material (design documents, slides, spreadsheets, notes) "
            "that the analysis may read: one entry per file, at most 20 files, 25 MB each, 100 MB in all. "
            "Upload each file with a PUT to its upload_url using the returned headers, then pass the returned "
            "batch_id to submit_meeting as context_batch. Reference only: it is never treated as what was said."
        ),
        "inputSchema": _schema(
            {
                "files": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string", "description": "File name including its extension."},
                            "media_type": {"type": "string", "description": "Content type the PUT will send."},
                            "byte_size": {"type": "integer", "description": "Size in bytes."},
                        },
                        "required": ["filename"],
                    },
                },
            },
            ["files"],
        ),
        "execution": {"taskSupport": "forbidden"},
        "annotations": {
            "title": "Prepare context upload",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "get_meeting",
        "title": "Get meeting",
        "description": (
            "Read status, prompt release, review-queue counts, and per-artifact status for one meeting "
            "in the caller's authorization context. Does not return transcript text or unpublished claim wording."
        ),
        "inputSchema": _schema({"meeting_id": _MEETING}, ["meeting_id"]),
        "execution": {"taskSupport": "forbidden"},
        "annotations": {
            "title": "Get meeting",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "read_graph",
        "title": "Read graph",
        "description": (
            "Read one page of the provenance graph: spans, claims, findings, synthesis, actions, "
            "disagreements, and omissions. Every dimension is findings, none_in_transcript, or not_evaluated. "
            "Shared dimensions, charts, and the joined raw_transcript are included on the first page only. "
            "Each span includes raw_text and text. raw_transcript.audio joins span raw_text in time order. "
            "raw_transcript.video joins Pegasus observation statements in time order. "
            "Citations include start_ms, end_ms, and a playback path. "
            "Unpublished claims may appear here; the brief resource is the published projection."
        ),
        "inputSchema": _schema(
            {
                "meeting_id": _MEETING,
                "cursor": {"type": "string", "description": "Opaque page cursor from a previous read_graph result."},
            },
            ["meeting_id"],
        ),
        "execution": {"taskSupport": "forbidden"},
        "annotations": {
            "title": "Read graph",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "read_span",
        "title": "Read span",
        "description": (
            "Read one span, including raw_text and text. raw_text is the audio transcription and stays "
            "in place. text is the synthesized transcript and can change when a person edits it."
        ),
        "inputSchema": _schema(
            {
                "meeting_id": _MEETING,
                "span_id": {"type": "string", "description": "Span id from the graph."},
            },
            ["meeting_id", "span_id"],
        ),
        "execution": {"taskSupport": "forbidden"},
        "annotations": {
            "title": "Read span",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "accept_action",
        "title": "Accept action",
        "description": (
            "Move one proposed action to accepted. Optional later override: the analysis run does not call this "
            "and does not wait on it. Accepted actions remain when analysis is regenerated. "
            "Does not assign an owner. A missing owner stays not stated."
        ),
        "inputSchema": _schema(
            {
                "meeting_id": _MEETING,
                "action_id": {"type": "string", "description": "Action id from the graph."},
            },
            ["meeting_id", "action_id"],
        ),
        "execution": {"taskSupport": "forbidden"},
        "annotations": {
            "title": "Accept action",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "revise_speaker",
        "title": "Revise speaker",
        "description": (
            "Set the speaker display on one span, or on every span that shares that span's speaker hypothesis. "
            "This updates the transcript presentation immediately; it does not rerun analysis. raw_text is unchanged."
        ),
        "inputSchema": _schema(
            {
                "meeting_id": _MEETING,
                "span_id": {"type": "string", "description": "Anchor span id."},
                "scope": {
                    "type": "string",
                    "enum": ["span", "hypothesis"],
                    "description": "span updates the anchor. hypothesis updates every span with the same hypothesis id.",
                },
                "display_name": {
                    "type": "string",
                    "description": "Human speaker label for the selected spans.",
                },
            },
            ["meeting_id", "span_id", "scope", "display_name"],
        ),
        "execution": {"taskSupport": "forbidden"},
        "annotations": {
            "title": "Revise speaker",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "merge_speakers",
        "title": "Merge speakers",
        "description": (
            "Merge two speaker voices into one everywhere. Every line of the other span's voice moves to the anchor "
            "span's voice and takes display_name. Use only when a person confirms they are the same speaker. "
            "This updates the transcript presentation immediately; it does not rerun analysis. raw_text is unchanged."
        ),
        "inputSchema": _schema(
            {
                "meeting_id": _MEETING,
                "span_id": {"type": "string", "description": "Anchor span; its voice is kept."},
                "other_span_id": {"type": "string", "description": "A span of the voice to fold into the anchor's voice."},
                "display_name": {"type": "string", "description": "Name for the merged voice."},
            },
            ["meeting_id", "span_id", "other_span_id", "display_name"],
        ),
        "execution": {"taskSupport": "forbidden"},
        "annotations": {
            "title": "Merge speakers",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "revise_text",
        "title": "Revise transcript text",
        "description": "Edit the synthesized text for one transcript span. The original raw_text is preserved; this edit does not rerun analysis.",
        "inputSchema": _schema({
            "meeting_id": _MEETING,
            "span_id": {"type": "string", "description": "Span to edit."},
            "text": {"type": "string", "description": "Corrected synthesized transcript text."},
        }, ["meeting_id", "span_id", "text"]),
        "execution": {"taskSupport": "forbidden"},
        "annotations": {"title": "Revise transcript text", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "cancel_meeting",
        "title": "Cancel meeting",
        "description": (
            "Cancel a meeting and its in-flight submission task. Destructive: the meeting will not be published. "
            "Requires the authorization context that created the meeting."
        ),
        "inputSchema": _schema({"meeting_id": _MEETING}, ["meeting_id"]),
        "execution": {"taskSupport": "forbidden"},
        "annotations": {
            "title": "Cancel meeting",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
]

_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def list_tools() -> dict:
    return {"tools": TOOLS}


def task_mode_error(name: str, params: dict, request_id: object) -> dict | None:
    tool = _BY_NAME.get(name)
    if tool is None:
        return error(INVALID_PARAMS, f"Unknown tool: {name}", request_id)
    support = tool["execution"]["taskSupport"]
    has_task = "task" in params and params.get("task") is not None
    if support == "required" and not has_task:
        return error(METHOD_NOT_FOUND, "Task augmentation required for this tool", request_id)
    if support == "forbidden" and has_task:
        return error(METHOD_NOT_FOUND, "Task augmentation is forbidden for this tool", request_id)
    if has_task and not isinstance(params.get("task"), dict):
        return error(INVALID_PARAMS, "task must be an object", request_id)
    return None


def call_immediate(name: str, arguments: dict, *, subject: str, port: object, request_id: object) -> dict:
    if not isinstance(arguments, dict):
        return error(INVALID_PARAMS, "arguments must be an object", request_id)
    handler = _HANDLERS.get(name)
    if handler is None:
        return error(INVALID_PARAMS, f"Unknown tool: {name}", request_id)
    try:
        payload = handler(arguments, subject, port)
    except PortError as exc:
        return {"jsonrpc": "2.0", "id": request_id, "result": tool_text({"error": exc.message}, is_error=True)}
    except ValueError as exc:
        return error(INVALID_PARAMS, str(exc), request_id)
    return {"jsonrpc": "2.0", "id": request_id, "result": tool_text(payload)}


def _handlers() -> dict[str, Callable]:
    return {
        "prepare_context": _prepare_context,
        "get_meeting": _get_meeting,
        "read_graph": _read_graph,
        "read_span": _read_span,
        "accept_action": _accept_action,
        "revise_speaker": _revise_speaker,
        "merge_speakers": _merge_speakers,
        "revise_text": _revise_text,
        "cancel_meeting": _cancel_meeting,
    }


def _owned(port: object, meeting_id: str, subject: str) -> dict:
    raw = port.meeting(meeting_id, subject)  # type: ignore[attr-defined]
    if raw is None:
        raise PortError("not_found", "Meeting not found.")
    return raw


def _prepare_context(arguments: dict, subject: str, port: object) -> dict:
    files = arguments.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 20:
        raise ValueError("files must be a list of 1 to 20 entries")
    clean = []
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("filename"), str) or not entry["filename"].strip() or len(entry["filename"]) > 200:
            raise ValueError("each file needs a filename of at most 200 characters")
        media = entry.get("media_type")
        size = entry.get("byte_size")
        if media is not None and (not isinstance(media, str) or len(media) > 127):
            raise ValueError("media_type must be a short string")
        if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
            raise ValueError("byte_size must be a non-negative integer")
        clean.append({"filename": entry["filename"].strip(), "media_type": media, "byte_size": size})
    prepare = getattr(port, "prepare_context", None)
    if not callable(prepare):
        raise PortError("unavailable", "Context uploads need object storage, which is not configured.")
    result = prepare(subject, clean)
    if result is None:
        raise PortError("unavailable", "Context uploads need object storage, which is not configured.")
    return result


def _get_meeting(arguments: dict, subject: str, port: object) -> dict:
    meeting_id = _required_id(arguments, "meeting_id")
    return summary(project_meeting(_owned(port, meeting_id, subject)))


def _read_graph(arguments: dict, subject: str, port: object) -> dict:
    meeting_id = _required_id(arguments, "meeting_id")
    offset = _optional_cursor(arguments.get("cursor"))
    projected = project_meeting(_owned(port, meeting_id, subject))
    paged, next_offset = page_graph(projected["graph"], offset, PAGE_SIZE)
    if next_offset is not None:
        paged["nextCursor"] = encode_cursor(next_offset)
    return paged


def _read_span(arguments: dict, subject: str, port: object) -> dict:
    meeting_id = _required_id(arguments, "meeting_id")
    span_id = _required_text(arguments, "span_id")
    projected = project_meeting(_owned(port, meeting_id, subject))
    for span in projected["graph"]["spans"]:
        if span.get("span_id") == span_id:
            return span
    raise PortError("not_found", "Span not found.")


def _accept_action(arguments: dict, subject: str, port: object) -> dict:
    meeting_id = _required_id(arguments, "meeting_id")
    action_id = _required_text(arguments, "action_id")
    raw = port.accept_action(meeting_id, subject, action_id)  # type: ignore[attr-defined]
    projected = project_meeting(raw)
    for action in projected["graph"]["actions"]:
        if action.get("action_id") == action_id:
            return action
    raise PortError("not_found", "Action not found.")


def _revise_speaker(arguments: dict, subject: str, port: object) -> dict:
    meeting_id = _required_id(arguments, "meeting_id")
    span_id = _required_text(arguments, "span_id")
    scope = arguments.get("scope")
    if scope not in {"span", "hypothesis"}:
        raise ValueError("scope must be span or hypothesis")
    display_name = _required_text(arguments, "display_name")
    if len(display_name) > 128:
        raise ValueError("display_name is too long")
    raw = port.revise_speaker(meeting_id, subject, span_id, scope, display_name)  # type: ignore[attr-defined]
    projected = project_meeting(raw)
    return summary(projected)


def _merge_speakers(arguments: dict, subject: str, port: object) -> dict:
    meeting_id = _required_id(arguments, "meeting_id")
    span_id = _required_text(arguments, "span_id")
    other_span_id = _required_text(arguments, "other_span_id")
    display_name = _required_text(arguments, "display_name")
    if len(display_name) > 128:
        raise ValueError("display_name is too long")
    raw = port.merge_speakers(meeting_id, subject, span_id, other_span_id, display_name)  # type: ignore[attr-defined]
    return summary(project_meeting(raw))


def _revise_text(arguments: dict, subject: str, port: object) -> dict:
    meeting_id = _required_id(arguments, "meeting_id")
    span_id = _required_text(arguments, "span_id")
    text = arguments.get("text")
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if len(text) > 20_000:
        raise ValueError("text is too long")
    raw = port.revise_text(meeting_id, subject, span_id, text)  # type: ignore[attr-defined]
    projected = project_meeting(raw)
    for span in projected["graph"]["spans"]:
        if span.get("span_id") == span_id:
            return span
    raise PortError("not_found", "Span not found.")


def _cancel_meeting(arguments: dict, subject: str, port: object) -> dict:
    meeting_id = _required_id(arguments, "meeting_id")
    raw = port.cancel(meeting_id, subject)  # type: ignore[attr-defined]
    return summary(project_meeting(raw))


def _required_id(arguments: dict, key: str) -> str:
    value = _required_text(arguments, key)
    if len(value) > 128 or not all(char.isalnum() or char in "_-" for char in value):
        raise ValueError(f"{key} is not a meeting identifier")
    return value


def _required_text(arguments: dict, key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _optional_cursor(cursor: object) -> int:
    if cursor is None:
        return 0
    decoded = decode_cursor(cursor, None)
    if isinstance(decoded, dict):
        raise ValueError("Invalid cursor")
    return decoded


def validate_submit_arguments(arguments: dict) -> str | None:
    key = arguments.get("object_key")
    if not isinstance(key, str):
        return "object_key is required"
    if "upload_complete" in arguments and not isinstance(arguments.get("upload_complete"), bool):
        return "upload_complete must be a boolean"
    names = arguments.get("context_names", [])
    if names is None:
        names = []
    if not isinstance(names, list) or len(names) > 32:
        return "context_names must be a list of at most 32 strings"
    for name in names:
        if not isinstance(name, str) or len(name) > 64 or not name.strip():
            return "context_names entries must be short strings"
    batch = arguments.get("context_batch")
    if batch is not None and (not isinstance(batch, str) or not 1 <= len(batch) <= 64 or not all(c.isalnum() or c in "_-" for c in batch)):
        return "context_batch is not a batch id"
    purpose = arguments.get("purpose")
    if purpose is not None and (not isinstance(purpose, str) or len(purpose) > 2000):
        return "purpose must be text of at most 2000 characters"
    idem = arguments.get("idempotency_key")
    if idem is not None:
        if not isinstance(idem, str) or len(idem) > 128:
            return "idempotency_key must be a string"
        if not all(char.isalnum() or char in "_-." for char in idem):
            return "idempotency_key has unsupported characters"
    if key.strip() and not _safe_object_key(key.strip()):
        return "object_key is not a storage key"
    return None


def upload_incomplete(arguments: dict) -> bool:
    key = arguments.get("object_key")
    if not isinstance(key, str):
        return False
    if not key.strip():
        return True
    return arguments.get("upload_complete") is False


def _safe_object_key(value: str) -> bool:
    if len(value) > 1024 or ".." in value or "\\" in value or value.startswith("/"):
        return False
    return all(32 < ord(char) < 127 for char in value)


_HANDLERS = _handlers()
