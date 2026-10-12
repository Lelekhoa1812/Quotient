# Execution traces

Verified end-to-end paths from repository code. Each trace lists entry → control flow → persistence → outputs → failure modes.

Diagram cross-refs: [ARCHITECTURE.md](./ARCHITECTURE.md) (`D07` sequence, `D03` pipeline).

---

## Trace T1 — Local boot

| Step | Location | Behavior |
| --- | --- | --- |
| 1 | `scripts/start-local.sh` | Load `.env`, require Bedrock env names, set `QUOTIENT_ENVIRONMENT=local`, `QUOTIENT_AUTH_BYPASS=1`, `PYTHONPATH=apps/api:apps/worker` |
| 2 | Same | `uvicorn quotient.app:create_app` on `127.0.0.1:8080` |
| 3 | Same | `next dev` on `127.0.0.1:3000` |
| 4 | `apps/api/quotient/app.py` | `create_app` → `load_worker_port()` → `Port` from `apps/worker/quotient/port.py` |
| 5 | Startup lifespan | `runtime.board.fail_orphans()` |

**Outputs:** MCP at `http://127.0.0.1:8080/mcp`, portal at `:3000`.

**Failures:** missing `.env` keys → script exit; worker import failure in local → raise (`worker/port.py`).

---

## Trace T2 — MCP `submit_meeting` (portal upload)

| Step | Location | Behavior |
| --- | --- | --- |
| 1 | `apps/web/lib/mcp/client.ts` | `initialize` → session id; optional SSE for elicitation |
| 2 | `apps/web/components/home.tsx` | `submitMeeting` with `upload_complete: false` |
| 3 | `mcp/server.py` `_tools_call` | Routes to `_submit` |
| 4 | `mcp/jobs.py` `run_submit` | `port.submit(...)` sync; asyncio poll `port.meeting` every 0.25s |
| 5 | `quotient/port.py` `submit` | Row `queued`; may return existing id for `(subject, idempotency_key)` |
| 6 | Elicitation | Task `input_required`; portal PUT to signed URL (`upload.ts`) |
| 7 | `Port.submit` continue | Download from `uploads/{task_id}/...` if needed (`storage.download`) |
| 8 | `Port._analyze` | Daemon thread `quotient-analysis`; status `working` |
| 9 | `_run_meeting` | `assemble` → context → identity → `run_quality` → `_project` |
| 10 | `run_submit` | On `ready` or `needs_review`, task `completed` with meeting id |
| 11 | Portal | `/tasks/{taskId}` → `/meetings/{id}`; workspace loads `get_meeting` + `read_graph` |

**Outputs:** Meeting row in `.local/run/meetings.json` (local); MCP task result; graph resources after projection.

**Failures:** `failed` status with message on `_fail`; cancel stops in-flight model work (`cancel`); upload timeout `QUOTIENT_UPLOAD_TIMEOUT_SECONDS`.

---

## Trace T3 — MCP `submit_meeting` (derivatives CLI path)

| Step | Location | Behavior |
| --- | --- | --- |
| 1 | Partner `tools/call` | `object_key: derivatives/...`, `upload_complete: true` |
| 2 | `loop/ingest.resolve_object` | Path must be under `derivatives/` relative to repo |
| 3 | Continue as T2 from `assemble` | No elicitation if upload already complete |

**Failures:** missing file → port error surfaced to task/client.

---

## Trace T4 — Quality loop (single analysis run)

| Step | Location | Behavior |
| --- | --- | --- |
| 0 | `loop/quality.run` | Checkpoint hit → return stored `GateResult` (`loop/store.py`) |
| 1 | `_require_speech` | Long silent recordings → `NoSpeech` |
| 2 | Compaction | `media/compact.apply_omissions` via registry route `compaction` |
| 3 | `_cross` | `graph/cross.record_cross` |
| 4 | `_extract` | Claims; `untranscribed` → gaps |
| 5 | `_coverage` | Omissions + supplement pass |
| 6 | `run_lenses` | Ten dimensions, parallel width `loop/pool.width()` |
| 7 | `_apply_decisions` | Lens enum → claim status |
| 8 | `_synthesize` | Brief sentences + dissent omissions |
| 9 | `_actions` | `ground_action`, merge durable |
| 10 | `_digest` | Model digest → `ground_digest` → review → answer_check → `rank_digest` → screenuse |
| 11 | `_chart` | Schema chart → `graph/chart.compute` |
| 12 | `gate` | `ready` vs `needs_review`; may null brief on ceiling |
| 13 | `jev/sort.apply_order` | Reorder review queue only |

