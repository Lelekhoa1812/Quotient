# Motivation vs Logic
# Motivation: The analysis can run its text reasoning on NVIDIA NIM instead of Amazon Bedrock. NIM is an
# OpenAI-compatible chat API with several models of very different speed and reliability, and an account has
# several API keys with a per-key request limit. A single hard-coded model and key would fail on the first 429.
# Logic: NimTransport has the same respond(request) contract as bedrock.wire.Transport, so the Reasoner is
# unchanged. It turns the Reasoner's request into a chat completion, then routes it the way FreeRouter does:
# try the planned model, and on failure move to the next key, then to the next model in the plan. Evidence from
# live probes (docs/model-routing.md): strict json_schema works once keywords NIM's grammar cannot express
# (uniqueItems and a few more) are removed; thinking models take 25-60 s and are used only where the plan asks
# for them; chat_template_kwargs.enable_thinking=false makes the same models answer in 2-6 s.

from __future__ import annotations

import json
import os
import random
import re
import threading
import sys
import time
import urllib.error
import urllib.request
from collections import deque

from errors import NotInvocable

BASE_URL = "https://integrate.api.nvidia.com/v1"
REQUEST_TIMEOUT_SECONDS = 300
MAX_DISPATCHES = 7
SLOW_CALL_MS = 15_000
# NVIDIA's free tier allows roughly 40 requests a minute per key. Stay under it.
PER_KEY_PER_MINUTE = 30
COOLDOWN_DEFAULT_SECONDS = 30
COOLDOWN_MAX_SECONDS = 120
MAX_WAIT_SECONDS = 90

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_UNIMPLEMENTED = re.compile(r"Unimplemented keys?:\s*\[([^\]]*)\]")
# Keywords NIM's guided-decoding grammar rejects or cannot enforce. uniqueItems is the one every Quotient schema trips on.
_SCHEMA_STRIP = frozenset({"uniqueItems", "$schema", "$id", "title"})


class NimUnavailable(RuntimeError):
    """No NVIDIA NIM key is configured."""


# ---------------------------------------------------------------------------------------------------------------
# Keys


_KEYS: list[str] | None = None
_KEYS_LOCK = threading.Lock()


def _keys_from_environment() -> list[str]:
    keys: list[str] = []
    joined = os.environ.get("NVIDIA_NIM_API_KEYS", "")
    keys.extend(part.strip() for part in re.split(r"[,\s]+", joined) if part.strip())
    for index in range(1, 10):
        value = os.environ.get(f"NVIDIA_NIM_API_KEY_{index}", "").strip()
        if value:
            keys.append(value)
    return keys


def _keys_from_secret() -> list[str]:
    arn = os.environ.get("NIM_SECRET_ARN", "").strip()
    if not arn:
        return []
    try:
        import botocore.session

        client = botocore.session.get_session().create_client(
            "secretsmanager", region_name=os.environ.get("AWS_REGION", "ap-southeast-2")
        )
        raw = client.get_secret_value(SecretId=arn).get("SecretString") or ""
    except Exception as exc:  # noqa: BLE001 - a missing grant must read as "not configured", never leak the cause
        print(f"nim secret unavailable: {type(exc).__name__}", flush=True)
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        data = raw
    if isinstance(data, dict):
        values = data.get("keys") if isinstance(data.get("keys"), list) else list(data.values())
    elif isinstance(data, list):
        values = data
    else:
        values = re.split(r"[,\s]+", str(data))
    return [str(v).strip() for v in values if isinstance(v, str) and v.strip().startswith("nvapi-")] or [
        str(v).strip() for v in values if isinstance(v, str) and v.strip()
    ]


def load_keys(refresh: bool = False) -> list[str]:
    global _KEYS
    with _KEYS_LOCK:
        if _KEYS is None or refresh:
            seen: list[str] = []
            for key in _keys_from_environment() + _keys_from_secret():
                if key not in seen:
                    seen.append(key)
            _KEYS = seen
        return list(_KEYS)


