"""Motivation vs Logic

Motivation: Partners read the graph, the published brief, the review queue, and
export bytes through MCP resources. There is no meetings REST collection.
Logic: URIs under quotient://meetings/{id}/ are parsed structurally, projected
through the publish gate, and rendered by the export module. burned.mp4 is
returned only when the worker port supplies bytes.
"""

from __future__ import annotations

import base64

from quotient.export.project import EXPORTS, is_text, mime_for, render_local
from quotient.graph.gate import project_meeting
from quotient.mcp.errors import INVALID_PARAMS, RESOURCE_NOT_FOUND, error
from quotient.mcp.page import decode_cursor, encode_cursor
from quotient.worker.port import PortError

_PREFIX = "quotient://meetings/"
_PAGE = 50

TEMPLATES = [
    {
        "name": "meeting_graph",
        "title": "Meeting graph",
        "uriTemplate": "quotient://meetings/{id}/graph",
        "description": (
            "Provenance graph for one meeting, including raw_transcript, per-span raw_text and text, "
            "unpublished claims, and playback paths."
        ),
        "mimeType": "application/json",
    },
    {
        "name": "meeting_brief",
        "title": "Meeting brief",
        "uriTemplate": "quotient://meetings/{id}/brief",
        "description": "Published brief. Withheld unless the meeting status is ready. Unpublished claims are omitted.",
        "mimeType": "application/json",
    },
    {
        "name": "meeting_review",
        "title": "Meeting review",
        "uriTemplate": "quotient://meetings/{id}/review",
        "description": "Review queue of unpublished claims. This queue is not the brief.",
        "mimeType": "application/json",
    },
    {
        "name": "meeting_export",
        "title": "Meeting export",
        "uriTemplate": "quotient://meetings/{id}/exports/{name}",
        "description": (
            "One export artifact. Names: graph.json, brief.html, brief.pdf, actions.csv, "
            "actions.xlsx, captions.vtt, captions.srt, burned.mp4. "
            "burned.mp4 is present only after the worker renders it."
        ),
    },
]


def list_templates() -> dict:
    return {"resourceTemplates": TEMPLATES}


def list_resources(port: object, subject: str, cursor: object, request_id: object) -> dict:
    offset = decode_cursor(cursor, request_id)
    if isinstance(offset, dict):
        return offset
    uris = _uris(port, subject)
    page = uris[offset : offset + _PAGE]
    payload: dict = {"resources": page}
    if offset + _PAGE < len(uris):
        payload["nextCursor"] = encode_cursor(offset + _PAGE)
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def read_resource(port: object, subject: str, uri: object, request_id: object) -> dict:
    parsed = _parse(uri)
    if parsed is None:
        return error(RESOURCE_NOT_FOUND, "Resource not found", request_id)
    meeting_id, kind, name = parsed
    raw = port.meeting(meeting_id, subject)  # type: ignore[attr-defined]
    if raw is None:
        return error(RESOURCE_NOT_FOUND, "Resource not found", request_id)
    projected = project_meeting(raw)
    try:
        content = _content(uri, kind, name, projected, port, subject, meeting_id)
    except PortError:
        return error(RESOURCE_NOT_FOUND, "Resource not found", request_id)
    if content is None:
        return error(RESOURCE_NOT_FOUND, "Export is not ready", request_id)
    return {"jsonrpc": "2.0", "id": request_id, "result": {"contents": [content]}}


def subscribe(port: object, subject: str, uri: object, session: object, request_id: object) -> dict:
    parsed = _parse(uri)
    if parsed is None or not isinstance(uri, str):
        return error(RESOURCE_NOT_FOUND, "Resource not found", request_id)
    meeting_id, _kind, _name = parsed
    if port.meeting(meeting_id, subject) is None:  # type: ignore[attr-defined]
        return error(RESOURCE_NOT_FOUND, "Resource not found", request_id)
    session.subscriptions.add(uri)  # type: ignore[attr-defined]
    return {"jsonrpc": "2.0", "id": request_id, "result": {}}


def unsubscribe(uri: object, session: object, request_id: object) -> dict:
    if isinstance(uri, str):
        session.subscriptions.discard(uri)  # type: ignore[attr-defined]
    return {"jsonrpc": "2.0", "id": request_id, "result": {}}


def meeting_uris(meeting_id: str) -> list[str]:
    rows = [
        f"{_PREFIX}{meeting_id}/graph",
        f"{_PREFIX}{meeting_id}/brief",
        f"{_PREFIX}{meeting_id}/review",
    ]
    rows.extend(f"{_PREFIX}{meeting_id}/exports/{name}" for name, _mime in EXPORTS)
    return rows


def _uris(port: object, subject: str) -> list[dict]:
    resources = []
    for raw in port.list_meetings(subject):  # type: ignore[attr-defined]
        meeting_id = raw.get("meeting_id")
        if not isinstance(meeting_id, str):
            continue
        updated = raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else None
        for uri in meeting_uris(meeting_id):
            name = uri.rsplit("/", 1)[-1]
            mime = "application/json"
            if "/exports/" in uri:
                mime = mime_for(name) or "application/octet-stream"
            entry = {
                "uri": uri,
                "name": name,
                "mimeType": mime,
                "annotations": {"audience": ["user", "assistant"], "priority": 0.8},
            }
            if updated:
                entry["annotations"]["lastModified"] = updated
            resources.append(entry)
    return resources


def _parse(uri: object) -> tuple[str, str, str | None] | None:
    if not isinstance(uri, str) or not uri.startswith(_PREFIX):
        return None
    parts = uri[len(_PREFIX) :].split("/")
    if not parts or not _safe_id(parts[0]):
        return None
    if len(parts) == 2 and parts[1] in {"graph", "brief", "review"}:
        return parts[0], parts[1], None
    if len(parts) == 3 and parts[1] == "exports" and mime_for(parts[2]):
        return parts[0], "exports", parts[2]
    return None


def _safe_id(value: str) -> bool:
    return bool(value) and len(value) <= 128 and all(char.isalnum() or char in "_-" for char in value)


def _content(
    uri: str,
    kind: str,
    name: str | None,
    projected: dict,
    port: object,
    subject: str,
    meeting_id: str,
) -> dict | None:
    if kind == "graph":
        return _json_block(uri, projected["graph"])
    if kind == "brief":
        return _json_block(uri, projected["brief"])
    if kind == "review":
        return _json_block(uri, projected["review"])
    if name is None:
        return None
    rendered = port.export_bytes(meeting_id, subject, name)  # type: ignore[attr-defined]
    if rendered is None:
        rendered = render_local(name, projected)
    if rendered is None:
        return None
    mime, body = rendered
    block: dict = {"uri": uri, "mimeType": mime}
    if is_text(name):
        block["text"] = body.decode("utf-8")
    else:
        block["blob"] = base64.b64encode(body).decode("ascii")
    return block


def _json_block(uri: str, payload: dict) -> dict:
    import json

    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": json.dumps(payload, ensure_ascii=False),
    }


def reject_cursor(cursor: object, request_id: object) -> dict | None:
    if cursor in (None, ""):
        return None
    decoded = decode_cursor(cursor, request_id)
    if isinstance(decoded, dict):
        return decoded
    if decoded != 0:
        return error(INVALID_PARAMS, "Invalid cursor", request_id)
    return None