**Outputs:** `GateResult` with spans, claims, synthesis, digest, charts, artifact flags.

**Failures:** `SchemaRejected` / timeout → stage retry once; `budget.hit` → ceiling; queued claim in brief → `RuntimeError` → meeting `failed`.

---

## Trace T5 — Ingest / media parallel path

| Step | Location | Behavior |
| --- | --- | --- |
| 1 | `probe` + `model_plan` | Audio vs video plan |
| 2 | PCM + silence + optional S3 derivative clip | |
| 3 | Video: parallel Sonic, Pegasus, diarize, frames | Audio: Sonic + diarize only |
| 4 | `SonicClient.transcribe` | Real-time stream; cache under `QUOTIENT_TRANSCRIPT_CACHE_DIR` |
| 5 | `PegasusClient.analyze` | Skipped if MinIO without `QUOTIENT_PEGASUS_BUCKET` |
| 6 | `diarize_pcm` | Local pyannote; HF model download only |
| 7 | `resolve_visual` + `attach_speakers` | Ledger populated |

**Failures:** IAM expiry mid-transcribe; content filter → `untranscribed` spans; ffmpeg errors from probe/pcm.

---

## Trace T6 — MCP `read_graph` / resources

| Step | Location | Behavior |
| --- | --- | --- |
| 1 | `mcp/tools.py` `_read_graph` or `resources/read` | `_owned` → `port.meeting` |
| 2 | `graph/gate.py` `project_meeting` / `page_graph` | Strip denied keys; verify citations against span text |
| 3 | Brief resource | Withheld unless `ready` (partial export rules in `export/project.py`) |

**Failures:** wrong subject → not found; invalid citation dropped from published view.

---

## Trace T7 — Human revision tools

| Step | Location | Behavior |
| --- | --- | --- |
| 1 | `revise_text` / `revise_speaker` / `merge_speakers` | `Port` mutates row + `revisions` cap 5000 |
| 2 | `reindex_meeting` | New checkpoint key; status `queued`; may restore on cancel |
| 3 | `accept_action` | `proposed` → `accepted` only |
| 4 | Workspace `reload` | Re-fetch meeting + graph |

**Outputs:** Updated row persisted via `_save_locked` (local file).

---

## Trace T8 — Integration API `/v1/jobs`

| Step | Location | Behavior |
| --- | --- | --- |
| 1 | `public/routes.py` | Bearer `KeyDirectory.verify` → subject `key:{id}` |
| 2 | `JobBoard.create` | Persist job row (file or Dynamo + S3) |
| 3 | `job_submit` | `port.submit` synchronous on request thread |
| 4 | Poll `GET /v1/jobs/{id}` | `project_result` shapes analysis sections |

**Note:** Parallel to MCP task path; same `Port.submit` backend.

---

## Trace T9 — Export download

| Step | Location | Behavior |
| --- | --- | --- |
| 1 | Portal `exports.tsx` or MCP `resources/read` | `quotient://meetings/{id}/exports/{name}` |
| 2 | `export/project.py` | `render_local` except `burned.mp4` |
| 3 | Worker | `export_bytes` for burned video when worker produced it |

---

## Trace T10 — Staging ECS (documented gap)

| Step | Evidence | Behavior |
| --- | --- | --- |
| 1 | `infra/cdk/compute/cluster.py` | ALB routes `/mcp` (SSE) and `/v1` to API task |
| 2 | README Known limitations | Meeting state in API process, not DynamoDB |
| 3 | Grep `STATE_MACHINE` in `apps/` | **No matches** — SFN not driven by application code in this repo |

Treat staging as **deployed infrastructure** with **local-equivalent analysis threading** only where operator runs the same Python images; durable state and queue-orchestrated worker path are **not** verified in `apps/`.
