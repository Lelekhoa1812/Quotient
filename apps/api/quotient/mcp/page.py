"""Opaque cursors for MCP list methods."""

from __future__ import annotations

import base64

from quotient.mcp.errors import INVALID_PARAMS, error


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode("ascii")).decode("ascii")


def decode_cursor(cursor: object, request_id: object) -> int | dict:
    if cursor is None or cursor == "":
        return 0
    if not isinstance(cursor, str):
        return error(INVALID_PARAMS, "Invalid cursor", request_id)
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
        if not raw.startswith("o:"):
            raise ValueError
        offset = int(raw[2:])
    except Exception:
        return error(INVALID_PARAMS, "Invalid cursor", request_id)
    if offset < 0:
        return error(INVALID_PARAMS, "Invalid cursor", request_id)
    return offset
