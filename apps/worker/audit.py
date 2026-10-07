# Motivation vs Logic
# Motivation: scripts/start-local.sh --logs has to record what LLM and API
# calls did, without writing credentials or meeting text into the audit file.
# Logic: QUOTIENT_AUDIT_LOG unset is a no-op. When it is a path, append one
# JSON object per call. Drop secret field names, then replace any configured
# secret value that still appears in the line.

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime

_LOCK = threading.Lock()
_SECRET_ENV = (
    "AWS_BEDROCK_API_KEY",
    "AWS_BEARER_TOKEN_BEDROCK",
    "JEV_TYPESAFE_API_KEY",
    "TYPESAFE_API_KEY",
)
_HIDDEN = ("authorization", "token", "secret", "password", "api_key", "apikey", "bearer")


def record(service: str, operation: str, **fields: object) -> None:
    path = os.environ.get("QUOTIENT_AUDIT_LOG")
    if not path:
        return
    try:
        event: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "service": service,
            "operation": operation,
        }
        for name, value in fields.items():
            if _hidden(name):
                continue
            event[name] = value
        line = json.dumps(event, default=str, separators=(",", ":"))
        line = _redact(line)
        with _LOCK:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
    except Exception:
        return


def _hidden(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in _HIDDEN)


def _redact(line: str) -> str:
    for name in _SECRET_ENV:
        secret = os.environ.get(name)
        if isinstance(secret, str) and len(secret) >= 8 and secret in line:
            line = line.replace(secret, "[redacted]")
    return line
