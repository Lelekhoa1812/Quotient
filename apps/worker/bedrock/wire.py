# Motivation vs Logic
# Motivation: Local analysis has to call the pinned Bedrock models with the API key
# and never log that key. Sonic is a bidirectional stream paced by the caller.
# Logic: Responses and InvokeModel are HTTPS posts. Sonic is HTTP/2 eventstream.
# A model-not-found error is NotInvocable so Sol can fall back once.

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import select
import socket
import ssl
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable
from datetime import UTC, datetime

from errors import NotInvocable

_STRING = 7
_PRELUDE = 12


_IAM: tuple[float, object] | None = None
_IAM_LOCK = threading.Lock()


def invalidate_iam() -> None:
    """Drop the cached session credentials so the next call re-reads them (after an HTTP 401/403)."""
    global _IAM
    with _IAM_LOCK:
        _IAM = None


def iam_credentials():
    """Session credentials for SigV4. The Bedrock API key is not logged and is not required."""

    global _IAM
    now = time.time()
    if _IAM is not None and _IAM[0] > now + 480:
        return _IAM[1]
    with _IAM_LOCK:
        now = time.time()
        if _IAM is not None and _IAM[0] > now + 480:
            return _IAM[1]
        completed = subprocess.run(
            ["aws", "configure", "export-credentials", "--format", "process"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        if completed.returncode != 0:
            return None
        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None
        access = data.get("AccessKeyId")
        secret = data.get("SecretAccessKey")
        if not isinstance(access, str) or not isinstance(secret, str):
            return None
        from botocore.credentials import Credentials

        token = data.get("SessionToken")
        creds = Credentials(access, secret, token if isinstance(token, str) else None)
        # Bugs vs Fixes
        # Bug: Cached session credentials were reused after they expired, so the
        # next Sonic open returned HTTP 403. Parallel calls could also refresh
        # that cache at the same time.
        # Fix: Honor the credential expiration and refresh under one lock while
        # a five-minute stream can still finish on the new token.
        expires_at = now + 600
        expiry = data.get("Expiration")
        if isinstance(expiry, str):
            try:
                expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00")).timestamp()
            except ValueError:
                expires_at = now + 600
        _IAM = (expires_at, creds)
        return creds


# Bugs vs Fixes
# Bug: A bearer token on the Sonic bidirectional stream returns HTTP 403.
# An unsigned event frame then returns validationException on Nova 2.5, so
# analysis dies before any transcript exists. The runtime identity is IAM.
# Fix: Sign the HTTP/2 request as STREAMING-AWS4-HMAC-SHA256-EVENTS and sign
# each event from that signature. The API key remains the fallback and is never logged.
_EVENT_STREAM_HASH = "STREAMING-AWS4-HMAC-SHA256-EVENTS"
def _auth_headers(url: str, body: bytes, *, content_type: str, accept: str, token: str, streaming: bool) -> dict[str, str]:
    creds = iam_credentials()
    if creds is None:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "Accept": accept,
        }
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    host = urllib.parse.urlsplit(url).hostname or ""
    region = host.split(".")[1] if host.startswith("bedrock-runtime.") else "ap-southeast-2"
    headers = {"Content-Type": content_type, "Accept": accept, "Host": host}
    request = AWSRequest(method="POST", url=url, data=b"" if streaming else body, headers=headers)
    if streaming:
        request.context["payload_signing_enabled"] = False
    SigV4Auth(creds, "bedrock", region).add_auth(request)
    signed = {str(key): str(value) for key, value in request.headers.items()}
    return signed


def bearer_token() -> str:
    raw = os.environ.get("AWS_BEARER_TOKEN_BEDROCK") or os.environ.get("AWS_BEDROCK_API_KEY") or ""
    token = raw.strip().strip('"').strip("'")
    if not token:
        raise RuntimeError("Bedrock API key is not configured")
    return token


# Motivation vs Logic
# Motivation: --logs needs one line per Bedrock call: model, host, status, and timing.
# Logic: Skip the write unless QUOTIENT_AUDIT_LOG is set. Never pass headers or bodies.
def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _audit_llm(operation: str, **fields: object) -> None:
    if not os.environ.get("QUOTIENT_AUDIT_LOG"):
        return
    try:
        from audit import record
    except ImportError:
        return
    record("llm", operation, **fields)


class Transport:
    """HTTPS adapter. respond() and invoke() match the worker client contracts."""

    def __init__(self, token: str | None = None, opener: Callable | None = None):
        self._token = token if token is not None else bearer_token()
        self._opener = opener

    def respond(self, request: dict) -> dict:
        region = request.get("region") or "ap-southeast-2"
        body = {key: value for key, value in request.items() if key != "region"}
        url = f"https://bedrock-runtime.{region}.amazonaws.com/openai/v1/responses"
        data = self._post(
            url,
            body,
            model_id=str(request.get("model") or ""),
            operation="respond",
            timeout=180,
        )
        return {
            "output_text": _output_text(data),
            "tool_calls": _function_calls(data),
            "usage": {"cached_tokens": _cached_tokens(data)},
        }

    def invoke(self, *, model_id: str, region: str, body: dict) -> dict:
        quoted = urllib.parse.quote(model_id, safe="")
        url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{quoted}/invoke"
        data = self._post(url, body, model_id=model_id, operation="invoke")
        return _pegasus_response(data)

    def open(self, *, model_id: str, region: str):
        return _SonicSession(model_id=model_id, region=region, token=self._token)

    def _post(self, url: str, body: dict, *, model_id: str, operation: str, timeout: int = 600) -> dict:
        raw = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=raw,
            method="POST",
            headers=_auth_headers(
                url,
                raw,
                content_type="application/json",
                accept="application/json",
                token=self._token,
                streaming=False,
            ),
        )
        started = time.perf_counter()
        host = urllib.parse.urlsplit(url).hostname or ""
        # Bugs vs Fixes
        # Bug: A single HTTP 500 from the model host aborted the meeting.
        # Fix: Retry 500, 502, 503, and 529 twice. Reasoning still times out at 180s.
        response_status = 0
        response_body = b""
        for attempt in range(3):
            try:
                if self._opener is not None:
                    response_status, response_body = self._opener(request)
                else:
                    with urllib.request.urlopen(request, timeout=timeout) as response:
                        response_status, response_body = response.status, response.read()
            except urllib.error.HTTPError as exc:
                response_status, response_body = exc.code, exc.read()
            if response_status in {500, 502, 503, 529} and attempt < 2:
                time.sleep(1 + attempt)
                continue
            break
        status, payload = response_status, response_body
        if status >= 400:
            _audit_llm(
                operation,
                model_id=model_id,
                host=host,
                status=status,
                ms=_elapsed_ms(started),
                request_bytes=len(raw),
                error="http",
            )
            _raise_http(status, payload if isinstance(payload, (bytes, bytearray)) else b"", model_id)
        response_bytes = len(payload) if isinstance(payload, (bytes, bytearray)) else 0
        _audit_llm(
            operation,
            model_id=model_id,
            host=host,
            status=status,
            ms=_elapsed_ms(started),
            request_bytes=len(raw),
            response_bytes=response_bytes,
        )
        return _json_object(payload)