def available() -> bool:
    return bool(load_keys())


def reset_keys_for_tests() -> None:
    global _KEYS
    with _KEYS_LOCK:
        _KEYS = None
    _STATE.reset()


# ---------------------------------------------------------------------------------------------------------------
# Per-key pacing and cooldowns (process wide: every Reasoner in this worker shares the same keys)


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.sent: dict[str, deque] = {}
        self.cooldown: dict[tuple[str, str], float] = {}  # (key, model) -> monotonic time it is usable again
        self.invalid: set[str] = set()
        self.dead_models: dict[str, float] = {}  # model -> monotonic time to try again

    def wait_for(self, key: str, deadline: float) -> bool:
        """Block until this key may send, within the deadline. False when it cannot in time."""
        while True:
            with self.lock:
                window = self.sent.setdefault(key, deque())
                now = time.monotonic()
                while window and now - window[0] > 60:
                    window.popleft()
                if len(window) < PER_KEY_PER_MINUTE:
                    window.append(now)
                    return True
                wait = 60 - (now - window[0]) + 0.05
            if time.monotonic() + wait > deadline:
                return False
            time.sleep(wait)


_STATE = _State()


# ---------------------------------------------------------------------------------------------------------------
# Request and response shaping


# Keys whose values are maps of NAMES to schemas: the names are data (a property called "title" is a property), not keywords.
_NAME_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"})


def strip_schema(node: object, banned: frozenset[str] = _SCHEMA_STRIP) -> object:
    if isinstance(node, dict):
        return {k: strip_schema(v, banned) for k, v in node.items() if k not in banned}
    if isinstance(node, list):
        return [strip_schema(item, banned) for item in node]
    return node


