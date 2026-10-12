# Component inventory

Maps architectural components to repository evidence and diagram IDs (`D01`–`D11` in [ARCHITECTURE.md](./ARCHITECTURE.md)).

Legend: **Implemented** = invoked in normal local path; **Partial** = exists but not on main path; **CDK-only** = in infra template, not referenced from `apps/`; **Planned** = documented intent without implementation evidence.

## Entry points

| Component | Path | Symbols | Diagrams | Status |
| --- | --- | --- | --- | --- |
| API process main | `apps/api/quotient/__main__.py` | `main()` L6 | D01, D02 | Implemented |
| ASGI factory | `apps/api/quotient/app.py` | `create_app` L31, `_Runtime` L75 | D01, D02 | Implemented |
| Local launcher | `scripts/start-local.sh` | `launch_api`, `launch_web` | D01 | Implemented |
| CDK synth entry | `infra/cdk/app.py` | `StagingStack` | D10 | CDK-only deploy |
| Portal dev server | `apps/web/package.json` | `next dev` | D11 | Implemented |

## API — MCP and HTTP

| Component | Path | Symbols | Diagrams | Status |
| --- | --- | --- | --- | --- |
| MCP routes | `apps/api/quotient/mcp/server.py` | `mcp_routes`, `_dispatch`, `_authorize` | D02, D07 | Implemented |
| Tools catalog | `apps/api/quotient/mcp/tools.py` | `TOOLS`, `_submit`, `_HANDLERS` | D02, D07 | Implemented |
| Task board | `apps/api/quotient/mcp/tasks.py` | `TaskBoard`, `TaskRecord`, `MAX_CONCURRENT=8` | D02, D07 | Implemented |
| Submit job runner | `apps/api/quotient/mcp/jobs.py` | `run_submit`, `sync_task` | D07 | Implemented |
| Resources | `apps/api/quotient/mcp/resources.py` | `read_resource`, `TEMPLATES` | D02 | Implemented |
| Partner prompts | `apps/api/quotient/mcp/prompts.py` | `brief_this_meeting`, etc. | D02 | Implemented |
| Sessions / SSE | `apps/api/quotient/mcp/session.py` | `SessionStore`, `Session` | D02 | Implemented |
| OAuth metadata | `apps/api/quotient/auth/metadata.py` | `AuthSettings`, `load_auth_settings` | D01 | Implemented |
| Token verify | `apps/api/quotient/auth/context.py` | `CognitoVerifier`, `local_context` | D01 | Implemented |
| Integration `/v1` | `apps/api/quotient/public/routes.py` | `public_routes`, `jobs_collection` | D01 | Implemented |
| API keys | `apps/api/quotient/public/keys.py` | `KeyDirectory`, `verify` | D01 | Implemented |
| Integration jobs | `apps/api/quotient/public/jobs.py` | `JobBoard`, `ObjectJobs` | D01 | Partial (Dynamo when `JOBS_TABLE` set) |
| Partner projection | `apps/api/quotient/graph/gate.py` | `project_meeting`, `DIMENSIONS` | D01, D05 | Implemented |
| Export render | `apps/api/quotient/export/project.py` | `render_local`, `EXPORTS` | D01 | Implemented |
| Captions | `apps/api/quotient/export/captions.py` | `webvtt`, `srt` | D01 | Implemented |
| PDF/HTML markup | `apps/api/quotient/export/markup.py`, `diagram.py` | `render_markdown`, `svg_for` | D01 | Implemented |

## API — worker boundary

| Component | Path | Symbols | Diagrams | Status |
| --- | --- | --- | --- | --- |
| WorkerPort protocol | `apps/api/quotient/worker/port.py` | `WorkerPort`, `load_worker_port` | D01, D02 | Implemented |
| Memory fallback | `apps/api/quotient/worker/memory.py` | `MemoryPort` | D01 | Implemented (non-local degrade) |

## Worker — orchestration

