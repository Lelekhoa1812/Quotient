# Model routing: AWS Bedrock and NVIDIA NIM

The text analysis (statement extraction, evidence checks, lenses, the walkaway digest, who-is-who) can run on
**AWS Bedrock** (Claude Haiku 5.5, the pinned release and the default) or on **NVIDIA NIM**. The choice is made in
**Settings → Models**, is stored in the browser, and is sent with each meeting when it is started. A meeting records the
provider it used; changing the setting never changes a running meeting.

What the switch does **not** cover: audio transcription (Amazon Nova Sonic) and the video scan (TwelveLabs Pegasus and the
frame reader) always use Bedrock, because NIM has no equivalent. A **transcript upload** needs neither, so on NIM it uses no
Bedrock at all.

## How routing works

`apps/worker/bedrock/provider.py` holds a `RolePlan` per role. The two roles come from the prompt registry:

| Role | Used for | NIM plan |
| --- | --- | --- |
| `slm` (easy, bounded) | claim extraction, counter-evidence, coverage, most lenses, answer checks, who-is-who | `nemotron-3-ultra-550b-a55b`, **thinking off**, 16k output |
| `llm` (complex, long reasoning) | entailment, supplementary findings, digest and its review, risk, stakeholder and dependency lenses | `nemotron-3-ultra-550b-a55b`, **thinking on**, 32k output |

`apps/worker/bedrock/nim.py` (`NimTransport`) has the same `respond(request)` contract as the Bedrock transport, so the
Reasoner is unchanged. It routes each call the way FreeRouter does:

1. Keys come from `NVIDIA_NIM_API_KEY_1..9` / `NVIDIA_NIM_API_KEYS` (local `.env`) or the Secrets Manager secret named by
   `NIM_SECRET_ARN` (AWS). A key is picked at random among those not cooling down; each key is paced to 30 requests a
   minute (NVIDIA's free tier is about 40).
2. On HTTP 429 the key cools down for that model (30 s). 401/403 retires the key for the process. 402 cools it for 2 min.
   5xx and transport errors move to the next key.
3. A 400 that names unsupported schema keywords (`Unimplemented keys: ["uniqueItems"]`) is retried once on the same model
   with those keywords removed; any other format rejection falls back to JSON-object mode (the schema is already in the
   prompt and the Reasoner validates the result either way).
4. 404/410/413/503 or an **empty reply** (a reasoning model that spent its whole budget thinking) moves to the next model in
   the plan: ultra → super → laguna → GLM for `slm`; ultra → nano → super → GLM for `llm`. At most 7 dispatches per call.
5. If everything fails the meeting fails with "NVIDIA NIM did not answer after trying every model and key."

## Evidence (live probes, 2026-11-11, Quotient claim prompt + real schema, 3 spans from the 10 Nov meeting)

Strict `json_schema` was rejected by every NIM model until `uniqueItems` was removed from the schema. After that:

| Model | Thinking off | Thinking on | Verdict |
| --- | --- | --- | --- |
| `nvidia/nemotron-3-ultra-550b-a55b` | 5 s, valid, 3–6 claims | 25–28 s, valid, 6 claims | **Primary** for both roles |
| `nvidia/nemotron-3.5-super-vl-120b-a12b` | 2 s, valid, 3 claims | 60 s, valid, 5 claims (empty at 4k max tokens) | Fallback; thinking budget must be large |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | 3 s, valid (invalid in JSON-object mode: `null` enum) | 59 s, valid, 4 claims | Fallback for `llm`; 256k context |
| `poolside/laguna-xs-2.1` | 2–3 s, valid, 2–3 claims | n/a (no thinking mode) | Fast fallback; fewer claims per pass |
| `z-ai/glm-5.3-flash` | 9–11 s, valid, 3–4 claims | not tested | Last fallback; 1M context |
| `deepseek-ai/deepseek-v4.1-flash` | HTTP 500 | empty content | **Not offered** |

Agreement with FreeRouter's own evidence (`src/lib/models/catalog.ts`, `docs/OPERATIONS.md`): its "ready" NVIDIA models are
the first four rows; DeepSeek V4.1 Flash fails the schema probe there too; GLM 5.3 Flash is slow through a gateway but passes
when called directly. FreeRouter never injects `max_tokens`; Quotient sets it explicitly because reasoning models otherwise
return no visible answer.

## Where the choice lives

- Browser: `localStorage["quotient.models.v1"]` = `{ provider, overrides }`.
- MCP: `submit_meeting` takes `model_provider` (`bedrock` | `nim`) and `model_overrides` (`{ slm?, llm? }`, proven NIM models
  only). `model_options` lists providers, availability and the model list. Server default: `QUOTIENT_MODEL_PROVIDER`
  (unset = Bedrock).
- Row: `model_provider`, `model_overrides`. Reindex reuses the row's provider.
- AWS: secret `axion-meeting-staging/nim` (JSON `{"keys": ["nvapi-…", …]}`), read by the API and worker roles only.
