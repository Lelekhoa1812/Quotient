"""JSON-RPC error codes used by the Quotient MCP endpoint."""

from __future__ import annotations

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
RESOURCE_NOT_FOUND = -32002

RELATED_TASK = "io.modelcontextprotocol/related-task"


def error(code: int, message: str, request_id: object = None, data: object | None = None) -> dict:
    body: dict = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": body}


def result(request_id: object, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}