| Component | Path | Symbols | Diagrams | Status |
| --- | --- | --- | --- | --- |
| Port / ledger | `apps/worker/quotient/port.py` | `Port`, `submit`, `_analyze`, `_run_meeting`, `_project`, `run_quality` | D01, D03, D06, D07 | Implemented |
| Staging seed | `apps/worker/quotient/seed.py` | seed loader | D01 | Partial (staging boot) |
| Quality loop | `apps/worker/loop/quality.py` | `run`, `Budget`, stage functions | D03, D05 | Implemented |
| Ingest | `apps/worker/loop/ingest.py` | `assemble`, `_assemble` | D03 | Implemented |
| Checkpoint store | `apps/worker/loop/store.py` | `MemoryStore` | D01, D03 | Implemented (in-process) |
| Tool rounds | `apps/worker/loop/tools.py` | `complete_with_open_span` | D03 | Implemented |
| Thread pool | `apps/worker/loop/pool.py` | `map_ordered`, `width` | D03 | Implemented |

## Worker — graph / domain

| Component | Path | Symbols | Diagrams | Status |
| --- | --- | --- | --- | --- |
| Graph types | `apps/worker/graph/state.py` | `Claim`, `Finding`, `Action`, … | D08 | Implemented |
| Claim finalize | `apps/worker/graph/claim.py` | `finalize_claim`, `confidence_of` | D04 | Implemented |
| Quote resolve | `apps/worker/graph/quote.py` | `resolve_quote` | D04 | Implemented |
| Publish gate | `apps/worker/graph/publish.py` | `gate`, `GateResult` | D05 | Implemented |
| Lenses | `apps/worker/graph/lenses.py` | `run_lenses`, `LENS_ORDER` via `registry/ids.py` | D03, D09 | Implemented |
| Synthesis | `apps/worker/graph/synth.py` | `synthesis_payload`, `dissent_payload` | D03 | Implemented |
| Actions | `apps/worker/graph/actions.py` | `ground_action`, `merge_actions` | D03 | Implemented |
| Digest ground | `apps/worker/graph/digest.py` | `ground_digest` | D03 | Implemented |
| Cross-modal | `apps/worker/graph/cross.py` | `record_cross` | D03 | Implemented |
| Charts spec | `apps/worker/graph/chart.py` | `compute`, `reject_numeric_literals` | D03 | Implemented |
| Prose scrub | `apps/worker/graph/prose.py` | `normalize` | D03 | Implemented |
| Screen use | `apps/worker/graph/screenuse.py` | reading validation | D03 | Implemented |

## Worker — media & identity

| Component | Path | Symbols | Diagrams | Status |
| --- | --- | --- | --- | --- |
| Probe / plan | `apps/worker/media/probe.py` | `probe`, `classify_file`, `model_plan` | D03 | Implemented |
| PCM extract | `apps/worker/media/pcm.py` | `write_pcm` | D03 | Implemented |
| Storage / S3 | `apps/worker/media/storage.py` | `download`, presign helpers | D01, D03 | Implemented |
| Diarization | `apps/worker/media/diarize.py` | `diarize_pcm`, `attach_speakers` | D03 | Implemented |
| Artifact cache | `apps/worker/media/artifacts.py` | `ArtifactCache` | D03 | Implemented |
| Compaction index | `apps/worker/media/compact.py` | `IndexedSpan`, `apply_omissions` | D03 | Implemented |
| Visual frames | `apps/worker/visual/frames.py` | `FrameReader` | D03 | Implemented |
| Identity reconcile | `apps/worker/identity/resolve.py` | `resolve_visual`, `reconcile` | D03 | Implemented |
| Context library | `apps/worker/context/loader.py`, `library.py`, `convert.py` | `load_library`, `to_markdown` | D03 | Implemented |

## Worker — models & registry

