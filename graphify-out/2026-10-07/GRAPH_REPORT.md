# Graph Report - meeting  (2026-10-07)

## Corpus Check
- 201 files · ~89,660 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1927 nodes · 4147 edges · 130 communities (98 shown, 29 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 270 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- sort.py
- properties
- MemoryPort
- home.tsx
- isolation.py
- meeting.chart.v1.json
- metadata.py
- meeting.synthesis.v1.json
- meeting.pegasus.continue.v1.json
- meeting.compaction.v1.json
- meeting.dissent.v1.json
- compilerOptions
- meeting.counterevidence.v1.json
- meeting.coverage.v1.json
- meeting.entailment_luna.v1.json
- meeting.entailment.v1.json
- meeting.supplement.v1.json
- Reasoner
- gate.py
- react
- client.ts
- delete-cache.sh
- ingest.py
- meeting.lens_commitment.v1.json
- meeting.lens_cross_modal.v1.json
- meeting.lens_decision.v1.json
- meeting.lens_dependency.v1.json
- meeting.lens_documentary.v1.json
- meeting.lens_gap.v1.json
- meeting.lens_question.v1.json
- meeting.lens_risk.v1.json
- meeting.lens_stakeholder.v1.json
- meeting.lens_temporal.v1.json
- __main__.py
- auth/__init__.py
- export/__init__.py
- graph/__init__.py
- worker/__init__.py
- next-env.d.ts
- media/__init__.py
- registry/__init__.py
- quotient-api
- quality.py
- properties
- TaskRecord
- wire.py
- mcp.tsx
- Quotient MCP
- open_session
- meeting.pegasus.v1.json
- registry
- Session
- TaskRoles
- project.py
- sandbox.py
- shell.tsx
- MeetingCompute
- WorkerPort
- package.json
- transcript.tsx
- stack.py
- workspace.tsx
- StagingStack
- Registry
- state.py
- PegasusClient
- server.py
- Workspace
- contracts/schemas/meeting.pegasus.v1.json
- numbers.py
- Quotient staging
- quotient/app.py
- MeetingMachine
- fixtures/contracts/schemas/meeting.entailment.v1.json
- MeetingBuckets
- route.ts
- meeting.crossmodal.v1.json
- BillingAlarms
- MeetingLogs
- next.config.mjs
- api/quotient/__init__.py
- mcp/__init__.py
- css.d.ts
- bedrock/__init__.py
- worker/graph/__init__.py
- loop/__init__.py
- pegasus/__init__.py
- sonic/__init__.py
- cdk/auth/__init__.py
- compute/__init__.py
- network/__init__.py
- ops/__init__.py
- cdk/quotient/__init__.py
- storage/__init__.py
- workflow/__init__.py
- meeting.sonic.v1.json
- Port
- test_sort.py
- start-local.sh
- stop-local.sh
- pegasus/client.py
- mcp/tools.py
- Span
- sonic/client.py
- auth.py
- test_gates.py
- markdown.tsx
- meeting.review_sort.v1.json
- home-object.tsx
- IndexedSpan
- quotient/port.py
- statusLabel
- classify_file
- skills.tsx
- format.ts
- diagram.tsx
- settings.tsx
- write_pcm
- jobs.py
- SchemaRejected
- dependencies
- chart/__init__.py
- jev/__init__.py
- devDependencies
- test_prose.py
- cross.py
- PortError

## God Nodes (most connected - your core abstractions)
1. `Registry` - 39 edges
2. `asRecord()` - 35 edges
3. `ChartRejected` - 35 edges
4. `asString()` - 32 edges
5. `Span` - 32 edges
6. `run()` - 31 edges
7. `project_meeting()` - 29 edges
8. `MemoryPort` - 26 edges
9. `Session` - 23 edges
10. `TaskRecord` - 23 edges

## Surprising Connections (you probably didn't know these)
- `test_bedrock_respond_appends_status_without_the_body()` --uses--> `Transport`  [INFERRED]
  tests/worker/test_audit.py → apps/worker/bedrock/wire.py
- `test_jev_exchange_records_status_without_the_key()` --uses--> `Client`  [INFERRED]
  tests/worker/test_audit.py → apps/worker/jev/client.py
- `MapVerifier` --uses--> `AuthContext`  [INFERRED]
  tests/api/conftest.py → apps/api/quotient/auth/context.py
- `test_bypass_off_by_default_and_metadata()` --uses--> `MemoryPort`  [INFERRED]
  tests/api/auth.py → apps/api/quotient/worker/memory.py
- `test_explicit_bypass_flag_from_env()` --uses--> `MemoryPort`  [INFERRED]
  tests/api/auth.py → apps/api/quotient/worker/memory.py

## Import Cycles
- None detected.

## Communities (130 total, 29 thin omitted)

### Community 0 - "sort.py"
Cohesion: 0.13
Nodes (20): _audit_api(), Client, _elapsed_ms(), JevFailed, RuntimeError, _retry_after(), order(), _overflows() (+12 more)

### Community 1 - "properties"
Cohesion: 0.06
Nodes (37): additionalProperties, items, type, anyOf, items, type, $id, additionalProperties (+29 more)

### Community 2 - "MemoryPort"
Cohesion: 0.18
Nodes (8): _blank_meeting(), MemoryPort, _now(), _pending_artifacts(), Motivation vs Logic Motivation: Partners can exercise MCP before the worker…, Move a ledger row. Not an MCP tool and not a model loop., PortError, Exception

### Community 3 - "home.tsx"
Cohesion: 0.15
Nodes (25): ASSURANCES, FilterId, FILTERS, Home(), beginEdit(), onSubmit(), removeRow(), saveEdit() (+17 more)

### Community 4 - "isolation.py"
Cohesion: 0.17
Nodes (25): Draft202012Validator, accepts(), compile_schema(), contract_needles(), dimension_roles(), embedded(), load_prompt(), load_registry() (+17 more)

### Community 5 - "meeting.chart.v1.json"
Cohesion: 0.08
Nodes (24): additionalProperties, enum, type, allOf, enum, type, $id, items (+16 more)

### Community 6 - "metadata.py"
Cohesion: 0.31
Nodes (7): AuthSettings, bypass_requested(), _csv_origins(), environment_locks_bypass(), load_auth_settings(), _metadata_url(), Motivation vs Logic Motivation: MCP HTTP authorization discovers the…

### Community 7 - "meeting.synthesis.v1.json"
Cohesion: 0.08
Nodes (24): additionalProperties, items, minItems, type, uniqueItems, $id, additionalProperties, minLength (+16 more)

### Community 8 - "meeting.pegasus.continue.v1.json"
Cohesion: 0.08
Nodes (24): additionalProperties, description, type, $id, additionalProperties, properties, required, type (+16 more)

### Community 9 - "meeting.compaction.v1.json"
Cohesion: 0.09
Nodes (21): additionalProperties, $id, additionalProperties, properties, required, type, enum, type (+13 more)

### Community 10 - "meeting.dissent.v1.json"
Cohesion: 0.11
Nodes (19): additionalProperties, items, minItems, type, uniqueItems, $id, minLength, type (+11 more)

### Community 11 - "compilerOptions"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+10 more)

### Community 12 - "meeting.counterevidence.v1.json"
Cohesion: 0.12
Nodes (16): additionalProperties, oneOf, $id, minLength, type, properties, finding, searched_ids (+8 more)

### Community 13 - "meeting.coverage.v1.json"
Cohesion: 0.13
Nodes (14): additionalProperties, $id, minLength, type, properties, uncovered_span_ids, required, $schema (+6 more)

### Community 14 - "meeting.entailment_luna.v1.json"
Cohesion: 0.17
Nodes (11): additionalProperties, $id, description, enum, type, properties, label, required (+3 more)

### Community 15 - "meeting.entailment.v1.json"
Cohesion: 0.17
Nodes (11): additionalProperties, $id, description, enum, type, properties, label, required (+3 more)

### Community 16 - "meeting.supplement.v1.json"
Cohesion: 0.17
Nodes (11): additionalProperties, $id, items, oneOf, type, properties, items, required (+3 more)

### Community 17 - "Reasoner"
Cohesion: 0.13
Nodes (18): estimate_tokens(), _function_tools(), Registry tool objects become Responses function tools. Schema keywords the…, Reasoner, ModelTurn, ToolCall, InputTooLarge, NotInvocable (+10 more)

### Community 18 - "gate.py"
Cohesion: 0.16
Nodes (24): _action_claims_published(), _actions(), _artifacts(), _charts(), _citation_view(), _claim_view(), _counts(), _coverage_gap() (+16 more)

### Community 19 - "react"
Cohesion: 0.13
Nodes (10): CANONICAL, Exports(), Mode, Player, PlayerHandle, mcp, ExportArtifact, Playback (+2 more)

### Community 20 - "client.ts"
Cohesion: 0.07
Nodes (91): dedupe(), dedupeObservations(), dedupeOmissions(), dedupeSeams(), entityId(), exportUri(), mediaLocator(), mergeGraph() (+83 more)

### Community 22 - "ingest.py"
Cohesion: 0.22
Nodes (16): HTTPS adapter. respond() and invoke() match the worker client contracts., Transport, assemble(), _clamp(), _complement(), _cut(), _duration_ms(), _ms_field() (+8 more)

### Community 23 - "meeting.lens_commitment.v1.json"
Cohesion: 0.40
Nodes (4): $id, oneOf, $schema, title

### Community 24 - "meeting.lens_cross_modal.v1.json"
Cohesion: 0.40
Nodes (4): $id, oneOf, $schema, title

### Community 25 - "meeting.lens_decision.v1.json"
Cohesion: 0.40
Nodes (4): $id, oneOf, $schema, title

### Community 26 - "meeting.lens_dependency.v1.json"
Cohesion: 0.40
Nodes (4): $id, oneOf, $schema, title

### Community 27 - "meeting.lens_documentary.v1.json"
Cohesion: 0.40
Nodes (4): $id, oneOf, $schema, title

### Community 28 - "meeting.lens_gap.v1.json"
Cohesion: 0.40
Nodes (4): $id, oneOf, $schema, title

### Community 29 - "meeting.lens_question.v1.json"
Cohesion: 0.40
Nodes (4): $id, oneOf, $schema, title

### Community 30 - "meeting.lens_risk.v1.json"
Cohesion: 0.40
Nodes (4): $id, oneOf, $schema, title

### Community 31 - "meeting.lens_stakeholder.v1.json"
Cohesion: 0.40
Nodes (4): $id, oneOf, $schema, title

### Community 32 - "meeting.lens_temporal.v1.json"
Cohesion: 0.40
Nodes (4): $id, oneOf, $schema, title

### Community 42 - "quality.py"
Cohesion: 0.15
Nodes (29): overlapping(), Claim, Gap, Omission, SynthesisOmission, dissent_payload(), dropped_ids(), sentences_from() (+21 more)

### Community 43 - "properties"
Cohesion: 0.07
Nodes (27): enum, additionalProperties, type, items, type, type, enum, type (+19 more)

### Community 44 - "TaskRecord"
Cohesion: 0.17
Nodes (5): TaskBoard, TaskRecord, tool_error(), utc_now(), Future

### Community 45 - "wire.py"
Cohesion: 0.06
Nodes (45): _hidden(), record(), _redact(), _audit_llm(), _auth_headers(), bearer_token(), _blob_header(), _cached_tokens() (+37 more)

### Community 46 - "mcp.tsx"
Cohesion: 0.19
Nodes (9): metadata, formatTool(), McpScreen(), originSubscribe(), phaseLabel(), phaseSentence(), subscribe(), View (+1 more)

### Community 47 - "Quotient MCP"
Cohesion: 0.09
Nodes (22): `accept_action`, Authorization, `cancel_meeting`, Endpoint, Errors, External client, `get_meeting`, Limits (+14 more)

### Community 48 - "open_session"
Cohesion: 0.18
Nodes (18): MapVerifier, open_session(), published_graph(), Shared HTTP helpers for the Quotient MCP contract tests., rpc(), Publish gate, captions, and export resources., _resource(), test_brief_withholds_unresolved_claims_and_captions_use_source_time() (+10 more)

### Community 49 - "meeting.pegasus.v1.json"
Cohesion: 0.10
Nodes (21): additionalProperties, type, additionalProperties, properties, required, type, items, type (+13 more)

### Community 50 - "registry"
Cohesion: 0.20
Nodes (12): MemoryStore, lens_id(), dimensions(), registry(), Scripted, _span(), test_blind_lenses_run_all_ten_without_seeing_each_other(), test_iteration_ceiling_withholds_the_brief() (+4 more)

### Community 51 - "Session"
Cohesion: 0.12
Nodes (26): AuthContext, local_context(), Motivation vs Logic Motivation: Every task and meeting is visible only inside…, _accepts(), _audit_http(), _authorize(), _bearer(), _classify() (+18 more)

### Community 52 - "TaskRoles"
Cohesion: 0.15
Nodes (11): IBucket, ICluster, Construct, IQueue, Role, TaskRoles, IRole, ISecret (+3 more)

### Community 53 - "project.py"
Cohesion: 0.09
Nodes (49): _bounds(), _cue_text(), _document(), Motivation vs Logic Motivation: Captions are a projection of speech spans onto…, _speech(), srt(), _stamp(), webvtt() (+41 more)

### Community 54 - "sandbox.py"
Cohesion: 0.06
Nodes (71): _action_acceptance(), aggregation_chart(), builtins_open(), _catalog(), _chart(), _chart_by_id(), commit_svg(), _count_row() (+63 more)

### Community 55 - "shell.tsx"
Cohesion: 0.15
Nodes (11): metadata, montserrat, pirulen, isCurrent(), PRIMARY_LINKS, PrimaryLinks(), Shell(), subscribe() (+3 more)

### Community 56 - "MeetingCompute"
Cohesion: 0.20
Nodes (10): FargateService, MeetingCompute, Construct, IQueue, Role, _release_desired_count(), MeetingTables, Construct (+2 more)

### Community 57 - "WorkerPort"
Cohesion: 0.16
Nodes (9): _import_worker_port(), _load_file(), load_worker_port(), Path, Protocol, Motivation vs Logic Motivation: The meeting loop, model calls, and binary…, Sync surface the MCP server calls. submit must return without a model loop.…, _repo_root() (+1 more)

### Community 58 - "package.json"
Cohesion: 0.13
Nodes (14): name, private, scripts, build, dev, start, typecheck, version (+6 more)

### Community 59 - "transcript.tsx"
Cohesion: 0.17
Nodes (17): Highlighted(), Inspector(), Timeline(), Highlighted(), RawRow(), SpanEdit(), Transcript(), VIDEO_KIND (+9 more)

### Community 60 - "stack.py"
Cohesion: 0.30
Nodes (3): global_foundation_arns(), sydney_profile_arns(), tokyo_sonic_arn()

### Community 61 - "workspace.tsx"
Cohesion: 0.13
Nodes (24): Boards(), Charts(), Disagreements(), Review(), openKey(), Synthesis(), Hypotheses(), idlePanel (+16 more)

### Community 62 - "StagingStack"
Cohesion: 0.20
Nodes (9): MeetingAuth, Construct, MeetingVpc, Construct, Construct, StagingStack, Construct, WorkQueue (+1 more)

### Community 63 - "Registry"
Cohesion: 0.16
Nodes (13): PinMismatch, The registry model role does not match the locked plan pin., A plan registry id or its file is not on disk., RegistryMissing, _breakpoints(), default_root(), _index(), Prompt (+5 more)

### Community 64 - "state.py"
Cohesion: 0.22
Nodes (16): DimensionSkipped, RuntimeError, A meeting finished without one of the ten blinded lenses., apply_decision_status(), _decision_enum(), require_dimensions(), run_lenses(), _take_enum() (+8 more)

### Community 65 - "PegasusClient"
Cohesion: 0.21
Nodes (6): PegasusClient, pack_scenes(), Part, test_length_continuation_discards_the_partial_object(), test_scene_parts_stay_under_fifty_minutes(), Transport

### Community 66 - "server.py"
Cohesion: 0.12
Nodes (39): is_text(), mime_for(), error(), JSON-RPC error codes used by the Quotient MCP endpoint., result(), decode_cursor(), encode_cursor(), Opaque cursors for MCP list methods. (+31 more)

### Community 67 - "Workspace"
Cohesion: 0.22
Nodes (13): citationFor(), useTask(), Workspace(), onOpenSentence(), onSeekClaim(), onSeekSpan(), reload(), run() (+5 more)

### Community 68 - "contracts/schemas/meeting.pegasus.v1.json"
Cohesion: 0.08
Nodes (24): additionalProperties, description, type, $id, additionalProperties, properties, required, type (+16 more)

### Community 69 - "numbers.py"
Cohesion: 0.20
Nodes (15): ImmutableRawText, raw_text is the Sonic string and cannot be replaced., _digit(), _direction(), grounded(), NumberScan, _orphan_unit(), Quantity (+7 more)

### Community 70 - "Quotient staging"
Cohesion: 0.17
Nodes (11): Auth, Budget, Compute, Data, Deploy, IAM, Images, Network (+3 more)

### Community 71 - "quotient/app.py"
Cohesion: 0.12
Nodes (15): create_app(), __getattr__(), Motivation vs Logic Motivation: The process exposes one ASGI app: Streamable…, _Runtime, Protocol, Return a context for a signature-checked access token, or None., Stub resource-server check. Cognito JWKS validation is not performed., RejectingVerifier (+7 more)

### Community 72 - "MeetingMachine"
Cohesion: 0.31
Nodes (6): ILogGroup, _label(), MeetingMachine, Construct, IQueue, SqsSendMessage

### Community 73 - "fixtures/contracts/schemas/meeting.entailment.v1.json"
Cohesion: 0.25
Nodes (7): additionalProperties, enum, properties, label, required, $schema, type

### Community 74 - "MeetingBuckets"
Cohesion: 0.52
Nodes (3): Bucket, MeetingBuckets, Construct

### Community 75 - "route.ts"
Cohesion: 0.25
Nodes (15): dynamic, envPath(), GET(), localRequest(), loopbackHost(), POST(), ALLOWED, applyEnv() (+7 more)

### Community 76 - "meeting.crossmodal.v1.json"
Cohesion: 0.09
Nodes (21): additionalProperties, allOf, description, $id, minLength, type, properties, observation_id (+13 more)

### Community 77 - "BillingAlarms"
Cohesion: 0.60
Nodes (3): BillingAlarms, Construct, IQueue

### Community 78 - "MeetingLogs"
Cohesion: 0.60
Nodes (3): MeetingLogs, Construct, LogGroup

### Community 97 - "meeting.sonic.v1.json"
Cohesion: 0.25
Nodes (7): additionalProperties, description, $id, properties, $schema, title, type

### Community 98 - "Port"
Cohesion: 0.16
Nodes (9): _now(), _pending(), Port, _raise(), Ledger the MCP server calls. Analysis stays in loop.quality.run., Raise the API PortError when this module was loaded by the MCP process., Record bytes a worker renderer already produced. Empty bodies are ignored., Quality entrypoint. Calls loop.quality.run and stores its gate result. (+1 more)

### Community 99 - "test_sort.py"
Cohesion: 0.32
Nodes (16): apply_order(), Answers, claim(), queued_result(), test_429_honors_retry_after_once(), test_confidence_does_not_reorder(), test_empty_queue_does_not_call(), test_http_failure_keeps_order_status_and_brief() (+8 more)

### Community 100 - "start-local.sh"
Cohesion: 0.17
Nodes (27): api_process(), apply_local_env(), assert_port_available(), cleanup(), clear_pidfile_if_ours(), die(), follow_audit(), is_under() (+19 more)

### Community 101 - "stop-local.sh"
Cohesion: 0.44
Nodes (8): kill_tree(), pid_alive(), pid_running(), process_args(), read_pidfile(), stop-local.sh script, stop_pid(), stop_recorded()

### Community 102 - "pegasus/client.py"
Cohesion: 0.21
Nodes (9): A cited time lies outside the source or the scene part that produced it., TimestampOutside, build_body(), classify_observations(), Observation, PegasusResult, _vendor_schema(), VisualNote (+1 more)

### Community 103 - "mcp/tools.py"
Cohesion: 0.29
Nodes (16): page_graph(), summary(), _accept_action(), _cancel_meeting(), _get_meeting(), _handlers(), list_tools(), _optional_cursor() (+8 more)

### Community 104 - "Span"
Cohesion: 0.27
Nodes (16): accept_action(), action_schema(), apply_owner(), _checked(), _find_action_schema(), _first_person(), ground_action(), ground_due() (+8 more)

### Community 105 - "sonic/client.py"
Cohesion: 0.05
Nodes (46): build_table(), KeepInterval, map_sample_range(), _merge(), ms_to_samples(), source_ms_of_sample(), frame_metrics(), idle_spans() (+38 more)

### Community 106 - "auth.py"
Cohesion: 0.53
Nodes (5): Authorization metadata and the default-off local bypass., test_bypass_off_by_default_and_metadata(), test_explicit_bypass_flag_from_env(), test_staging_ignores_bypass_flag(), base_headers()

### Community 107 - "test_gates.py"
Cohesion: 0.26
Nodes (16): dual(), finalize_claim(), Resolution, resolve_quote(), claim_for(), publish(), speech(), test_cross_modal_disagreement_keeps_both_ids_and_raw_text() (+8 more)

### Community 108 - "markdown.tsx"
Cohesion: 0.29
Nodes (11): Align, alignment(), Block, blocks(), fit(), inline(), Markdown(), paragraphBlock() (+3 more)

### Community 109 - "meeting.review_sort.v1.json"
Cohesion: 0.17
Nodes (11): additionalProperties, $id, properties, score, type, required, $schema, type (+3 more)

### Community 110 - "home-object.tsx"
Cohesion: 0.43
Nodes (6): HomeObject, buildStars(), HomeObject(), isLightTheme(), mulberry32(), three

### Community 111 - "IndexedSpan"
Cohesion: 0.73
Nodes (5): apply_omissions(), IndexedSpan, payload_duration_ms(), source_duration_ms(), test_compaction_never_drops_overlap_and_keeps_the_index()

### Community 112 - "quotient/port.py"
Cohesion: 0.23
Nodes (12): _action_row(), _claim_row(), _finding_row(), _observation_row(), _public_failure(), Copy worker table rows. The API stores this list and does not recompute it., _record(), _relation() (+4 more)

### Community 113 - "statusLabel"
Cohesion: 0.26
Nodes (8): Lens(), Progress(), TaskScreen(), artifactLabel(), humanize(), statusLabel(), ARTIFACT_ORDER, TaskSnapshot

### Community 114 - "classify_file"
Cohesion: 0.24
Nodes (10): classify_file(), classify_streams(), model_plan(), probe(), Path, _load_entrypoints(), load_port(), Path (+2 more)

### Community 115 - "skills.tsx"
Cohesion: 0.22
Nodes (5): metadata, Skill, Skills(), TIPS, SkillSummary

### Community 116 - "format.ts"
Cohesion: 0.38
Nodes (8): Actions(), ARTIFACT_LABEL, dueText(), isProposed(), ownerText(), STATUS_LABEL, ActionItem, Span

### Community 117 - "diagram.tsx"
Cohesion: 0.31
Nodes (7): Diagram(), enqueue(), MermaidTheme, queue, readTheme(), sanitize(), mermaid

### Community 118 - "settings.tsx"
Cohesion: 0.29
Nodes (4): metadata, LoadedField, Settings(), next

### Community 119 - "write_pcm"
Cohesion: 0.70
Nodes (4): ffmpeg_pcm_args(), Path, write_pcm(), test_ffprobe_and_pcm_keep_source_clock()

### Community 120 - "jobs.py"
Cohesion: 0.22
Nodes (18): cancel_meeting_tasks(), _collect_upload(), _elicitation(), _fanout(), _names(), notify_resources(), _notify_status(), _progress() (+10 more)

### Community 121 - "SchemaRejected"
Cohesion: 0.46
Nodes (7): Decoded model output failed draft-2020-12 validation or was truncated JSON., SchemaRejected, loads_object(), validate(), validate_json(), test_sol_and_luna_roles_are_unchanged(), test_repo_registry_routes_match_plan_pins()

### Community 122 - "dependencies"
Cohesion: 0.29
Nodes (7): dependencies, lucide-react, mermaid, next, react, react-dom, three

### Community 126 - "devDependencies"
Cohesion: 0.33
Nodes (6): devDependencies, @types/node, @types/react, @types/react-dom, @types/three, typescript

### Community 127 - "test_prose.py"
Cohesion: 0.24
Nodes (11): _line(), normalize(), _scrub(), Mermaid fences stay inside synthesis sentences only when the header is real., test_c4_header_is_kept(), test_flowchart_stays_and_click_markup_is_removed(), test_non_mermaid_fence_stays_a_code_fence(), test_plain_sentence_is_unchanged() (+3 more)

### Community 128 - "cross.py"
Cohesion: 0.60
Nodes (4): record_cross(), _unchanged(), Disagreement, Disagreement

## Knowledge Gaps
- **380 isolated node(s):** `quotient-api`, `dynamic`, `montserrat`, `pirulen`, `metadata` (+375 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 628 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **29 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Table` connect `sandbox.py` to `MeetingCompute`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **Why does `MeetingTables` connect `MeetingCompute` to `stack.py`, `StagingStack`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Why does `ChartRejected` connect `sandbox.py` to `mcp/tools.py`, `Registry`?**
  _High betweenness centrality (0.029) - this node is a cross-community bridge._
- **Are the 25 inferred relationships involving `Registry` (e.g. with `Reasoner` and `Port`) actually correct?**
  _`Registry` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `ChartRejected` (e.g. with `_ImportBlocker` and `test_chart_numeric_literal_fails_before_render_and_workbook_value_is_plotted()`) actually correct?**
  _`ChartRejected` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `Span` (e.g. with `accept_action()` and `apply_owner()`) actually correct?**
  _`Span` has 20 INFERRED edges - model-reasoned connections that need verification._
- **What connects `quotient-api`, `dynamic`, `montserrat` to the rest of the system?**
  _380 weakly-connected nodes found - possible documentation gaps or missing edges._