def strip_keywords(node: object, banned: frozenset[str] = _SCHEMA_STRIP) -> object:
    """Remove schema keywords NIM cannot express, never a property name. A map of names (properties, $defs) keeps every
    name and has only its values cleaned."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in banned:
                continue
            if key in _NAME_MAPS and isinstance(value, dict):
                out[key] = {name: strip_keywords(sub, banned) for name, sub in value.items()}
            else:
                out[key] = strip_keywords(value, banned)
        return out
    if isinstance(node, list):
        return [strip_keywords(item, banned) for item in node]
    return node


def _text_of(contents: object) -> str:
    parts = []
    for item in contents or []:
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
        elif isinstance(item, str):
            parts.append(item)
    return "\n".join(parts)


def build_body(request: dict, model: str, *, response_format: str) -> dict:
    """Chat-completions body for one model. response_format: 'schema', 'object' or 'none'."""
    system, messages = [], []
    for message in request.get("input") or []:
        if not isinstance(message, dict):
            continue
        text = _text_of(message.get("content"))
        if not text:
            continue
        if message.get("role") == "system":
            system.append(text)
        elif message.get("role") in {"user", "assistant"}:
            messages.append({"role": message["role"], "content": text})
    if system:
        messages.insert(0, {"role": "system", "content": "\n\n".join(system)})
    body: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": int(request.get("max_output_tokens") or 16384),
        "temperature": 0.2,
        "stream": False,
    }
    if request.get("thinking") is False:
        body["chat_template_kwargs"] = {"enable_thinking": False}
        if "glm" in model:
            body["reasoning_effort"] = "low"
    tools = request.get("tools")
    if isinstance(tools, list) and tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description") or "",
                    "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
                },
            }
            for tool in tools
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        ]
        body["tool_choice"] = "auto"
    fmt = (request.get("text") or {}).get("format") if isinstance(request.get("text"), dict) else None
    if isinstance(fmt, dict) and fmt.get("type") == "json_schema" and isinstance(fmt.get("schema"), dict) and not body.get("tools"):
        if response_format == "schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": str(fmt.get("name") or "schema").replace(".", "_"), "schema": strip_keywords(fmt["schema"]), "strict": True},
            }
        elif response_format == "object":
            body["response_format"] = {"type": "json_object"}
    return body


def parse_response(data: dict) -> dict:
    choice = ((data.get("choices") or [{}])[0]) if isinstance(data, dict) else {}
    message = choice.get("message") or {}
    text = message.get("content") or ""
    if isinstance(text, list):
        text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    text = _THINK.sub("", text)
    if "</think>" in text:  # an opening tag that was part of the prompt template
        text = text.split("</think>", 1)[1]
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*\n(.*)\n```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    calls = []
    for item in message.get("tool_calls") or []:
        function = item.get("function") if isinstance(item, dict) else None
        if not isinstance(function, dict):
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except ValueError:
                arguments = None
        if isinstance(function.get("name"), str) and isinstance(arguments, dict):
            calls.append({"name": function["name"], "arguments": arguments})
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    return {
        "output_text": text,
        "tool_calls": calls,
        "usage": {"cached_tokens": int(details.get("cached_tokens") or 0)},
        "finish_reason": choice.get("finish_reason"),
    }


def _public(text: str) -> str:
    return re.sub(r"nvapi-[A-Za-z0-9_\-]+", "[key]", text.replace("\n", " "))[:200]


class _Retry(Exception):
    """This key or model failed for a reason another key or model may not share."""

    def __init__(self, kind: str, detail: str = "", cooldown: float = 0.0):
        super().__init__(detail)
        self.kind = kind  # "key", "model" or "invalid"
        self.detail = detail
        self.cooldown = cooldown


# ---------------------------------------------------------------------------------------------------------------


class NimTransport:
    """respond(request) like bedrock.wire.Transport, routed across NIM keys and a fallback chain of models."""

    def __init__(self, keys: list[str] | None = None, opener=None):
        self._keys = keys
        self._opener = opener
        self.attempts: list[dict] = []

    def keys(self) -> list[str]:
        keys = self._keys if self._keys is not None else load_keys()
        if not keys:
            raise NimUnavailable("No NVIDIA NIM key is configured.")
        return keys

    def respond(self, request: dict) -> dict:
        keys = self.keys()
        models = [str(request.get("model") or "")] + [m for m in (request.get("fallback_models") or []) if m]
        models = [m for i, m in enumerate(models) if m and m not in models[:i]]
        if not models:
            raise NotInvocable("", "no-model")
        deadline = time.monotonic() + MAX_WAIT_SECONDS + REQUEST_TIMEOUT_SECONDS * 2
        dispatched = 0
        last = "no attempt"
        now = time.monotonic()
        # A model that failed hard a moment ago goes last, not never.
        ordered = sorted(models, key=lambda m: 1 if _STATE.dead_models.get(m, 0) > now else 0)
        for model in ordered:
            fmt = "schema"
            stripped: frozenset[str] | None = None
            queue = self._rank(keys, model)
            tried = 0
            reshaped = 0
            while queue and dispatched < MAX_DISPATCHES and tried < 3:
                key = queue.pop(0)
                if not _STATE.wait_for(key, deadline):
                    last = "rate limited"
                    continue
                dispatched += 1
                tried += 1
                body = build_body(request, model, response_format=fmt)
                if stripped and "response_format" in body and body["response_format"].get("type") == "json_schema":
                    body["response_format"]["json_schema"]["schema"] = strip_keywords(
                        request["text"]["format"]["schema"], _SCHEMA_STRIP | stripped
                    )
                try:
                    return self._post(key, model, body)
                except _Retry as retry:
                    last = f"{model}: {retry.detail or retry.kind}"
                    self.attempts.append({"model": model, "kind": retry.kind, "detail": retry.detail})
                    if retry.kind == "invalid":
                        _STATE.invalid.add(key)
                    elif retry.kind == "key":
                        with _STATE.lock:
                            _STATE.cooldown[(key, model)] = time.monotonic() + (retry.cooldown or COOLDOWN_DEFAULT_SECONDS)
                    elif retry.kind == "schema" and reshaped < 2:
                        # The grammar refused a keyword, or json_schema as a whole: say it differently, on the same model and key.
                        reshaped += 1
                        if retry.cooldown == -1:
                            stripped = (stripped or frozenset()) | frozenset(retry.detail.split(","))
                        else:
                            fmt = "object"
                        queue.insert(0, key)
                        tried -= 1
                    elif retry.kind in {"model", "schema"}:
                        with _STATE.lock:
                            _STATE.dead_models[model] = time.monotonic() + 120
                        break
        raise NotInvocable(models[0], f"nim-exhausted: {_public(last)}")

    def _rank(self, keys: list[str], model: str) -> list[str]:
        now = time.monotonic()
        live = [k for k in keys if k not in _STATE.invalid]
        random.shuffle(live)
        ready = [k for k in live if _STATE.cooldown.get((k, model), 0) <= now]
        cooling = [k for k in live if k not in ready]
        return ready + cooling

    def _post(self, key: str, model: str, body: dict) -> dict:
        raw = json.dumps(body).encode()
        request = urllib.request.Request(
            f"{BASE_URL}/chat/completions",
            data=raw,
            method="POST",
            headers={"authorization": f"Bearer {key}", "content-type": "application/json", "accept": "application/json"},
        )
        started = time.perf_counter()
        try:
            if self._opener is not None:
                status, payload = self._opener(request)
            else:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    status, payload = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, payload = exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError, OSError, ConnectionError) as exc:
            raise _Retry("key", f"transport {type(exc).__name__}") from exc
        elapsed = int((time.perf_counter() - started) * 1000)
        if status >= 400 or elapsed >= SLOW_CALL_MS:
            # No key, no prompt: only what is needed to see where the minutes went.
            thinking = "chat_template_kwargs" not in body
            print(f"nim call: {model} thinking={'on' if thinking else 'off'} HTTP {status} {elapsed / 1000:.0f}s", file=sys.stderr, flush=True)
        if status >= 400:
            self._audit(model, status, elapsed, len(raw), error=True)
            raise self._classify(status, payload)
        try:
            data = json.loads(payload)
        except ValueError as exc:
            raise _Retry("key", "unreadable reply") from exc
        result = parse_response(data)
        self._audit(model, status, elapsed, len(raw), response_bytes=len(payload))
        if not result["output_text"] and not result["tool_calls"]:
            # Reasoning used the whole budget, or the model returned nothing: another model may answer.
            raise _Retry("model", f"empty reply ({result.get('finish_reason') or 'no reason'})")
        return result

    @staticmethod
    def _classify(status: int, payload: bytes) -> _Retry:
        text = payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
        if status in {400, 422}:
            match = _UNIMPLEMENTED.search(text)
            if match:
                keys = ",".join(k.strip().strip('"\\ ') for k in match.group(1).split(",") if k.strip())
                return _Retry("schema", keys, cooldown=-1)
            if "response_format" in text or "json_schema" in text or "Grammar" in text or status == 400 and "Bad Request" in text:
                return _Retry("schema", "format rejected")
            return _Retry("model", f"HTTP {status}")
        if status in {401, 403}:
            return _Retry("invalid", f"HTTP {status}")
        if status == 402:
            return _Retry("key", "HTTP 402", cooldown=COOLDOWN_MAX_SECONDS)
        if status in {404, 410, 413}:
            return _Retry("model", f"HTTP {status}")
        if status == 429:
            return _Retry("key", "HTTP 429", cooldown=COOLDOWN_DEFAULT_SECONDS)
        if status in {408, 425}:
            return _Retry("key", f"HTTP {status}")
        if status == 503:
            return _Retry("model", "HTTP 503")
        return _Retry("key", f"HTTP {status}", cooldown=10)

    @staticmethod
    def _audit(model: str, status: int, ms: int, request_bytes: int, **fields: object) -> None:
        if not os.environ.get("QUOTIENT_AUDIT_LOG"):
            return
        try:
            from audit import record
        except ImportError:
            return
        record("llm", "nim-chat", model_id=model, host="integrate.api.nvidia.com", status=status, ms=ms, request_bytes=request_bytes, **fields)