# Motivation vs Logic
# Motivation: The Sonic socket is non-blocking so reads can be polled. sendall() on
# a non-blocking TLS socket raises SSLWantWriteError / BlockingIOError whenever the
# send buffer is momentarily full, which happens under load or when two streams
# run at once, and it failed the whole transcription session.
# Logic: Write what the socket accepts, wait (select) until it is writable again,
# and continue until every byte is out or the deadline passes. A TLS socket that
# needs to read first is waited on for readability.
def _send_all(sock, data: bytes, *, timeout: float = 30.0) -> None:
    view = memoryview(data)
    deadline = time.monotonic() + timeout
    while len(view):
        want_read = False
        try:
            sent = sock.send(view)
            view = view[sent:]
            continue
        except ssl.SSLWantReadError:
            want_read = True
        except (ssl.SSLWantWriteError, BlockingIOError):
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Sonic send timed out")
        readable, writable, _ = select.select([sock] if want_read else [], [] if want_read else [sock], [], min(remaining, 1.0))
        del readable, writable


class _SonicSession:
    """One Nova session. send() writes one event and returns any text already buffered."""

    def __init__(self, *, model_id: str, region: str, token: str):
        self._model_id = model_id
        self._region = region
        self._token = token
        self._buffer = bytearray()
        self._ready: list[dict] = []
        self._status: int | None = None
        self._error: str | None = None
        self._ended = False
        self._probed = False
        self._lock = threading.Lock()
        started = time.perf_counter()
        try:
            self._sock, self._conn, self._stream_id, self._signer = _open_h2(region, model_id, token)
        except Exception as exc:
            _audit_llm(
                "sonic.open",
                model_id=model_id,
                region=region,
                ms=_elapsed_ms(started),
                error=type(exc).__name__,
            )
            raise
        _audit_llm("sonic.open", model_id=model_id, region=region, status=200, ms=_elapsed_ms(started))

    def send(self, event: dict) -> list[dict]:
        if self._error:
            raise RuntimeError(self._error)
        raw = json.dumps(event).encode("utf-8")
        if self._signer is None:
            frame = _encode_frame(_CHUNK_HEADERS, raw)
        else:
            wrapped = json.dumps({"bytes": base64.b64encode(raw).decode("ascii")}, separators=(",", ":")).encode("ascii")
            frame = self._signer.wrap(_encode_frame(_CHUNK_HEADERS, wrapped))
        with self._lock:
            probe = not self._probed
            self._probed = True
            self._write(frame, end_stream=False)
            self._pump(2 if probe else 0)
            self._raise_status()
        return self._take()

    def close(self) -> list[dict]:
        started = time.perf_counter()
        try:
            with self._lock:
                if not self._ended:
                    if self._signer is not None:
                        self._write(self._signer.wrap(b""), end_stream=False)
                    self._write(b"", end_stream=True)
                self._pump(45)
            self._close_socket()
            if self._error and not self._ready:
                raise RuntimeError(self._error)
            taken = self._take()
        except Exception as exc:
            _audit_llm(
                "sonic.close",
                model_id=self._model_id,
                region=self._region,
                ms=_elapsed_ms(started),
                error=type(exc).__name__,
            )
            raise
        _audit_llm(
            "sonic.close",
            model_id=self._model_id,
            region=self._region,
            status=self._status or 200,
            events=len(taken),
            ms=_elapsed_ms(started),
        )
        return taken

    def release(self) -> None:
        self._close_socket()

    def _write(self, payload: bytes, *, end_stream: bool) -> None:
        if self._ended:
            return
        view = payload
        waited = 0.0
        while True:
            self._pump(0)
            window = self._conn.local_flow_control_window(self._stream_id)
            if window <= 0 and view:
                self._pump(0.05)
                waited += 0.05
                if waited > 30:
                    raise RuntimeError("Sonic send window did not open")
                continue
            waited = 0.0
            take = len(view) if not view else min(len(view), window)
            chunk = view[:take]
            view = view[take:]
            last = end_stream and not view
            self._conn.send_data(self._stream_id, chunk, end_stream=last)
            _send_all(self._sock, self._conn.data_to_send())
            if last:
                self._ended = True
            if not view:
                return

    def _pump(self, timeout: float) -> None:
        if self._sock is None:
            return
        deadline = time.monotonic() + timeout
        while self._sock is not None and not self._ended:
            remaining = 0.0 if timeout == 0 else deadline - time.monotonic()
            if timeout > 0 and remaining <= 0:
                return
            try:
                readable, _, _ = select.select([self._sock], [], [], max(0.0, remaining))
            except (OSError, ValueError):
                self._ended = True
                return
            if not readable:
                return
            try:
                incoming = self._sock.recv(65535)
            except (BlockingIOError, ssl.SSLWantReadError, TimeoutError):
                return
            if not incoming:
                self._ended = True
                return
            events = self._conn.receive_data(incoming)
            _send_all(self._sock, self._conn.data_to_send())
            for event in events:
                self._on_event(event)
            if timeout == 0 and not readable:
                return

    def _on_event(self, event) -> None:
        from h2.events import DataReceived, ResponseReceived, StreamEnded

        if isinstance(event, ResponseReceived):
            self._status = _status_of(event.headers)
            if self._status and self._status >= 400:
                self._error = f"sonic HTTP {self._status}"
        elif isinstance(event, DataReceived):
            self._buffer.extend(event.data)
            self._conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
            _send_all(self._sock, self._conn.data_to_send())
            for headers, payload in _decode_frames(self._buffer):
                parsed = _sonic_event(headers, payload)
                if parsed is not None:
                    self._ready.append(parsed)
                elif _exception_message(headers, payload):
                    self._error = _exception_message(headers, payload)
        elif isinstance(event, StreamEnded):
            self._ended = True

    def _raise_status(self) -> None:
        if self._status == 404:
            raise NotInvocable(self._model_id, "ResourceNotFoundException")
        if self._status == 403:
            raise RuntimeError(
                "sonic HTTP 403: check the configured AWS identity, Sonic model access, "
                "and bidirectional-stream permission"
            )
        if self._status is not None and self._status >= 400:
            raise RuntimeError(self._error or f"sonic HTTP {self._status}")
        if self._error and "ResourceNotFound" in self._error:
            raise NotInvocable(self._model_id, "ResourceNotFoundException")

    def _take(self) -> list[dict]:
        found = list(self._ready)
        self._ready.clear()
        return found

    def _close_socket(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                return


_CHUNK_HEADERS = (
    (":message-type", "event"),
    (":event-type", "chunk"),
    (":content-type", "application/json"),
)


def _signing_key(secret: str, datestamp: str, region: str) -> bytes:
    key = hmac.new(("AWS4" + secret).encode("utf-8"), datestamp.encode("utf-8"), hashlib.sha256).digest()
    key = hmac.new(key, region.encode("utf-8"), hashlib.sha256).digest()
    key = hmac.new(key, b"bedrock", hashlib.sha256).digest()
    return hmac.new(key, b"aws4_request", hashlib.sha256).digest()


def _timestamp_header(name: str, moment: datetime) -> bytes:
    raw_name = name.encode("utf-8")
    millis = int(moment.timestamp() * 1000)
    return struct.pack(">B", len(raw_name)) + raw_name + struct.pack(">Bq", 8, millis)


def _blob_header(name: str, value: bytes) -> bytes:
    raw_name = name.encode("utf-8")
    return struct.pack(">B", len(raw_name)) + raw_name + struct.pack(">BH", 6, len(value)) + value


class _EventSigner:
    """Chains the HTTP signature into each Sonic event. The secret is not logged."""

    def __init__(self, secret: str, region: str, prior: str):
        self._secret = secret
        self._region = region
        self._prior = prior

    def wrap(self, payload: bytes) -> bytes:
        moment = datetime.now(UTC)
        stamp = moment.strftime("%Y%m%dT%H%M%SZ")
        date_headers = _timestamp_header(":date", moment)
        scope = f"{stamp[:8]}/{self._region}/bedrock/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256-PAYLOAD",
                stamp,
                scope,
                self._prior,
                hashlib.sha256(date_headers).hexdigest(),
                hashlib.sha256(payload).hexdigest(),
            ]
        )
        digest = hmac.new(
            _signing_key(self._secret, stamp[:8], self._region),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        self._prior = digest.hex()
        return _encode_frame_raw(date_headers + _blob_header(":chunk-signature", digest), payload)


def _streaming_headers(url: str, token: str) -> tuple[dict[str, str], _EventSigner | None]:
    creds = iam_credentials()
    if creds is None:
        return (
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/vnd.amazon.eventstream",
                "Accept": "application/vnd.amazon.eventstream",
            },
            None,
        )
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    region = host.split(".")[1] if host.startswith("bedrock-runtime.") else "ap-southeast-2"
    moment = datetime.now(UTC)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")
    datestamp = stamp[:8]
    headers = {
        "accept": "application/vnd.amazon.eventstream",
        "content-type": "application/vnd.amazon.eventstream",
        "host": host,
        "x-amz-content-sha256": _EVENT_STREAM_HASH,
        "x-amz-date": stamp,
    }
    token_value = getattr(creds, "token", None)
    if isinstance(token_value, str) and token_value:
        headers["x-amz-security-token"] = token_value
    names = sorted(headers)
    canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in names)
    signed_headers = ";".join(names)
    canonical = "\n".join(["POST", parts.path, "", canonical_headers, signed_headers, _EVENT_STREAM_HASH])
    scope = f"{datestamp}/{region}/bedrock/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode("utf-8")).hexdigest()]
    )
    signature = hmac.new(
        _signing_key(creds.secret_key, datestamp, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={creds.access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return headers, _EventSigner(creds.secret_key, region, signature)


def _open_h2(region: str, model_id: str, token: str):
    import h2.config
    import h2.connection

    host = f"bedrock-runtime.{region}.amazonaws.com"
    raw = socket.create_connection((host, 443), timeout=30)
    context = ssl.create_default_context()
    context.set_alpn_protocols(["h2"])
    sock = context.wrap_socket(raw, server_hostname=host)
    if sock.selected_alpn_protocol() != "h2":
        sock.close()
        raise RuntimeError("Bedrock did not negotiate HTTP/2 for Sonic")
    sock.setblocking(False)
    config = h2.config.H2Configuration(client_side=True, header_encoding="utf-8")
    conn = h2.connection.H2Connection(config=config)
    conn.initiate_connection()
    conn.increment_flow_control_window(8 * 1024 * 1024)
    stream_id = conn.get_next_available_stream_id()
    path = "/model/" + urllib.parse.quote(model_id, safe="") + "/invoke-with-bidirectional-stream"
    url = f"https://{host}{path}"
    signed, signer = _streaming_headers(url, token)
    headers = [
        (":method", "POST"),
        (":path", path),
        (":scheme", "https"),
        (":authority", host),
    ]
    for key, value in signed.items():
        if key.lower() == "host":
            continue
        headers.append((key.lower(), value))
    conn.send_headers(stream_id, headers, end_stream=False)
    conn.increment_flow_control_window(8 * 1024 * 1024, stream_id=stream_id)
    _send_all(sock, conn.data_to_send())
    return sock, conn, stream_id, signer


def _encode_frame_raw(header_bytes: bytes, payload: bytes) -> bytes:
    total = _PRELUDE + len(header_bytes) + len(payload) + 4
    prelude = struct.pack(">II", total, len(header_bytes))
    prelude += struct.pack(">I", zlib.crc32(prelude) & 0xFFFFFFFF)
    message = prelude + header_bytes + payload
    return message + struct.pack(">I", zlib.crc32(message) & 0xFFFFFFFF)


def _encode_frame(headers: tuple[tuple[str, str], ...], payload: bytes) -> bytes:
    blob = b"".join(_header(name, value) for name, value in headers)
    total = _PRELUDE + len(blob) + len(payload) + 4
    prelude = struct.pack(">II", total, len(blob))
    prelude += struct.pack(">I", zlib.crc32(prelude) & 0xFFFFFFFF)
    message = prelude + blob + payload
    return message + struct.pack(">I", zlib.crc32(message) & 0xFFFFFFFF)


def _header(name: str, value: str) -> bytes:
    raw_name = name.encode("utf-8")
    raw_value = value.encode("utf-8")
    return struct.pack(">B", len(raw_name)) + raw_name + struct.pack(">BH", _STRING, len(raw_value)) + raw_value


def _decode_frames(buffer: bytearray) -> list[tuple[dict, bytes]]:
    frames = []
    while len(buffer) >= _PRELUDE:
        total, headers_length, _crc = struct.unpack_from(">III", buffer)
        if total < 16 or total > 16_000_000 or len(buffer) < total:
            break
        frame = bytes(buffer[:total])
        del buffer[:total]
        headers = _parse_headers(frame[_PRELUDE : _PRELUDE + headers_length])
        payload = frame[_PRELUDE + headers_length : -4]
        frames.append((headers, payload))
    return frames


def _parse_headers(blob: bytes) -> dict:
    headers = {}
    offset = 0
    while offset < len(blob):
        name_len = blob[offset]
        offset += 1
        name = blob[offset : offset + name_len].decode("utf-8")
        offset += name_len
        kind = blob[offset]
        offset += 1
        if kind == _STRING:
            value_len = struct.unpack_from(">H", blob, offset)[0]
            offset += 2
            headers[name] = blob[offset : offset + value_len].decode("utf-8")
            offset += value_len
        else:
            break
    return headers


def _sonic_event(headers: dict, payload: bytes) -> dict | None:
    if headers.get(":message-type") not in {None, "event"}:
        return None
    parsed = _json_bytes(payload)
    if not isinstance(parsed, dict):
        return None
    nested = parsed.get("bytes")
    if isinstance(nested, str):
        try:
            import base64

            decoded = _json_bytes(base64.b64decode(nested))
        except (ValueError, json.JSONDecodeError):
            decoded = None
        if isinstance(decoded, dict):
            parsed = decoded
    if "event" in parsed or "textOutput" in parsed:
        return parsed if "event" in parsed else {"event": parsed}
    return None


def _exception_message(headers: dict, payload: bytes) -> str | None:
    if headers.get(":message-type") != "exception":
        return None
    kind = headers.get(":exception-type") or "exception"
    parsed = _json_bytes(payload)
    message = parsed.get("message") if isinstance(parsed, dict) else ""
    text = f"{kind}: {message}" if isinstance(message, str) and message else kind
    return _public(text)


def _status_of(headers) -> int | None:
    for name, value in headers:
        if name == ":status":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _json_bytes(payload: bytes) -> dict | list | None:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _json_object(payload: bytes) -> dict:
    data = _json_bytes(payload)
    if not isinstance(data, dict):
        raise RuntimeError("Bedrock response was not a JSON object")
    return data


def _function_calls(data: dict) -> list[dict]:
    """Responses function_call items. Arguments stay a JSON object; a bad blob is dropped."""

    calls = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue
        name = item.get("name")
        arguments = item.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                continue
        if isinstance(name, str) and name and isinstance(arguments, dict):
            calls.append({"name": name, "arguments": arguments})
    return calls


def _output_text(data: dict) -> str:
    # Bugs vs Fixes
    # Bug: Reasoning items and an earlier message were concatenated onto the
    # schema object, so validation saw two JSON values and rejected the turn.
    # Fix: Use the last message text. A response with no message keeps output_text.
    messages: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") == "reasoning":
            continue
        if item.get("type") not in {None, "message"}:
            continue
        chunks: list[str] = []
        if isinstance(item.get("text"), str):
            chunks.append(item["text"])
        for content in item.get("content") or []:
            if not isinstance(content, dict) or not isinstance(content.get("text"), str):
                continue
            if content.get("type") not in {None, "output_text", "text"}:
                continue
            chunks.append(content["text"])
        if chunks:
            messages.append("".join(chunks))
    if messages:
        return _strip_fence(messages[-1])
    direct = data.get("output_text")
    if isinstance(direct, str):
        return _strip_fence(direct)
    return ""


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _cached_tokens(data: dict) -> int:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    cached = details.get("cached_tokens", usage.get("cached_tokens", 0))
    return int(cached) if isinstance(cached, int) and not isinstance(cached, bool) else 0


def _pegasus_response(data: dict) -> dict:
    reason = data.get("finishReason") or data.get("stopReason") or data.get("stop_reason")
    message = data.get("message")
    if message is None and isinstance(data.get("output"), str):
        message = data["output"]
    if message is None and isinstance(data.get("generation"), str):
        message = data["generation"]
    if not isinstance(message, str):
        if "observations" in data or "notes" in data:
            message = json.dumps({key: data.get(key) for key in ("observations", "notes") if key in data})
            reason = reason or "stop"
        else:
            message = ""
    return {"finishReason": str(reason or "stop"), "message": message}


def _raise_http(status: int, payload: bytes, model_id: str) -> None:
    parsed = _json_bytes(payload) if payload else None
    code = ""
    message = ""
    if isinstance(parsed, dict):
        code = str(parsed.get("code") or parsed.get("__type") or parsed.get("type") or "")
        raw_message = parsed.get("message") or parsed.get("error")
        if isinstance(raw_message, dict):
            code = code or str(raw_message.get("code") or raw_message.get("type") or "")
            raw_message = raw_message.get("message")
        if isinstance(raw_message, str):
            message = raw_message
    label = code.rsplit("#", 1)[-1] or f"HTTP{status}"
    if _not_invocable(status, label, message):
        raise NotInvocable(model_id, label or "NotInvocable")
    raise RuntimeError(_public(f"{label}: {message}" if message else label))


def _not_invocable(status: int, code: str, message: str) -> bool:
    if status == 404 or code in {"ResourceNotFoundException", "ModelNotReadyException"}:
        return True
    lowered = message.casefold()
    if code in {"ValidationException", "AccessDeniedException"}:
        markers = ("model identifier", "not found", "not entitled", "unsupported", "is not available", "does not exist")
        return any(marker in lowered for marker in markers)
    return False


def _public(text: str) -> str:
    cleaned = text.replace("\n", " ")
    if "AKIA" in cleaned or "BEGIN PRIVATE" in cleaned or "Bearer " in cleaned:
        return "Bedrock request failed"
    return cleaned[:180]