| Component | Path | Symbols | Diagrams | Status |
| --- | --- | --- | --- | --- |
| Registry | `apps/worker/registry/load.py` | `Registry`, `prompt`, `schema` | D09 | Implemented |
| Validation | `apps/worker/registry/check.py` | `validate_json` | D09 | Implemented |
| Route ids | `apps/worker/registry/ids.py` | `SONIC`, `CLAIM`, lens constants | D09 | Implemented |
| Reasoner | `apps/worker/bedrock/reason.py` | `Reasoner.complete` | D03, D09 | Implemented |
| Transport | `apps/worker/bedrock/wire.py` | `Transport`, `_SonicSession` | D03 | Implemented |
| Limits / pins | `apps/worker/bedrock/limits.py` | model ids, regions | D03 | Implemented |
| Sonic client | `apps/worker/sonic/client.py` | `SonicClient.transcribe` | D03 | Implemented |
| Sonic cache | `apps/worker/sonic/cache.py` | `TranscriptCache` | D03 | Implemented |
| Pegasus client | `apps/worker/pegasus/client.py` | `PegasusClient.analyze` | D03 | Implemented |
| Pegasus windows | `apps/worker/pegasus/parts.py` | `window_parts` | D03 | Implemented |
| JEV sort/rank | `apps/worker/jev/sort.py`, `rank.py`, `client.py` | `apply_order`, `rank_digest` | D03 | Optional |
| Portal charts | `apps/worker/chart/sandbox.py` | `portal_charts`, `render_svg` | D03, D11 | Implemented |
| Errors | `apps/worker/errors.py` | `SchemaRejected`, `NoSpeech`, … | D03 | Implemented |
| Audit helper | `apps/worker/audit.py` | call metadata | D01 | Partial (`--logs`) |

## Contracts

| Component | Path | Symbols | Diagrams | Status |
| --- | --- | --- | --- | --- |
| Route registry | `contracts/registry.json` | `routes[]`, `models` | D09 | Implemented |
| Prompt bodies | `contracts/prompts/*.yaml` | per `prompt_id` | D09 | Implemented |
| JSON schemas | `contracts/schemas/*.json` | per `schema_id` | D09 | Implemented |

## Web portal

| Component | Path | Symbols | Diagrams | Status |
| --- | --- | --- | --- | --- |
| MCP client | `apps/web/lib/mcp/client.ts` | `connect`, tool wrappers | D11, D07 | Implemented |
| Graph parser | `apps/web/lib/graph.ts` | `parseGraph`, `parseMeetingStatus` | D11 | Implemented |
| Workspace | `apps/web/components/meeting/workspace.tsx` | `VIEWS`, polling | D11 | Implemented |
| Overview / digest | `apps/web/components/meeting/overview.tsx` | walkaway UI | D11 | Implemented |
| Insights | `apps/web/components/meeting/insights.tsx` | `lib/analytics.ts` | D11 | Implemented |
| Upload | `apps/web/lib/mcp/upload.ts`, `home.tsx` | elicitation flow | D07, D11 | Implemented |
| Settings route | `apps/web/app/api/settings/route.ts` | `.env` mutation | D11 | Implemented (local) |
| MCP proxy | `apps/web/next.config.mjs` | `/mcp` rewrite | D11 | Implemented |

## Infrastructure (CDK)

| Component | Path | Symbols | Diagrams | Status |
| --- | --- | --- | --- | --- |
| Staging stack | `infra/cdk/quotient/stack.py` | `StagingStack` | D10 | CDK-only |
| VPC | `infra/cdk/network/vpc.py` | `MeetingVpc` | D10 | CDK-only |
| Buckets | `infra/cdk/storage/buckets.py` | `MeetingBuckets` | D10 | CDK-only |
| Tables | `infra/cdk/storage/tables.py` | `MeetingTables` | D10 | CDK-only |
| ECS cluster | `infra/cdk/compute/cluster.py` | `MeetingCompute` | D10 | CDK-only |
| Cognito | `infra/cdk/auth/pool.py` | `MeetingAuth` | D10 | CDK-only |
| Work queue | `infra/cdk/workflow/queue.py` | `WorkQueue` | D10 | CDK-only |
| State machine | `infra/cdk/workflow/machine.py` | `MeetingMachine` | D10 | CDK-only (no `apps/` consumer) |
| IAM roles | `infra/cdk/identity/roles.py` | `TaskRoles` | D10 | CDK-only |

## Tests (architectural role)

| Suite | Path | Role |
| --- | --- | --- |
| Worker | `tests/worker/` | Pipeline, gates, media, digest |
| API | `tests/api/` | MCP, auth, exports |
| Contracts | `tests/contracts/` | Schema/prompt drift |
| JEV | `tests/jev/` | Sort/rank client |
| Web unit | `apps/web/tests/*.test.ts` | Parsers, analytics, guard |
