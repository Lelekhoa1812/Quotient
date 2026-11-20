# NIM.md — NVIDIA NIM routing contract

Reusable contract for any coding agent that must call NVIDIA NIM chat models with a **pool of API keys** and a
**fallback chain of models**. Derived from Quotient (`apps/worker/bedrock/nim.py`, `provider.py`,
`docs/model-routing.md`) and its sibling FreeRouter (`free-router/src/lib/{failures,providers,models}`), then
re-verified live on 2026-11-20. Items are tagged:

- **[Q]** implemented in Quotient today
- **[F]** implemented in FreeRouter (streaming gateway)
- **[V]** verified live against `integrate.api.nvidia.com` on 2026-11-20 (this document's author)
- **[R]** recommended, not in Quotient yet; the reference client in §9 implements it and was run live

```yaml
contract:
  id: nim.routing.v1
  endpoint: https://integrate.api.nvidia.com/v1/chat/completions   # OpenAI-compatible
  auth: "Authorization: Bearer nvapi-..."
  keys:
    env_numbered: NVIDIA_NIM_API_KEY_1..9        # [Q][F]
    env_joined: NVIDIA_NIM_API_KEYS              # comma/space separated, loaded first [Q]
    secret_store: "AWS Secrets Manager id in NIM_SECRET_ARN, JSON {\"keys\":[\"nvapi-...\"]}" # [Q]
    dedupe: true
  never: [log keys, put keys in error text, return keys to a browser, commit .env]
```

---

## 1. Architecture (end to end)

```text
 Settings (browser localStorage "quotient.models.v1" = {provider, overrides})        apps/web/lib/models.ts
        │  submit_meeting { model_provider: "nim", model_overrides: {slm?, llm?} }   MCP -> apps/api/.../mcp/tools.py
        ▼
 meeting row {model_provider, model_overrides}  (frozen per meeting)                 apps/worker/quotient/port.py
        │  _run_meeting: provider_name, plans("nim", overrides), transport_for("nim")
        ▼
 Reasoner (role: slm | llm)  ──builds canonical request──►  NimTransport.respond(request)
   per prompt: model, fallback_models, thinking,                │
   max_output_tokens, input[], text.format.json_schema          │  for model in [primary, *fallbacks]  (dead ones last)
                                                                │    for key in rank(keys, model) (<=3 keys/model, <=7 dispatches)
                                                                │      pace(key)  ->  POST  ->  classify(status)
                                                                ▼
                                          result {output_text, tool_calls[], usage{cached_tokens}, finish_reason}
```

Design rules that make it work:

1. **Transport is swappable.** `NimTransport.respond(request)` has the same contract as the Bedrock transport, so the
   caller (the Reasoner) knows nothing about keys, cooldowns or schema quirks. [Q]
2. **Role plans, not model names, are the public surface.** Callers say `slm` (fast, bounded) or `llm` (long
   reasoning); `provider.plans()` resolves model, output cap, thinking flag, fallbacks and input budget. [Q]
3. **Overrides are allow-listed.** `clean_overrides` drops any role or model id not in `NIM_MODELS`; nothing the user
   typed reaches the vendor. [Q]
4. **Choice is frozen per meeting.** Changing Settings never changes a running job. [Q]
5. **State is process-wide.** All threads in one worker share one pacing/cooldown table (`_STATE`), because they share
   the same keys. Default worker pool is 2–6 threads (`loop/pool.py`, env `QUOTIENT_WORKERS`). [Q]

---

## 2. Recommended models (speed / quality)

Probe basis: Quotient claim prompt + real strict schema, 3 spans, 2026-11-11 (`docs/model-routing.md`) [Q];
FreeRouter catalog statuses [F]; one trivial-prompt latency per model today [V]. "Quality" is a **proxy** (claims
extracted per pass, schema validity), not a benchmark. Re-probe before relying on it; the free catalog churns weekly.

| Rank | Model id | Think OFF | Think ON | Context | Max out | Quality proxy | Use as |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `nvidia/nemotron-3-ultra-550b-a55b` | ~5 s (1.1 s trivial [V]) | 25–28 s | 1 M | 65 536 | 3–6 claims, valid; best | **Primary** both roles |
| 2 | `nvidia/nemotron-3.5-super-vl-120b-a12b` | ~2 s | ~60 s; **empty at 4k max_tokens** | 1 M | 131 072 | 3 (5 thinking) | Fallback; give thinking a big `max_tokens` |
| 3 | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | ~3 s | ~59 s | 256 k | 65 536 | 3 (4 thinking); `json_object` mode emitted `null` enum | Fallback for long reasoning; small context |
| 4 | `poolside/laguna-xs-2.1` | 2–3 s (0.65 s trivial [V]) | n/a, no thinking mode | 262 144 | 32 768 | 2–3 claims, fewer per pass | **Fast fallback**, cheapest latency |
| 5 | `z-ai/glm-5.3-flash` | 9–11 s | untested | 1 048 576 | 32 768 | 3–4 | Last resort. Needs `reasoning_effort:"low"`; slow time-to-first-content through gateways [F] |

**Not offered (evidence):** `deepseek-ai/deepseek-v4.1-flash` (HTTP 500 / empty content; schema probe failed) [Q][F];
`stepfun-ai/step-5-preview`, `meta/muse-glimmer-30b` (empty schema result), `google/diffusiongemma-26b-a4b-it` (strict
schema ignored), `minimaxai/minimax-m3.1-flash`, `google/gemma-4-31b-it`, `mistralai/mistral-large-4-1t-a52b`,
`openai/gpt-oss-20b` (probes timed out) [F].

Role plans shipped in Quotient [Q]:

```yaml
plans:
  slm:   # easy, bounded: claims, counter-evidence, coverage, most lenses, who-is-who
    model: nvidia/nemotron-3-ultra-550b-a55b
    thinking: false
    max_output_tokens: 16384
    input_budget_tokens: 200000
    fallbacks: [nvidia/nemotron-3.5-super-vl-120b-a12b, poolside/laguna-xs-2.1, z-ai/glm-5.3-flash]
  llm:   # long reasoning: entailment, digest + review, risk/stakeholder/dependency lenses
    model: nvidia/nemotron-3-ultra-550b-a55b
    thinking: true
    max_output_tokens: 32768
    input_budget_tokens: 200000
    fallbacks: [nvidia/nemotron-3-nano-omni-30b-a3b-reasoning, nvidia/nemotron-3.5-super-vl-120b-a12b, z-ai/glm-5.3-flash]
override_rule: "override keeps the role's thinking flag; chain = [old primary, *old fallbacks minus override];
                max_output = min(role cap, model max); input_budget = min(role budget, 0.75 * model context)"
```

Selection heuristic for new work: **thinking OFF is the default** (2–6 s). Turn thinking ON only for steps whose
answer quality depends on multi-step reasoning, and then budget 25–60 s and a large `max_tokens`.

---

## 3. Request schema (the SDK contract)

There is no vendor SDK. NIM is OpenAI-compatible, so Quotient uses plain `urllib` and FreeRouter plain `fetch`.
Any OpenAI client works if you keep the body fields below. The **internal request** is vendor-neutral; the transport
maps it to the wire body. [Q]

```yaml
internal_request:            # what callers hand to respond()
  model: string              # primary
  fallback_models: [string]  # ordered; de-duplicated, empties dropped
  max_output_tokens: int     # default 16384 when absent
  thinking: bool | null      # false -> disable thinking; true/null -> model default
  input:                     # list of {role: system|user|assistant, content: [{type: input_text, text}]}
  text.format: {type: json_schema, name: string, schema: object}   # optional
  tools: [{name, description, parameters}]                          # optional
internal_response:
  output_text: string        # <think>..</think> and ```json fences already removed
  tool_calls: [{name, arguments: object}]   # arguments always parsed JSON object
  usage: {cached_tokens: int}               # NOTE: only this field is kept today
  finish_reason: string | null
```

Wire body built per attempt [Q]:

```json
{
  "model": "nvidia/nemotron-3-ultra-550b-a55b",
  "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
  "max_tokens": 16384,
  "temperature": 0.2,
  "stream": false,
  "chat_template_kwargs": {"enable_thinking": false},
  "reasoning_effort": "low",
  "response_format": {"type": "json_schema", "json_schema": {"name": "meeting_claim_v1", "schema": {}, "strict": true}},
  "tools": [{"type": "function", "function": {"name": "...", "description": "...", "parameters": {}}}],
  "tool_choice": "auto"
}
```

Field rules:

- `chat_template_kwargs.enable_thinking=false` is what turns a thinking model from 25–60 s into 2–6 s. Sent only when
  `thinking === false`. Models without a thinking mode (Laguna) ignore it. [Q]
- `reasoning_effort:"low"` only for GLM, otherwise it defaults to max reasoning and can spend a small `max_tokens`
  before emitting any answer. [Q][F]
- **Always set `max_tokens`.** Reasoning models otherwise return no visible text. Quotient sets it explicitly;
  FreeRouter does not inject it. Give GLM ≥ 1 024. [Q][F]
- `response_format` is **omitted when `tools` are present**; tools and schema are separate passes. [Q]
- Dots in the schema `name` are replaced by `_` (`meeting.claim.v1` → `meeting_claim_v1`). [Q]
- Assistant/system text only; images and other content types are not mapped. [Q]
- `prompt_cache_*`, `effort`, `region` from the canonical request are **not forwarded** (Bedrock-only). [Q]

### 3.1 Strict JSON schema: what NIM's grammar rejects

Strict `json_schema` was rejected by every NIM model until `uniqueItems` was removed. [Q]

```yaml
strip_keywords: [uniqueItems, "$schema", "$id", title]   # as KEYWORDS only
never_strip: "names under properties / patternProperties / $defs / definitions / dependentSchemas"
```

- **Bug that shipped and was fixed:** stripping `title` everywhere deleted a *required property called `title`* from the
  digest schema, so NIM never wrote it and every digest was rejected. Strip keywords, never property names
  (`strip_keywords` vs the older `strip_schema`). Covered by `test_a_property_named_like_a_keyword_is_kept`. [Q]
- The server names further offenders in the 400 body: `Unimplemented keys: ["minItems"]`. Parse that list, remove those
  keywords, resend on the **same model and key**. [Q]
- Any other format rejection (`Grammar`, `response_format`, bare `Bad Request`) → fall back to `json_object` and rely on
  local validation (the schema is already in the prompt). `json_object` can emit `null` for enums on Nano. [Q]
- Max two reshapes per model, then the model is demoted. [Q]
- Always validate the output locally with the original (un-stripped) schema; NIM enforcement is best effort. [Q]

### 3.2 Response cleaning [Q]

1. Concatenate list-typed `content` parts.
2. Remove `<think>…</think>`; if only a closing `</think>` remains (opening tag lived in the template), keep text after it.
3. Unwrap a single ```` ```json ```` fence.
4. `tool_calls[].function.arguments` string → `json.loads`; an unparseable call is dropped, not guessed.
5. **Empty text and no tool calls = failure of the model**, not success (typically `finish_reason:"length"` after
   thinking). Fail over to the next model.

---

## 4. Key rotation and model routing algorithm

### 4.1 Per-call loop [Q]

```text
models  = dedupe([request.model] + fallback_models)
ordered = sort(models, key = is_demoted(model))          # demoted go LAST, never dropped
dispatched = 0
for model in ordered:
    queue = rank(keys, model); tried = 0; reshaped = 0
    while queue and dispatched < 7 and tried < 3:
        key = queue.pop(0)
        if not pace(key, deadline): continue             # key window full
        dispatched++; tried++
        try: return post(key, model, body(fmt, stripped))
        except Retry as r:
            invalid -> retire key for process
            key     -> cooldown[(key, model)] = now + r.cooldown
            schema  -> reshape and RE-QUEUE same key (tried--), at most 2x; else demote model, break
            model   -> demote model for 120 s, break
raise NotInvocable("nim-exhausted: <last error with nvapi-… redacted, 200 chars>")
```

`rank(keys, model)`: drop retired keys, **shuffle** (random spread, no shared counter), put keys not cooling for that
model first, cooling keys last (still usable as a last resort). [Q]

### 4.2 Failure policy matrix

| HTTP / event | Class | Action | Evidence |
| --- | --- | --- | --- |
| 429 | key | cool `(key, model)` 30 s (**ignores `Retry-After`** in Quotient) | [Q]; FreeRouter honours it, capped 24 h [F] |
| 401, **403** | invalid | retire key for the process. **NIM answers 403, not 401, to a bad key on chat** | [Q] [V] |
| 402 | key | cool 120 s | [Q][F] |
| 408, 425 | key | cool 30 s | [Q] |
| other 5xx, unknown status | key | cool 10 s → next key | [Q] |
| transport error, unreadable JSON | key | cool 30 s → next key | [Q] |
| 503 | model | demote model 120 s, next model (FreeRouter: provider-wide breaker, 30 s doubling to 5 min) | [Q][F] |
| 404, 410, 413 | model | demote 120 s, next model | [Q] |
| 400/422 + `Unimplemented keys` | schema | strip named keywords, same model+key | [Q] |
| 400/422 other format error | schema | `json_object` mode, same model+key | [Q] |
| 400/422 anything else | model | next model | [Q] |
| 200 with empty output | model | next model | [Q] |

Budget: **≤ 3 keys per model, ≤ 7 dispatches per call.** With six keys and a four-model chain that is enough to survive
a full model outage plus a rate-limited key. [Q]

### 4.3 Pacing [Q]

- NVIDIA's free tier is about **40 requests/min/key** (as recorded in `docs/model-routing.md`); Quotient paces
  **30/min/key** with a 60 s sliding window of monotonic timestamps. N keys ≈ 30·N rpm (6 keys = 180, 9 keys = 270).
- **NIM returns no `x-ratelimit-*` or `Retry-After` header on success** [V]; the window is purely client-side. A
  server 429 is the only signal, so keep headroom under the 40 rpm.
- The window slot is reserved at dispatch; a retried call consumes another slot.

### 4.4 Model demotion vs key cooldown

Cooldown is per `(key, model)`; demotion is per `model`, process-wide, 120 s. Demotion **reorders**, it does not
remove: a recently failed model still gets tried if everything else fails. [Q]

### 4.5 FreeRouter's stricter variant (persistent, multi-instance) [F]

Use when more than one process shares keys, or state must survive restarts:

- Credentials encrypted at rest in MongoDB (nonce + tag envelope, AAD `provider:slot`), fingerprint = sha256(secret), 9 slots.
- Candidates ranked `binding healthy → credential healthy → unknown`, rotated by `(now + id.length + rank) % n`.
- Persisted `credential_health` and `model_bindings` (`cooldownUntil`, `schemaStatus:"failed"` skips strict-schema
  requests on that binding), plus a model overload breaker (503: 30 s × 2^(n−1), cap 5 min, window 10 min, TTL 15 min).
- Admission leases and a quota ledger before each dispatch; ≤ 3 dispatches per request; deadline 275 s.
- A newer success clears the breaker only if it started after the last failure (no erasing a concurrent 503).

---

## 5. Streaming

**Quotient does not stream** [Q]: `stream:false`, one blocking `urlopen(timeout=300)`; the whole completion is parsed
at once. That is acceptable for batch analysis and keeps strict-schema handling simple. Use streaming when a human
watches the output or when time-to-first-token matters.

Wire protocol (verified [V]): `Content-Type: text/event-stream`; lines `data: {json}`; terminal `data: [DONE]`.
Request with `"stream": true, "stream_options": {"include_usage": true}`; the last JSON event then has
`choices: []` and a `usage` object. Observed delta keys with thinking off: `role`, `content`.

Observed latency today on a trivial prompt [V]:

| Model | Non-stream total | Stream headers | Stream first content |
| --- | --- | --- | --- |
| `poolside/laguna-xs-2.1` | 0.66 s | 0.61 s | 0.63 s |
| `nvidia/nemotron-3-ultra-550b-a55b` (thinking off) | 1.12 s | 0.62 s | 1.03 s |

Rules for a streaming gateway [F] (adopt these if you add streaming):

1. **Failover only before the first visible token.** Never splice a second model onto output already delivered; on a
   mid-stream failure emit an error frame and close.
2. Open the client SSE immediately and send `: keepalive` comments every 10 s while waiting for upstream headers (GLM
   can take 60–90 s to first content).
3. Hard deadline (275 s in FreeRouter); abort the upstream reader when the client disconnects.
4. Always call upstream with `stream:true` even for non-streaming callers; assemble the deltas yourself. This avoids
   long idle HTTP reads and gives time-to-first-byte signals.
5. **Strict schema or strict tools: buffer, validate, then release** (FreeRouter caps at 8 MiB; a single SSE event
   buffer caps at 4 MiB).
6. Filter provider reasoning-only fields from what the client sees; a model that streams only reasoning and no content
   is treated as failed (Nemotron Lightning was removed for this).
7. Normalise tool-call deltas (stable `id`, stable `index`); `finish_reason:"stop"` becomes `tool_calls` if tools were emitted.

---

## 6. Connections and "polling"

- **No polling for completions.** NIM chat is synchronous or SSE; there is no job id to poll. (Some other NVIDIA
  catalog endpoints answer 202 and need a status poll; not observed on chat completions here. Treat a 202 as
  unsupported until verified.)
- **What polls in this stack:** (a) the pacing loop `wait_for` sleeps until a window slot frees; (b) credential health
  re-checks when a cooldown expires; (c) FreeRouter probes a key when it is saved.
- **`GET /models` is not an authentication probe.** It returned **200 with a fabricated key** [V], while chat returned
  403 for the same key. FreeRouter's `probeProviderCredential` uses `/models` for NVIDIA, so it can mark an invalid
  key `healthy` at save time. Probe with a **1-token chat call** (as in §8).
- **Connection reuse [R]:** Quotient uses `urllib.request.urlopen` per call: new TCP+TLS handshake each time, no pool.
  Use one long-lived `httpx.Client` (or `requests.Session`) with keep-alive. Reference: `max_keepalive_connections=20`,
  `max_connections=40`, timeouts `connect 10 / read 120 / write 30 / pool 30`.
- **Timeouts:** Quotient `REQUEST_TIMEOUT_SECONDS = 300` is a *socket* timeout per read, not a wall clock. Put a wall
  clock deadline on the whole logical call (§7, finding F1).

---

## 7. Caching

| Layer | State today | Notes |
| --- | --- | --- |
| NIM server-side prefix cache | **Automatic, model dependent** [V] | `usage.prompt_tokens_details.cached_tokens` was 32 and 48 (of ~50 prompt tokens) on Laguna, 0 of 23 on Ultra for a trivial prompt. No request flag needed. |
| Request shape for cache hits | [Q] Reasoner puts the stable prefix (prompt body + schema) in `system` and the volatile payload in `user` | Keep it that way: **static content first, per-request data last**. Don't put timestamps/ids in the system message. |
| Bedrock cache markers | Built by Reasoner (`prompt_cache_options`, `prompt_cache_breakpoint`, 30 m) but **dropped** by `NimTransport.build_body` | Harmless; NIM ignores them. Don't rely on them for NIM. |
| Result/response cache for LLM calls | **None** for NIM calls [Q] | `cache/artifacts/*` is a *media* cache (Sonic/Pegasus, keyed by media), not LLM output. |
| Key list | Cached for the process (`_KEYS`), refreshed only by `load_keys(refresh=True)` | See F4. |
| FreeRouter classifier | Redis, 900 s, key `fr:v1:jev:cache:<hash>` [F] | Only the optional category classifier, not completions. |
| Telemetry | `cached_tokens` surfaced via `ModelTurn.cached_tokens` | Prompt/completion token counts are discarded (F6). |

Do not cache by prompt text alone across users/meetings; scope the key (Quotient scopes media cache by subject).

---

## 8. Operations: probes, audit, secrets

- **Key probe (correct):** 1-token chat call with `poolside/laguna-xs-2.1`, `max_tokens:4`. 200 = good, 403 = dead,
  429 = good but cooling. Do not use `/models`. All six configured keys returned 200 on 2026-11-20 [V].
- **Live-model probe:** claim-prompt + real schema, thinking off and on, check `finish_reason` and visible text; record
  headers/first-content/total times; never print keys or generated text. FreeRouter's `pnpm smoke:models` does this.
- **Logging:** `nim call: <model> thinking=on|off HTTP <status> <s>s` to stderr for any call ≥ 15 s or ≥ 400. No key,
  no prompt. Optional structured audit `llm/nim-chat` when `QUOTIENT_AUDIT_LOG` is set. [Q]
- **Redaction:** any text derived from upstream is passed through `re.sub(r"nvapi-[A-Za-z0-9_\-]+", "[key]", …)[:200]`
  before it is stored or raised. [Q]
- **AWS:** secret `axion-meeting-staging/nim`, read by API and worker task roles only; passed as `NIM_SECRET_ARN`.
  Rotate with `aws secretsmanager put-secret-value`, **then restart workers** (F4). [Q]
- **Env precedence:** `NVIDIA_NIM_API_KEYS`, then `NVIDIA_NIM_API_KEY_1..9`, then the secret; de-duplicated in that order. [Q]

---

## 9. Reference client [R] (verified live 2026-11-20)

Single file, `httpx` only. Implements the Quotient contract plus: non-blocking key acquisition, `Retry-After`,
pooled connections and streaming with failover only before the first token. Its `budget_s` bounds key *waits* only (read timeout 120 s per read, no total cap on an in-flight call: same gap as F1).
Live checks that passed: completion, stream (first token 0.84 s on Ultra), bad key first → retired and next key used,
unknown model → falls to Laguna, strict schema with `uniqueItems`, exhaustion message free of keys, and 3 calls with
`per_minute=1` over 3 keys finishing in 2.6 s (no 60 s stall).

```python
# Motivation vs Logic
# Motivation: call NVIDIA NIM with a pool of keys and a fallback chain of models without stalling on one key,
# without leaking keys, and with streaming. Callers should see one stream()/complete() call and nothing else.
# Logic: _acquire picks any key with window capacity and no cooldown for the model (sleeps only when all are busy);
# _fail maps HTTP status to key retirement, (key, model) cooldown (Retry-After honoured) or model demotion;
# stream() walks models (demoted last) x keys (<=3 per model, <=7 dispatches) and fails over only before the
# first visible token; complete() assembles the stream and strips <think> blocks.
"""Reference NIM router: keys x models, paced, cooled, streamed. httpx only."""
from __future__ import annotations

import json, os, random, re, threading, time
from collections import deque

import httpx

BASE = "https://integrate.api.nvidia.com/v1"
STRIP = frozenset({"uniqueItems", "$schema", "$id", "title"})   # grammar keywords NIM cannot express
NAME_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"})
THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class Exhausted(RuntimeError):
    pass


def load_keys() -> list[str]:
    keys = [k for k in re.split(r"[,\s]+", os.environ.get("NVIDIA_NIM_API_KEYS", "")) if k]
    keys += [os.environ.get(f"NVIDIA_NIM_API_KEY_{i}", "").strip() for i in range(1, 10)]
    return list(dict.fromkeys(k for k in keys if k))          # de-duplicated, order kept


def strip_schema(node):
    """Drop keywords, never property names: a property called "title" is data."""
    if isinstance(node, dict):
        return {k: ({n: strip_schema(s) for n, s in v.items()} if k in NAME_MAPS and isinstance(v, dict) else strip_schema(v))
                for k, v in node.items() if k not in STRIP}
    return [strip_schema(i) for i in node] if isinstance(node, list) else node


class Nim:
    def __init__(self, keys: list[str] | None = None, per_minute: int = 30, max_dispatch: int = 7):
        self.keys = keys or load_keys()
        if not self.keys:
            raise Exhausted("no NVIDIA_NIM_API_KEY_n configured")
        self.per_minute, self.max_dispatch = per_minute, max_dispatch
        self.lock = threading.Lock()
        self.sent = {k: deque() for k in self.keys}           # monotonic send times, 60 s window
        self.cool: dict[tuple[str, str], float] = {}          # (key, model) -> usable again
        self.bad: set[str] = set()                            # 401/403: retired for this process
        self.dead: dict[str, float] = {}                      # model -> demoted until
        self.http = httpx.Client(base_url=BASE, http2=False, limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
                                 timeout=httpx.Timeout(connect=10, read=120, write=30, pool=30))

    # -- key acquisition: never sleeps on one key while another is free -------------------------------------
    def _acquire(self, model: str, deadline: float) -> str:
        while True:
            now, free_at = time.monotonic(), []
            with self.lock:
                live = [k for k in self.keys if k not in self.bad]
                if not live:
                    raise Exhausted("every key was rejected (401/403)")
                random.shuffle(live)
                for k in live:
                    w = self.sent[k]
                    while w and now - w[0] > 60:
                        w.popleft()
                    ready = max(self.cool.get((k, model), 0.0), 0.0 if len(w) < self.per_minute else w[0] + 60)
                    if ready <= now:
                        w.append(now)
                        return k
                    free_at.append(ready)
            if min(free_at) > deadline:
                raise Exhausted("all keys are paced or cooling past the deadline")
            time.sleep(max(0.05, min(free_at) - now))

    # -- failure policy ------------------------------------------------------------------------------------
    def _fail(self, key: str, model: str, status: int | None, retry_after: str | None) -> str:
        """Record the consequence; return 'key' (try next key), 'model' (next model) or 'shape' (fix the body)."""
        with self.lock:
            if status in (401, 403):
                self.bad.add(key); return "key"
            if status in (404, 410, 413, 503):
                self.dead[model] = time.monotonic() + 120; return "model"
            if status in (400, 422):
                return "shape"
            wait = 120 if status == 402 else 10
            if status in (429, 408, 425):
                wait = min(120, float(retry_after)) if retry_after and retry_after.replace(".", "", 1).isdigit() else 30
            self.cool[(key, model)] = time.monotonic() + wait
            return "key"

    @staticmethod
    def body(model: str, messages: list, *, thinking: bool, max_tokens: int, schema: dict | None, stream: bool) -> dict:
        b = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2, "stream": stream}
        if stream:
            b["stream_options"] = {"include_usage": True}
        if thinking is False:
            b["chat_template_kwargs"] = {"enable_thinking": False}
            if "glm" in model:
                b["reasoning_effort"] = "low"                 # GLM burns small budgets on reasoning otherwise
        if schema:
            b["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": strip_schema(schema), "strict": True}}
        return b

    # -- one logical call: yields ("delta", text) then ("done", usage) ---------------------------------------
    def stream(self, models: list[str], messages: list, *, thinking: bool = False, max_tokens: int = 16384,
               schema: dict | None = None, budget_s: float = 300.0):
        deadline, dispatched, last = time.monotonic() + budget_s, 0, "no attempt"
        now = time.monotonic()
        for model in sorted(dict.fromkeys(models), key=lambda m: self.dead.get(m, 0) > now):   # demoted last, never dropped
            tried = 0
            while tried < 3 and dispatched < self.max_dispatch:
                key = self._acquire(model, deadline)
                tried += 1
                dispatched += 1
                emitted = False
                try:
                    with self.http.stream("POST", "/chat/completions", headers={"authorization": f"Bearer {key}", "accept": "text/event-stream"},
                                          json=self.body(model, messages, thinking=thinking, max_tokens=max_tokens, schema=schema, stream=True)) as r:
                        if r.status_code >= 400:
                            r.read()
                            last = f"{model}: HTTP {r.status_code}"
                            scope = self._fail(key, model, r.status_code, r.headers.get("retry-after"))
                            if scope == "model":
                                break
                            continue
                        usage = {}
                        for line in r.iter_lines():
                            if not line.startswith("data:"):
                                continue                      # comments / keep-alives
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            ev = json.loads(data)
                            usage = ev.get("usage") or usage
                            for c in ev.get("choices") or []:
                                text = (c.get("delta") or {}).get("content")
                                if text:
                                    emitted = True
                                    yield "delta", text
                        if not emitted:                        # reasoning ate the budget: another model may answer
                            last = f"{model}: empty reply"     # budget or model problem: next model, but do not demote globally
                            break
                        yield "done", {"model": model, "usage": usage}
                        return
                except (httpx.TransportError, json.JSONDecodeError) as exc:
                    if emitted:                                # never splice a second model onto visible output
                        raise
                    last = f"{model}: {type(exc).__name__}"
                    self._fail(key, model, None, None)
        raise Exhausted(f"nim-exhausted: {re.sub(r'nvapi-[A-Za-z0-9_-]+', '[key]', last)}")

    def complete(self, *args, **kw) -> tuple[str, dict]:
        parts, meta = [], {}
        for kind, value in self.stream(*args, **kw):
            parts.append(value) if kind == "delta" else meta.update(value)
        text = THINK.sub("", "".join(parts))
        text = text.split("</think>", 1)[1] if "</think>" in text else text
        return text.strip(), meta
```

Usage:

```python
from nim import Nim
n = Nim()                                                     # keys from env, see contract.keys
text, meta = n.complete(
    ["nvidia/nemotron-3-ultra-550b-a55b", "poolside/laguna-xs-2.1", "z-ai/glm-5.3-flash"],
    [{"role": "user", "content": "..."}], thinking=False, max_tokens=16384)
for kind, value in n.stream([...], messages):                 # ("delta", str) ... ("done", {"model","usage"})
    ...
```

Known limits of the reference: no tool-call parsing (add `tools`/`tool_choice` and parse `delta.tool_calls` per §3 and
FreeRouter `normalizeChatEvent`), no `json_object` downgrade or `Unimplemented keys` parsing (port from
`NimTransport._classify`), no local schema validation, no wall-clock cap on an in-flight stream.

---

## 10. Quotient implementation review: defects and hardening

Reviewed against the code at `8914163`; none are fixed by this document. Ordered by impact.

| ID | Finding | Evidence | Fix |
| --- | --- | --- | --- |
| F1 | **Deadline does not bound a call.** `deadline = 90 + 300·2` is passed only to `wait_for`. Each of up to 7 dispatches can block 300 s on the socket, so the worst case is ~2 100 s. | `nim.py` `respond`, `_post` | Wall-clock budget checked before every dispatch; shrink the per-request timeout to the time left. |
| F2 | **Ranking ignores pacing, and a full key blocks.** `_rank` shuffles keys; `wait_for` then sleeps up to 60 s on the chosen key while other keys are idle. | `_rank`, `_State.wait_for` | Acquire non-blockingly across all ranked keys, sleep only when all are full (reference `_acquire`; verified). |
| F3 | **`Retry-After` is dropped.** `_classify` receives only the body, headers are never read. | `_post`, `_classify` | Pass `exc.headers`; use `min(120, Retry-After)` for 429. |
| F4 | **Keys never refresh.** `_KEYS` is cached for the process and 401/403 retirement is permanent, so a rotated secret needs a worker restart; one bad probe retires a key forever. | `load_keys`, `_State.invalid` | TTL on `_KEYS` (e.g. 5 min) and a timed retirement (e.g. 10 min) with a re-probe. |
| F5 | **One request can demote a model for everyone.** An "empty reply" caused by that request's small budget (`finish_reason:"length"`) marks the model dead for 120 s process-wide. | `_post`, `respond` | Demote only on 404/410/503 and on empty replies with `finish_reason != "length"`; otherwise treat `length` as a budget error. |
| F6 | **Usage telemetry is thrown away.** Only `cached_tokens` is kept. | `parse_response` | Keep `prompt_tokens`, `completion_tokens`, `reasoning_tokens` for cost and speed tracking. |
| F7 | **No connection reuse, no streaming.** New handshake per call; first byte unobservable. | `_post` | §6 and §5. |
| F8 | **Doc drift.** `loop/pool.py` header says default width 10; code returns 2–6. `model-routing.md` says one schema retry; code allows two reshapes. | `pool.py`, `nim.py` | Align the docs. |
| F9 | **Sibling bug (FreeRouter).** `probeProviderCredential` validates NVIDIA keys with `GET /models`, which accepts any string. | live, §6 | Probe with a 1-token chat call. |

Strengths worth copying: transport-compatible `respond()`; allow-listed overrides; keyword-vs-property-name schema
stripping with a regression test; strict fall-through ladder (same model → json_object → next model); redacted errors;
process-wide shared state; 23 unit tests with a scripted fake network (`tests/worker/test_nim.py`, all pass).

---

## 11. Key takeaways

1. **Rotate on two axes.** Keys fail on 429/402/403; models fail on 404/503/empty. Cool the *(key, model)* pair, demote
   the *model*, and retire the *key* only on 401/403.
2. **Thinking off is the speed lever** (`chat_template_kwargs.enable_thinking=false`): Ultra goes 25–60 s → ~5 s.
3. **Always set `max_tokens`**, and treat an empty 200 as a failure.
4. **Strip schema keywords, not property names**, and always validate locally against the original schema.
5. **Pace client-side**: NIM gives no rate-limit headers; stay near 30 rpm/key and pick any key with capacity.
6. **Do not probe keys with `/models`.** Use a 1-token chat call; invalid keys get **403**.
7. **Failover before the first token only** when streaming.
8. **Never leak a key**: redact `nvapi-…` in every error, log and audit field.
9. **State is process-local.** For several workers or restarts, move cooldown/health to shared storage (FreeRouter §4.5).
10. **Probes age fast.** Model status and speeds are dated 2026-11-11/20; re-run the live probe before changing a plan.

---

## 12. Agent checklist

```yaml
before_coding:
  - read: [apps/worker/bedrock/nim.py, apps/worker/bedrock/provider.py, tests/worker/test_nim.py]
  - confirm: keys present (names only, never values)
implement:
  - keep respond(request)->response contract; add models only via NIM_MODELS + a probe row in docs/model-routing.md
  - schema: strip keywords only; validate locally
  - failures: use the §4.2 matrix; add a test per row
  - never: hardcode semantic routing, log keys, return keys to clients
validate:
  - unit: .venv/bin/python -m pytest tests/worker/test_nim.py
  - live: 1-token chat per key; claim probe per model, thinking off and on
  - trace: confirm fallback order, cooldown and demotion in logs
done_when: all rows of the failure matrix covered by tests and one live run shows key + model failover
```
