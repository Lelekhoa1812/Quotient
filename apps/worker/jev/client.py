# Motivation vs Logic
# Motivation: The queue sort needs one pinned Jev call and must finish when TypeSafe does not answer.
# Logic: POST systemone as jev-1.13.0 with a 10s timeout. Honor retry-after on 429 once. Any other failure raises a status-only error.

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

MODEL = "jev-1.13.0"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
TIMEOUT_SECONDS = 10


class JevFailed(RuntimeError):
    def __init__(self, status: int):
        self.status = int(status)
        super().__init__(f"jev request failed ({self.status})")


class Client:
    def __init__(self, key: str, transport=None, sleep=None):
        self._key = key
        self._transport = transport
        self._sleep = sleep if sleep is not None else time.sleep

    def __repr__(self) -> str:
        return "Client()"

    @classmethod
    def from_env(cls, env=None, transport=None, sleep=None):
        source = os.environ if env is None else env
        key = source.get("JEV_TYPESAFE_API_KEY") or source.get("TYPESAFE_API_KEY")
        if not isinstance(key, str) or not key.strip():
            return None
        return cls(key.strip(), transport=transport, sleep=sleep)

    def evaluate(self, payload: dict) -> dict:
        status, headers, raw = self._exchange(payload)
        if status == 429:
            self._sleep(min(TIMEOUT_SECONDS, _retry_after(headers)))
            status, headers, raw = self._exchange(payload)
        if status != 200:
            raise JevFailed(status) from None
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise JevFailed(status) from None
        if not isinstance(data, dict):
            raise JevFailed(status) from None
        return data

    def _exchange(self, payload: dict) -> tuple[int, dict, bytes]:
        started = time.perf_counter()
        raw = json.dumps(payload).encode("utf-8")
        try:
            result = self._send(raw, payload)
        except Exception as exc:
            _audit_api(status=0, ms=_elapsed_ms(started), request_bytes=len(raw), error=type(exc).__name__)
            raise
        _audit_api(status=result[0], ms=_elapsed_ms(started), request_bytes=len(raw), response_bytes=len(result[2]))
        return result

    def _send(self, raw: bytes, payload: dict) -> tuple[int, dict, bytes]:
        if self._transport is not None:
            status, headers, body = self._transport(payload)
            if isinstance(body, str):
                body = body.encode()
            return int(status), dict(headers or {}), body
        request = urllib.request.Request(
            ENDPOINT,
            data=raw,
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            code = exc.code
            headers = dict(exc.headers or {})
            detail = exc.read()
            return code, headers, detail
        except Exception:
            raise JevFailed(0) from None


# Motivation vs Logic
# Motivation: --logs has to show each Jev call's status and duration.
# Logic: Write one audit line after the exchange. Leave the key and the body out.
def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _audit_api(**fields: object) -> None:
    if not os.environ.get("QUOTIENT_AUDIT_LOG"):
        return
    try:
        from audit import record
    except ImportError:
        return
    record("api", "jev", model=MODEL, host="api.typesafe.ai", **fields)


def _retry_after(headers) -> float:
    if not headers:
        return 0.0
    raw = headers.get("Retry-After")
    if raw is None:
        raw = headers.get("retry-after")
    if raw is None:
        return 0.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    try:
        when = parsedate_to_datetime(str(raw))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return 0.0
