# Graph Report - meeting  (2026-10-28)

## Corpus Check
- 374 files · ~1,212,625 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 4352 nodes · 9080 edges · 299 communities (250 shown, 41 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 546 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e9bfde62`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- graph.ts
- properties
- MemoryPort
- home.tsx
- isolation.py
- meeting.chart.v1.json
- context.ts
- meeting.synthesis.v1.json
- properties
- meeting.compaction.v1.json
- meeting.dissent.v1.json
- compilerOptions
- meeting.counterevidence.v1.json
- meeting.coverage.v1.json
- meeting.entailment_luna.v1.json
- meeting.entailment.v1.json
- meeting.supplement.v1.json
- NotInvocable
- project_meeting
- present.ts
- client.ts
- delete-cache.sh
- Session
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
- test_media_robustness.py
- registry/__init__.py
- quotient-api
- quality.py
- properties
- TaskRecord
- wire.py
- shell.tsx
- Quotient MCP
- open_session
- properties
- test_loop.py
- server.py
- TaskRoles
- properties
- sandbox.py
- settings/route.ts
- MeetingCompute
- WorkerPort
- package.json
- Client
- cluster.py
- react
- stack.py
- overview.tsx
- keys.py
- pegasus/client.py
- exports.py
- workspace.tsx
- properties
- numbers.py
- Quotient staging
- insights.tsx
- MeetingMachine
- fixtures/contracts/schemas/meeting.entailment.v1.json
- MeetingBuckets
- asRecord
- meeting.crossmodal.v1.json
- resolve_visual
- MeetingLogs
- next.config.mjs
- api/quotient/__init__.py
- mcp/__init__.py
- css.d.ts
- bedrock/__init__.py
- worker/graph/__init__.py
- quotient/app.py
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
- ingest.py
- Registry
- start-local.sh
- stop-local.sh
- test_digest.py
- mcp/tools.py
- Span
- sonic/client.py
- create_app
- test_gates.py
- markdown.tsx
- meeting.review_sort.v1.json
- progress.tsx
- test_prose.py
- properties
- properties
- properties
- properties
- export/project.py
- properties
- properties
- meeting.frame.v1.json
- mcp/jobs.py
- test_digest_review.py
- properties
- chart/__init__.py
- jev/__init__.py
- properties
- record
- frames.py
- meeting.screen_use.v1.json
- Port
- ContextLibrary
- quotient/port.py
- to_markdown
- ._save_locked
- screens.ts
- test_context_port.py
- Quotient hardening ledger
- Quotient
- diagram.py
- SonicClient
- routes.py
- test_sonic.py
- storage.py
- test_port_persistence.py
- public/jobs.py
- review.tsx
- upload.ts
- test_flow_safety.py
- digest.py
- test_context.py
- overlap.py
- contracts/schemas/meeting.answer_check.v1.json
- fixtures/contracts/schemas/meeting.answer_check.v1.json
- _SonicSession
- load_library
- graph/screenuse.py
- summary
- summary
- summary
- summary
- test_screenuse.py
- ArtifactCache
- Path
- TranscriptCache
- Next steps (hand-over, 2026-10-09)
- captions.py
- Session
- ObjectJobs
- home-loader.tsx
- assemble
- Quotient — Repository Architecture
- gist_of
- mcp.tsx
- README.md
- start-local-minio.sh
- test_visual_scan.py
- contracts/schemas/meeting.digest_review.v1.json
- contracts/schemas/meeting.digest.v1.json
- fixtures/contracts/schemas/meeting.digest_review.v1.json
- fixtures/contracts/schemas/meeting.digest.v1.json
- worker/quotient/seed.py
- names.py
- build_eval_inputs.py
- identity.py
- _port
- test_seed.py
- resources.py
- Benchmark results
- Round 2: pressure testing (adversarial reviews, failure injection, rubric evaluation)
- local/README.md
- alias.mjs
- Changes (all in working tree, uncommitted)
- Round 3: from evidence dump to a walkaway (2026-10-08/09)
- api/quotient/seed.py
- public.py
- diarize_cli.py
- metadata.py
- asked_span_id
- end_span_id
- gist
- id
- name
- quote
- risk
- span_id
- span_ids
- statement
- status
- task
- term
- text
- topic
- value
- what
- asked_span_id
- end_span_id
- gist
- id
- name
- quote
- risk
- span_id
- span_ids
- statement
- status
- task
- term
- text
- topic
- value
- what
- asked_span_id
- end_span_id
- gist
- id
- name
- quote
- risk
- span_id
- span_ids
- statement
- status
- task
- term
- text
- topic
- value
- what
- asked_span_id
- end_span_id
- gist
- id
- name
- quote
- risk
- span_id
- span_ids
- statement
- status
- task
- term
- text
- topic
- value
- what
- claim_ids
- claim_ids
- setup-context.sh
- setup-diarizer.sh
- claim_ids
- claim_ids
- ValueError
- test_digest_visual.py
- Architecture gaps and discrepancies
- test_port.py
- test_media.py
- api/graph.py
- Component inventory
- ._apply_identity_state
- Execution traces
- public/__init__.py
- .media_url
- test_ingest_upload.py
- test_one_open_span_is_not_coarse_and_raw_text_is_immutable
- .wrap
- diarize_pcm
- datetime
- ._post
- iam_credentials
- _send_all
- IndexedSpan
- FilteringTransport
- api/screenuse.py

## God Nodes (most connected - your core abstractions)
1. `Port` - 70 edges
2. `project_meeting()` - 68 edges
3. `MemoryPort` - 59 edges
4. `create_app()` - 56 edges
5. `ground_digest()` - 48 edges
6. `asRecord()` - 46 edges
7. `Span` - 46 edges
8. `PortError` - 42 edges
9. `asString()` - 42 edges
10. `Registry` - 42 edges

## Surprising Connections (you probably didn't know these)
- `test_the_session_store_is_bounded()` --uses--> `AuthContext`  [INFERRED]
  tests/api/test_auth.py → apps/api/quotient/auth/context.py
- `_tool_turn()` --uses--> `ToolCall`  [INFERRED]
  tests/worker/test_digest_review.py → apps/worker/bedrock/turn.py
- `test_bedrock_respond_appends_status_without_the_body()` --uses--> `Transport`  [INFERRED]
  tests/worker/test_audit.py → apps/worker/bedrock/wire.py
- `test_respond_posts_to_converse_and_never_the_responses_endpoint()` --uses--> `Transport`  [INFERRED]
  tests/worker/test_bedrock_wire.py → apps/worker/bedrock/wire.py
- `test_a_reply_exactly_at_the_end_of_the_window_counts_and_one_millisecond_later_does_not()` --uses--> `Span`  [INFERRED]
  tests/worker/test_digest_review.py → apps/worker/graph/span.py

## Import Cycles
- None detected.

## Communities (299 total, 41 thin omitted)

### Community 0 - "graph.ts"
Cohesion: 0.09
Nodes (32): Synthesis(), dedupe(), dedupeObservations(), dedupeOmissions(), dedupeSeams(), exportUri(), IDENTITY_SOURCES, mediaLocator() (+24 more)

### Community 1 - "properties"
Cohesion: 0.06
Nodes (38): additionalProperties, items, type, anyOf, items, type, $id, additionalProperties (+30 more)

### Community 2 - "MemoryPort"
Cohesion: 0.11
Nodes (13): _blank_meeting(), MemoryPort, _now(), _pending_artifacts(), Motivation vs Logic Motivation: Partners can exercise MCP before the worker…, Move a ledger row. Not an MCP tool and not a model loop., _same_person(), PortError (+5 more)

### Community 3 - "home.tsx"
Cohesion: 0.09
Nodes (41): FilterId, FILTERS, Home(), beginEdit(), confirmRemove(), onSubmit(), saveEdit(), titleOf() (+33 more)

### Community 4 - "isolation.py"
Cohesion: 0.17
Nodes (25): Draft202012Validator, accepts(), compile_schema(), contract_needles(), dimension_roles(), embedded(), load_prompt(), load_registry() (+17 more)

### Community 5 - "meeting.chart.v1.json"
Cohesion: 0.08
Nodes (24): additionalProperties, enum, type, allOf, enum, type, $id, items (+16 more)

### Community 6 - "context.ts"
Cohesion: 0.06
Nodes (63): chipFor(), ContextDialog(), addFiles(), addNote(), editNote(), save(), ContextModal(), count() (+55 more)

### Community 7 - "meeting.synthesis.v1.json"
Cohesion: 0.08
Nodes (24): additionalProperties, items, minItems, type, uniqueItems, $id, additionalProperties, minLength (+16 more)

### Community 8 - "properties"
Cohesion: 0.05
Nodes (44): additionalProperties, type, description, type, type, $id, additionalProperties, properties (+36 more)

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

### Community 17 - "NotInvocable"
Cohesion: 0.16
Nodes (17): estimate_tokens(), _function_tools(), Registry tool objects become Responses function tools. Schema keywords the…, Reasoner, InputTooLarge, NotInvocable, Assembled model input exceeded the 272K-token short-context budget., loads_object() (+9 more)

### Community 18 - "project_meeting"
Cohesion: 0.07
Nodes (47): _action_claims_published(), _actions(), _artifacts(), _charts(), _citation_view(), _claim_view(), _confidence(), _context_view() (+39 more)

### Community 19 - "present.ts"
Cohesion: 0.06
Nodes (52): Actions(), Boards(), Charts(), Columns(), Moments(), Stack(), TableView(), Inspector() (+44 more)

### Community 20 - "client.ts"
Cohesion: 0.09
Nodes (42): buildPrepareArgs(), runPool(), UPLOAD_CONCURRENCY, answeredElicitations, baseHeaders(), callTool(), connect(), consumeSse() (+34 more)

### Community 22 - "Session"
Cohesion: 0.13
Nodes (7): AuthContext, local_context(), Cognito access-token verification and the explicitly local auth context., Motivation vs Logic Motivation: Streamable HTTP keeps a session so progress,…, Session, SessionStore, Queue

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

### Community 39 - "test_media_robustness.py"
Cohesion: 0.14
Nodes (6): Deterministic media evidence: probe, PCM, VAD, idle, overlap, compaction, clock., _FakeProcess, Stands in for the diarizer: writes its turns file when started, then reports it…, _run_with_output(), test_diarizer_output_that_is_not_an_object_or_has_bad_rows_never_crashes(), test_port_refuses_non_media_and_oversize_uploads()

### Community 42 - "quality.py"
Cohesion: 0.08
Nodes (52): DimensionSkipped, NoSpeech, RuntimeError, A meeting finished without one of the ten blinded lenses., The recording is long enough to hold speech but nothing was transcribed., overlapping(), apply_decision_status(), _decision_enum() (+44 more)

### Community 43 - "properties"
Cohesion: 0.07
Nodes (27): enum, additionalProperties, type, items, type, type, enum, type (+19 more)

### Community 44 - "TaskRecord"
Cohesion: 0.19
Nodes (7): LimitError, Exception, Motivation vs Logic Motivation: submit_meeting is long-running. MCP tasks let…, TaskRecord, tool_error(), utc_now(), Future

### Community 45 - "wire.py"
Cohesion: 0.15
Nodes (20): _converse_response(), _decode_frames(), _encode_frame(), _ensure_additional_properties_false(), _exception_message(), _has_disallowed_schema(), _header(), invalidate_iam() (+12 more)

### Community 46 - "shell.tsx"
Cohesion: 0.12
Nodes (15): metadata, montserrat, pirulen, QuantumLoader, STEPS, isCurrent(), PRIMARY_LINKS, PrimaryLinks() (+7 more)

### Community 47 - "Quotient MCP"
Cohesion: 0.05
Nodes (35): Authorization, Endpoint, Errors, Examples, Graph, Quotient API, Sequence, What you receive (+27 more)

### Community 48 - "open_session"
Cohesion: 0.08
Nodes (39): MapVerifier, open_session(), Shared HTTP helpers for the Quotient MCP contract tests., rpc(), test_media_resource_uses_owner_scoped_short_lived_url(), _answer(), _ContextOwningPort, _meeting_id() (+31 more)

### Community 49 - "properties"
Cohesion: 0.05
Nodes (44): additionalProperties, type, description, type, type, $id, additionalProperties, properties (+36 more)

### Community 50 - "test_loop.py"
Cohesion: 0.11
Nodes (41): ModelTurn, ToolCall, run_lenses(), Claim, Budget, _BudgetModel, _contest(), Ledger (+33 more)

### Community 51 - "server.py"
Cohesion: 0.19
Nodes (26): resolve_client_response(), get_prompt(), list_prompts(), Motivation vs Logic Motivation: MCP prompts are partner workflows for a client…, _accepts(), _audit_http(), _authorize(), _bearer() (+18 more)

### Community 52 - "TaskRoles"
Cohesion: 0.15
Nodes (11): IBucket, ICluster, Construct, IQueue, Role, TaskRoles, IRole, ISecret (+3 more)

### Community 53 - "properties"
Cohesion: 0.05
Nodes (43): additionalProperties, description, maximum, minimum, type, description, $id, description (+35 more)

### Community 54 - "sandbox.py"
Cohesion: 0.07
Nodes (71): _action_acceptance(), aggregation_chart(), builtins_open(), _catalog(), _chart(), _chart_by_id(), commit_svg(), _count_row() (+63 more)

### Community 55 - "settings/route.ts"
Cohesion: 0.12
Nodes (33): dynamic, forward(), GET(), localRequest(), loopbackHost(), POST(), siteRequest(), dynamic (+25 more)

### Community 56 - "MeetingCompute"
Cohesion: 0.22
Nodes (8): MeetingCompute, Construct, IQueue, Role, MeetingTables, Construct, IVpc, Repository

### Community 57 - "WorkerPort"
Cohesion: 0.10
Nodes (11): _prepare_context(), _import_worker_port(), _load_file(), load_worker_port(), Path, Protocol, Motivation vs Logic Motivation: The meeting loop, model calls, and binary…, Sync surface the MCP server calls. submit must return without a model loop.… (+3 more)

### Community 58 - "package.json"
Cohesion: 0.06
Nodes (31): metadata, dependencies, lucide-react, mermaid, next, react, react-dom, three (+23 more)

### Community 59 - "Client"
Cohesion: 0.12
Nodes (23): _audit_api(), Client, _elapsed_ms(), JevFailed, RuntimeError, _retry_after(), _ordered(), rank_digest() (+15 more)

### Community 60 - "cluster.py"
Cohesion: 0.29
Nodes (4): MeetingAuth, Construct, MeetingVpc, Construct

### Community 61 - "react"
Cohesion: 0.12
Nodes (22): Highlighted(), Player, PlayerHandle, Props, sampleBlank(), SPEEDS, Highlighted(), Line() (+14 more)

### Community 62 - "stack.py"
Cohesion: 0.20
Nodes (8): BillingAlarms, Construct, IQueue, Construct, StagingStack, Construct, WorkQueue, Stack

### Community 63 - "overview.tsx"
Cohesion: 0.06
Nodes (49): CONTEXT_STATUS, DECISION_LABEL, groupBySpeaker(), Overview(), TYPE_LABEL, counts(), KIND_LABEL, plural() (+41 more)

### Community 64 - "keys.py"
Cohesion: 0.12
Nodes (15): _client(), _Dynamo, dynamo_directory(), file_directory(), _item(), KeyDirectory, load_directory(), MemoryDirectory (+7 more)

### Community 65 - "pegasus/client.py"
Cohesion: 0.10
Nodes (23): A cited time lies outside the source or the scene part that produced it., TimestampOutside, A saved visual scan, or None when it is missing or does not have the expected…, _restore_scan(), classify_observations(), classify_screens(), Observation, PegasusClient (+15 more)

### Community 66 - "exports.py"
Cohesion: 0.10
Nodes (33): _digest(), _leaks(), Commentary about the transcript itself. Positional wording needs a speaker in…, Remove every clause or sentence that talks about the transcript itself; keep…, Clean one row in place. False when its main text was nothing but such…, Re-check the worker's grounded digest against this meeting's spans before…, _unleak(), _unleak_row() (+25 more)

### Community 67 - "workspace.tsx"
Cohesion: 0.07
Nodes (43): ConfirmDialog(), SameVoiceDialog(), UnknownVoiceButton(), UnknownVoiceDialog(), useMediaSource(), citationFor(), idlePanel, NAV (+35 more)

### Community 68 - "properties"
Cohesion: 0.05
Nodes (44): additionalProperties, type, description, type, type, $id, additionalProperties, properties (+36 more)

### Community 69 - "numbers.py"
Cohesion: 0.23
Nodes (16): _digit(), _direction(), grounded(), NumberScan, _orphan_unit(), Quantity, A magnitude word after a digit: "5 million", "$50k". Without it "$5 million"…, _same() (+8 more)

### Community 70 - "Quotient staging"
Cohesion: 0.18
Nodes (11): Auth, Budget, Compute, Data, Deploy, IAM, Images, Network (+3 more)

### Community 71 - "insights.tsx"
Cohesion: 0.07
Nodes (54): Insights(), KIND_LABEL, SERIES_COLORS, BarPart, ChartCard(), clip(), Column, DataTable() (+46 more)

### Community 72 - "MeetingMachine"
Cohesion: 0.31
Nodes (6): ILogGroup, _label(), MeetingMachine, Construct, IQueue, SqsSendMessage

### Community 73 - "fixtures/contracts/schemas/meeting.entailment.v1.json"
Cohesion: 0.25
Nodes (7): additionalProperties, enum, properties, label, required, $schema, type

### Community 75 - "asRecord"
Cohesion: 0.17
Nodes (42): isSafeUrl(), parsePrepareResult(), toolErrorMessage(), parseDigest(), rows(), entityId(), pairSeries(), parseAction() (+34 more)

### Community 76 - "meeting.crossmodal.v1.json"
Cohesion: 0.09
Nodes (21): additionalProperties, allOf, description, $id, minLength, type, properties, observation_id (+13 more)

### Community 77 - "resolve_visual"
Cohesion: 0.10
Nodes (51): _canonical_names(), clean_name(), clean_partial_name(), fuse_identities_model(), Identity, longer_form(), _near(), _overlap() (+43 more)

### Community 78 - "MeetingLogs"
Cohesion: 0.47
Nodes (3): MeetingLogs, Construct, LogGroup

### Community 79 - "next.config.mjs"
Cohesion: 0.40
Nodes (3): nextConfig, root, securityHeaders

### Community 86 - "quotient/app.py"
Cohesion: 0.07
Nodes (23): _disk(), __getattr__(), _isolated(), _load_verifier(), Motivation vs Logic Motivation: The process exposes one ASGI app: Streamable…, Contract tests inject a port and carry no table names. They must not open the…, _Runtime, Protocol (+15 more)

### Community 97 - "meeting.sonic.v1.json"
Cohesion: 0.25
Nodes (7): additionalProperties, description, $id, properties, $schema, title, type

### Community 98 - "ingest.py"
Cohesion: 0.15
Nodes (24): HTTPS adapter. respond() and invoke() match the worker client contracts., Transport, _assemble(), _clamp(), _complement(), _cut(), _duration_ms(), _ms_field() (+16 more)

### Community 99 - "Registry"
Cohesion: 0.12
Nodes (29): PinMismatch, FileNotFoundError, The registry model role does not match the locked plan pin., A plan registry id or its file is not on disk., RegistryMissing, apply_order(), _breakpoints(), default_root() (+21 more)

### Community 100 - "start-local.sh"
Cohesion: 0.17
Nodes (27): api_process(), apply_local_env(), assert_port_available(), cleanup(), clear_pidfile_if_ours(), die(), follow_audit(), is_under() (+19 more)

### Community 101 - "stop-local.sh"
Cohesion: 0.44
Nodes (8): kill_tree(), pid_alive(), pid_running(), process_args(), read_pidfile(), stop-local.sh script, stop_pid(), stop_recorded()

### Community 102 - "test_digest.py"
Cohesion: 0.12
Nodes (41): ground_digest(), _claim(), _raw(), _span(), test_a_concept_starts_at_its_earliest_cited_line(), test_a_disagreement_needs_two_distinct_identified_voices(), test_a_due_phrase_is_kept_only_when_it_names_a_time(), test_a_figure_without_a_quantity_is_not_a_figure() (+33 more)

### Community 103 - "mcp/tools.py"
Cohesion: 0.26
Nodes (20): page_graph(), summary(), encode_cursor(), _accept_action(), _cancel_meeting(), _get_meeting(), _handlers(), _merge_speakers() (+12 more)

### Community 104 - "Span"
Cohesion: 0.14
Nodes (28): ImmutableRawText, Decoded model output failed draft-2020-12 validation or was truncated JSON., raw_text is the Sonic string and cannot be replaced., SchemaRejected, accept_action(), action_schema(), apply_owner(), _checked() (+20 more)

### Community 105 - "sonic/client.py"
Cohesion: 0.16
Nodes (16): KeepInterval, map_sample_range(), _merge(), ms_to_samples(), source_ms_of_sample(), bind_samples(), _content(), _H2Error (+8 more)

### Community 106 - "create_app"
Cohesion: 0.12
Nodes (29): Any, create_app(), CognitoVerifier, Verify Cognito RS256 access tokens against the configured resource. Access…, PyJWKClient, Starlette, base_headers(), Authorization metadata and the default-off local bypass. (+21 more)

### Community 107 - "test_gates.py"
Cohesion: 0.21
Nodes (21): confidence_of(), dual(), _finalize(), finalize_claim(), Resolution, resolve_quote(), dimensions(), claim_for() (+13 more)

### Community 108 - "markdown.tsx"
Cohesion: 0.09
Nodes (26): metadata, Diagram(), enqueue(), MermaidTheme, queue, readTheme(), sanitize(), Align (+18 more)

### Community 109 - "meeting.review_sort.v1.json"
Cohesion: 0.17
Nodes (11): additionalProperties, $id, properties, score, type, required, $schema, type (+3 more)

### Community 110 - "progress.tsx"
Cohesion: 0.15
Nodes (16): CANONICAL, Exports(), download(), Progress(), stepState(), SpanEdit(), saveSpeaker(), saveText() (+8 more)

### Community 111 - "test_prose.py"
Cohesion: 0.19
Nodes (14): _line(), normalize(), _scrub(), Mermaid fences stay inside synthesis sentences only when the header is real., test_a_fourteen_node_architecture_flowchart_passes_through_unchanged(), test_a_node_called_link_or_click_is_kept_but_real_directives_and_styling_are_not(), test_comparisons_and_arrows_survive_but_html_and_scripts_do_not(), test_c4_header_is_kept() (+6 more)

### Community 112 - "properties"
Cohesion: 0.08
Nodes (41): items, type, items, type, items, items, type, items (+33 more)

### Community 113 - "properties"
Cohesion: 0.08
Nodes (41): items, type, items, type, items, items, type, items (+33 more)

### Community 114 - "properties"
Cohesion: 0.08
Nodes (41): items, type, items, type, items, items, type, items (+33 more)

### Community 115 - "properties"
Cohesion: 0.08
Nodes (41): items, type, items, type, items, items, type, items (+33 more)

### Community 116 - "export/project.py"
Cohesion: 0.13
Nodes (31): _blocks(), _inline(), mermaid_script(), _paragraph(), pdf_pieces(), _plain(), Bugs vs Fixes Bug: List markers were stripped, so a brief sentence became bare…, render_markdown() (+23 more)

### Community 117 - "properties"
Cohesion: 0.05
Nodes (39): anyOf, type, anyOf, anyOf, type, anyOf, anyOf, anyOf (+31 more)

### Community 118 - "properties"
Cohesion: 0.05
Nodes (39): anyOf, type, anyOf, anyOf, type, anyOf, anyOf, anyOf (+31 more)

### Community 119 - "meeting.frame.v1.json"
Cohesion: 0.05
Nodes (38): additionalProperties, enum, type, description, type, $id, additionalProperties, properties (+30 more)

### Community 120 - "mcp/jobs.py"
Cohesion: 0.19
Nodes (22): cancel_meeting_tasks(), _collect_upload(), _elicitation(), _fanout(), _names(), notify_resources(), _notify_status(), _progress() (+14 more)

### Community 121 - "test_digest_review.py"
Cohesion: 0.13
Nodes (26): handler(), AWS Lambda SQS worker handler for on-demand meeting processing., _reviewed(), _size(), _verify_questions(), complete_with_tools(), complete(payload) -> turn (or None). handlers: {tool name: fn(arguments) ->…, The call's arguments, with long strings cut: they are echoed back to the model… (+18 more)

### Community 122 - "properties"
Cohesion: 0.05
Nodes (39): anyOf, type, anyOf, anyOf, type, anyOf, anyOf, anyOf (+31 more)

### Community 126 - "properties"
Cohesion: 0.05
Nodes (39): anyOf, type, anyOf, anyOf, type, anyOf, anyOf, anyOf (+31 more)

### Community 127 - "record"
Cohesion: 0.27
Nodes (8): _hidden(), record(), _redact(), Audit lines for Bedrock and Jev stay free of secrets and request bodies., test_bedrock_respond_appends_status_without_the_body(), test_jev_exchange_records_status_without_the_key(), test_record_drops_secret_names_and_configured_values(), test_record_is_silent_until_the_log_path_is_set()

### Community 128 - "frames.py"
Cohesion: 0.15
Nodes (19): _clean_title(), frame_times(), merge_readings(), _norm(), _overlap(), _quality(), Cleaner is better, then fuller: the fewest unreadable marks, then the most text., readings: (frame time ms, validated frame object) in time order. (+11 more)

### Community 129 - "meeting.screen_use.v1.json"
Cohesion: 0.06
Nodes (31): additionalProperties, description, anyOf, $id, maxLength, minLength, type, additionalProperties (+23 more)

### Community 130 - "Port"
Cohesion: 0.13
Nodes (9): Port, True once a person stopped the reindex that is (still) running on this row., Ledger the MCP server calls. Analysis stays in loop.quality.run., Signed upload targets for reference files. The keys are minted here under…, Turn the meeting's uploaded reference files into a library the agents can read.…, Say on the row that the documents were not read, so nobody assumes the analysis…, Single-task background worker: processes meetings one at a time to preserve…, A reindex that fails leaves the meeting as it was: the brief it already had is… (+1 more)

### Community 131 - "ContextLibrary"
Cohesion: 0.14
Nodes (18): ContextDoc, ContextLibrary, headings_of(), _marks(), _passages(), What travels in a prompt: the purpose, the index and the rules for reading it.…, The read_context tool for the agent loop: arguments in, one bounded result out…, (offset of the heading line, title) for every heading, in order. (+10 more)

### Community 132 - "quotient/port.py"
Cohesion: 0.12
Nodes (23): _action_row(), apply_locked_names(), apply_text_edits(), _claim_row(), _finding_row(), _observation_row(), _pending(), Quality entrypoint. Calls loop.quality.run and stores its gate result. (+15 more)

### Community 133 - "to_markdown"
Cohesion: 0.17
Nodes (23): ConversionFailed, ConverterUnavailable, _csv_table(), _json_block(), _kill_group(), _limits(), Path, RuntimeError (+15 more)

### Community 134 - "._save_locked"
Cohesion: 0.17
Nodes (10): _now(), _raise(), A signed PUT for one browser upload, or None when object storage is not…, Record bytes a worker renderer already produced. Empty bodies are ignored., Keep the newest correction per span (re-analysis replays only that) and bound…, Raise the API PortError when this module was loaded by the MCP process., The context block a new meeting row carries; called with the lock held., Enqueue a meeting for sequential background analysis so concurrent jobs never… (+2 more)

### Community 135 - "screens.ts"
Cohesion: 0.19
Nodes (17): buildScreenCards(), chromeLines(), cleanLines(), collapseRows(), CONTROLS, dropMenuRuns(), Highlight, highlights() (+9 more)

### Community 136 - "test_context_port.py"
Cohesion: 0.14
Nodes (16): PortError, Exception, _files(), port(), fixture, The action-recall pass and the claim check were chosen from measured…, test_a_batch_belongs_to_one_meeting_and_unused_ones_are_capped_and_expire(), test_a_batch_belongs_to_the_subject_who_prepared_it() (+8 more)

### Community 137 - "Quotient hardening ledger"
Cohesion: 0.10
Nodes (21): Accessibility audit with axe-core (2026-10-09; read-only on the running local portal, no model calls), Adversarial check of the read-time filters (2026-10-09, no model calls), Authorization, ledger and concurrency check (2026-10-09, run directly, no model calls), Completion gates (strict status), "+ Context", the duplicate upload row, and software-architecture analysis (2026-10-09), Dependency advisories and the diagram surface (2026-10-09), Hostile context files and hidden text (2026-10-09, no model calls), Independent review of the hardening commits (2026-10-09) (+13 more)

### Community 138 - "Quotient"
Cohesion: 0.10
Nodes (21): Configuration, Contributing, Data handling and privacy, Deployment, Documentation, Environment file (`.env`), How it works, Known limitations (+13 more)

### Community 139 - "diagram.py"
Cohesion: 0.25
Nodes (20): Arrow, _border(), Box, _c4(), _chain(), _fit(), _flow(), _head() (+12 more)

### Community 140 - "SonicClient"
Cohesion: 0.13
Nodes (14): AnalysisCancelled, Exception, The meeting was cancelled while its analysis was running. Not a failure., _permanent(), plan_sessions(), BaseException, Span, Rebuild a saved segment under this meeting's ids; no audio is streamed. (+6 more)

### Community 141 - "routes.py"
Cohesion: 0.19
Nodes (21): KeyBusy, KeyMissing, Exception, An active key already exists., There is no active key to revoke., _auth(), _bearer(), _body() (+13 more)

### Community 142 - "test_sonic.py"
Cohesion: 0.29
Nodes (16): build_table(), _client(), Rejects the audio of selected session numbers with a provider-style error., RejectingTransport, test_a_configuration_failure_fails_the_meeting_instead_of_becoming_untranscribed(), test_a_content_filtered_segment_loses_only_the_rejected_window(), test_a_lapsed_sign_in_fails_after_one_refresh_with_the_real_cause(), test_a_meeting_where_every_window_is_rejected_fails_instead_of_looking_silent() (+8 more)

### Community 143 - "storage.py"
Cohesion: 0.18
Nodes (17): base_media_type(), bucket_name(), _client(), context_allowed(), context_extension(), context_key(), head(), media_type_allowed() (+9 more)

### Community 144 - "test_port_persistence.py"
Cohesion: 0.20
Nodes (18): _port_module(), _port_type(), _presign_keys(), test_a_ledger_that_is_damaged_or_the_wrong_shape_is_refused_and_left_exactly_as_found(), test_a_rejected_sign_in_gets_an_actionable_sentence(), test_a_restart_loop_cannot_resume_the_same_meeting_forever(), test_aws_playback_signs_the_submitted_key_without_probing(), test_checkpoint_keys_are_scoped_by_subject_so_one_tenant_cannot_replay_anothers_analysis() (+10 more)

### Community 145 - "public/jobs.py"
Cohesion: 0.15
Nodes (10): partner_graph(), Partner graph body: spans, speakers, screens, and times. Motivation vs Logic…, JobBoard, _not_ready(), _now(), _public_upload(), Motivation vs Logic Motivation: An external app submits one recording,…, Spans, speakers, screens, and times for one owned job. (+2 more)

### Community 146 - "review.tsx"
Cohesion: 0.17
Nodes (15): Group, KIND_ORDER, KIND_TITLE, kindOf(), kindRank(), List(), merge(), REASON (+7 more)

### Community 147 - "upload.ts"
Cohesion: 0.22
Nodes (16): contentForSchema(), EXTENSION_TYPES, fileFacts(), findUpload(), isHttp(), mediaTypeOf(), parseParts(), Part (+8 more)

### Community 148 - "test_flow_safety.py"
Cohesion: 0.20
Nodes (9): _public_failure(), BaseException, port(), fixture, _span(), test_a_long_recording_with_nothing_transcribed_fails_instead_of_publishing_as_ready(), test_a_second_process_cannot_open_the_same_meeting_store(), test_cancel_refuses_a_meeting_that_already_finished() (+1 more)

### Community 149 - "digest.py"
Cohesion: 0.14
Nodes (14): claim_rows(), _clean(), _clean_item(), _due(), _due_supported(), _has_quantity(), True when the figure reads as at least one number the span can be checked for;…, Compact transcript rows for the digest payload: id, m:ss, speaker label, text. (+6 more)

### Community 150 - "test_context.py"
Cohesion: 0.21
Nodes (16): download(), FileNotFoundError, The stored object is bigger than the caller allows., Copy an uploaded object to a private temporary file and return its path. With…, TooLarge, skipif, _items(), test_a_conversion_cached_before_the_cleaning_rule_is_cleaned_when_it_is_read_back() (+8 more)

### Community 151 - "overlap.py"
Cohesion: 0.23
Nodes (11): attach_hypotheses(), build_overlap(), commercial_use_allowed(), Hypothesis, license_id_from_card(), _overlap_ms(), download() is the weight fetch. It runs only after the license allows…, Read the Hugging Face card's structured license field. Prose is not scanned. (+3 more)

### Community 152 - "contracts/schemas/meeting.answer_check.v1.json"
Cohesion: 0.14
Nodes (13): additionalProperties, anyOf, anyOf, type, $id, properties, answer, answer_span_id (+5 more)

### Community 153 - "fixtures/contracts/schemas/meeting.answer_check.v1.json"
Cohesion: 0.14
Nodes (13): additionalProperties, anyOf, anyOf, type, $id, properties, answer, answer_span_id (+5 more)

### Community 155 - "load_library"
Cohesion: 0.22
Nodes (12): clean(), Printable text with tidy spacing, capped; the flag says whether it was cut., _cache_path(), _evict(), load_library(), Path, Converted text is cached per person: identical bytes from someone else must not…, (library, items with status/reason/chars/summary filled in). (+4 more)

### Community 156 - "graph/screenuse.py"
Cohesion: 0.27
Nodes (11): _clock(), batches(), _clip(), _line(), One checked reading per screen. A failed batch leaves the others; a failed pass…, Heading plus the tail. Totals on a record sit after the rows, so a head-only…, Payloads of at most BATCH screens, each with the lines the model is allowed to…, read_screens() (+3 more)

### Community 157 - "summary"
Cohesion: 0.14
Nodes (12): enum, type, content_type, summary, title, items, maxItems, minItems (+4 more)

### Community 158 - "summary"
Cohesion: 0.14
Nodes (12): enum, type, content_type, summary, title, items, maxItems, minItems (+4 more)

### Community 159 - "summary"
Cohesion: 0.14
Nodes (12): enum, type, content_type, summary, title, items, maxItems, minItems (+4 more)

### Community 160 - "summary"
Cohesion: 0.14
Nodes (12): enum, type, content_type, summary, title, items, maxItems, minItems (+4 more)

### Community 161 - "test_screenuse.py"
Cohesion: 0.49
Nodes (10): ground_screen_uses(), Keep a reading only when its screen was in this pack, its citations were shown,…, _pack(), _screen(), _span(), test_a_citation_outside_the_screen_window_is_removed_and_a_difference_needs_one(), test_a_difference_with_no_remaining_citation_is_cleared_and_the_reading_stays(), test_a_figure_that_is_neither_on_the_screen_nor_in_a_cited_line_drops_the_reading() (+2 more)

### Community 162 - "ArtifactCache"
Cohesion: 0.29
Nodes (5): artifact_dir(), artifact_key(), ArtifactCache, Path, test_artifact_cache_round_trips_and_isolates_owner_and_audio()

### Community 163 - "Path"
Cohesion: 0.20
Nodes (7): _load_entrypoints(), load_port(), _load_seed(), Path, Media entrypoint: ffprobe kind plus the model plan. Extensions are not used., One process owns the meeting store. Two writers would each rewrite the whole…, _seed_module()

### Community 164 - "TranscriptCache"
Cohesion: 0.24
Nodes (5): cache_key(), Path, span_items(), TranscriptCache, test_the_cache_is_private_per_owner_audio_context_and_prompt_version()

### Community 165 - "Next steps (hand-over, 2026-10-09)"
Cohesion: 0.18
Nodes (11): Do not do, How to score it (same method as Rounds 12 and 13, so numbers compare), Next steps (hand-over, 2026-10-09), Open defects, in the order worth fixing, Revert criteria for the claim-check paragraph, State of the repository (2026-10-09, after the owner approved committing in logical groups), Still open after this session (not blocked on AWS, not done), The confirming run (about 90 minutes, both recordings concurrently) (+3 more)

### Community 166 - "captions.py"
Cohesion: 0.24
Nodes (12): _bounds(), _cue_text(), _document(), Motivation vs Logic Motivation: Captions are a projection of speech spans onto…, Pack words into lines of at most LINE characters, then pair lines into cues.…, _speech(), _split(), srt() (+4 more)

### Community 167 - "Session"
Cohesion: 0.11
Nodes (6): CountingTransport, ExpiringTransport, Answers HTTP 403 until its credentials are refreshed, like a session token that…, A transport that records how many sessions were opened and can fail from a…, RejectingSession, Session

### Community 168 - "ObjectJobs"
Cohesion: 0.27
Nodes (4): _aws(), _job_item(), ObjectJobs, Job rows in the jobs table. The finished JSON goes to the artifacts bucket.

### Community 169 - "home-loader.tsx"
Cohesion: 0.21
Nodes (11): HomeLoader, HomeObject, HomeLoader(), readColor(), RINGS, Satellite, buildStars(), HomeObject() (+3 more)

### Community 170 - "assemble"
Cohesion: 0.24
Nodes (14): assemble(), classify_file(), classify_streams(), model_plan(), probe(), Path, readable_duration_ms(), extract_frame() (+6 more)

### Community 171 - "Quotient — Repository Architecture"
Cohesion: 0.11
Nodes (19): 1. Client layer (`apps/web`), 2. API / integration layer (`apps/api/quotient`), 3. Analysis worker (`apps/worker`), 4. Contracts (`contracts/`), 5. Infrastructure (`infra/cdk/`), Architectural layers, Local (primary implemented path), Master architecture (+11 more)

### Community 172 - "gist_of"
Cohesion: 0.25
Nodes (8): gist_of(), heading_title(), The title if this line is a heading: a Markdown "# Title", or a short line that…, The first sentence-ish passage that is prose, not a heading, rule, table row or…, test_a_gist_leaves_table_rows_out_of_a_block_that_mixes_prose_and_a_table(), test_a_gist_skips_bold_headings_and_slide_markers(), test_heading_lines_over_the_cap_are_not_headings_and_long_titles_are_cut(), test_headings_and_gist_skip_structure_and_find_the_first_prose()

### Community 173 - "mcp.tsx"
Cohesion: 0.08
Nodes (32): dynamic, metadata, metadata, metadata, ApiScreen(), copy(), originSubscribe(), View (+24 more)

### Community 175 - "start-local-minio.sh"
Cohesion: 0.32
Nodes (7): env_value(), fail(), QUOTIENT_MEDIA_BUCKET, QUOTIENT_S3_ACCESS_KEY_ID, QUOTIENT_S3_ENDPOINT_URL, QUOTIENT_S3_SECRET_ACCESS_KEY, start-local-minio.sh script

### Community 176 - "test_visual_scan.py"
Cohesion: 0.14
Nodes (15): pegasus_output_tokens(), Tokens for one window. Short windows use the vendor floor. Long windows stop at…, build_body(), pack_scenes(), Contiguous windows of about window_ms covering the whole recording. A tail…, window_parts(), test_length_continuation_discards_the_partial_object(), test_output_budget_stays_inside_the_vendor_card_and_times_must_sit_inside_the_part() (+7 more)

### Community 177 - "contracts/schemas/meeting.digest_review.v1.json"
Cohesion: 0.29
Nodes (6): additionalProperties, $id, required, $schema, title, type

### Community 178 - "contracts/schemas/meeting.digest.v1.json"
Cohesion: 0.29
Nodes (6): additionalProperties, $id, required, $schema, title, type

### Community 179 - "fixtures/contracts/schemas/meeting.digest_review.v1.json"
Cohesion: 0.29
Nodes (6): additionalProperties, $id, required, $schema, title, type

### Community 180 - "fixtures/contracts/schemas/meeting.digest.v1.json"
Cohesion: 0.29
Nodes (6): additionalProperties, $id, required, $schema, title, type

### Community 181 - "worker/quotient/seed.py"
Cohesion: 0.42
Nodes (9): install(), _install(), load_into(), _note(), Runner, Motivation vs Logic Motivation: The staging portal lists meetings from the API…, read_remote(), read_state_or_seed() (+1 more)

### Community 182 - "names.py"
Cohesion: 0.67
Nodes (3): global_foundation_arns(), sydney_profile_arns(), tokyo_sonic_arn()

### Community 183 - "build_eval_inputs.py"
Cohesion: 0.53
Nodes (5): build(), clock(), main(), Path, Motivation vs Logic Motivation: Blind scoring needs, per meeting, a plain-text…

### Community 184 - "identity.py"
Cohesion: 0.53
Nodes (5): Identities, screens and the stale flag reach the client; unknown shapes are…, _row(), test_a_stale_analysis_and_a_running_reindex_show_in_the_summary_only_when_they_matter(), test_bad_identity_and_screen_rows_are_dropped_or_clamped(), test_identities_reach_the_span_and_the_page_but_not_typed_names()

### Community 185 - "_port"
Cohesion: 0.53
Nodes (5): _port(), Path, test_a_name_given_to_a_voice_covers_all_its_lines_and_survives_a_rerun(), test_merging_two_voices_makes_one_voice_with_one_name(), test_renaming_one_line_does_not_lock_the_voice()

### Community 186 - "test_seed.py"
Cohesion: 0.42
Nodes (8): _Port, _seed(), test_a_missing_seed_object_installs_nothing(), test_a_non_list_and_an_oversized_document_are_skipped(), test_a_seed_document_is_installed_and_a_damaged_one_is_skipped(), test_install_keeps_an_existing_meeting_and_drops_export_bytes(), test_read_state_or_seed_prefers_state_over_seed(), test_save_remote_state_writes_to_state_key()

### Community 187 - "resources.py"
Cohesion: 0.12
Nodes (32): is_text(), mime_for(), error(), JSON-RPC error codes used by the Quotient MCP endpoint., result(), decode_cursor(), Opaque cursors for MCP list methods., _content() (+24 more)

### Community 188 - "Benchmark results"
Cohesion: 0.40
Nodes (5): Benchmark results, Iteration table (same two recordings, both runs concurrent each time), Scenario A: real meeting recording (`derivatives/meeting-20m.mp4`, 1280x720, 20:00), Scenario B: educational lecture (MIT 18.06 L2, Strang, 20-min slice from 3:00; source archive.org/details/MIT18.06S05_MP4, CC BY-NC-SA), Scenarios C, D, E

### Community 189 - "Round 2: pressure testing (adversarial reviews, failure injection, rubric evaluation)"
Cohesion: 0.40
Nodes (5): Defects found and fixed (all with tests; "live" = also verified in the running app), Independent rubric evaluation (scores 1-5, by an evaluator who read the full transcripts), Round 2: pressure testing (adversarial reviews, failure injection, rubric evaluation), Soak test: the user's 84-minute recording (`src/meeting.mp4`, 14 segments), What this round did not fix (open, with the evidence)

### Community 191 - "alias.mjs"
Cohesion: 0.67
Nodes (3): isFile(), resolve(), root

### Community 192 - "Changes (all in working tree, uncommitted)"
Cohesion: 0.50
Nodes (4): Backend / worker, Changes (all in working tree, uncommitted), Local storage (approved by the user), Portal (`apps/web`)

### Community 193 - "Round 3: from evidence dump to a walkaway (2026-10-08/09)"
Cohesion: 0.50
Nodes (4): Blind rubric evaluation (independent Haiku evaluators; each writes its own 8 key points from the full transcript first), Defects found (all verified) and fixed, New capability, Round 3: from evidence dump to a walkaway (2026-10-08/09)

### Community 194 - "api/quotient/seed.py"
Cohesion: 0.42
Nodes (9): install(), _install(), load_into(), _note(), Runner, Motivation vs Logic Motivation: The staging portal lists meetings from the API…, read_remote(), read_state_or_seed() (+1 more)

### Community 195 - "public.py"
Cohesion: 0.38
Nodes (16): _auth(), _finish(), TestClient, Integration key and /v1 job contract., _recording(), _stack(), test_a_bad_output_spec_is_rejected_before_an_upload_target(), test_a_key_never_expires_and_a_revoked_key_is_rejected() (+8 more)

### Community 197 - "metadata.py"
Cohesion: 0.26
Nodes (8): AuthSettings, bypass_requested(), _csv_origins(), environment_locks_bypass(), load_auth_settings(), _metadata_url(), Motivation vs Logic Motivation: MCP HTTP authorization discovers the…, _resource_origin()

### Community 198 - "asked_span_id"
Cohesion: 0.67
Nodes (3): minLength, type, asked_span_id

### Community 199 - "end_span_id"
Cohesion: 0.67
Nodes (3): minLength, type, end_span_id

### Community 200 - "gist"
Cohesion: 0.67
Nodes (3): minLength, type, gist

### Community 201 - "id"
Cohesion: 0.67
Nodes (3): minLength, type, id

### Community 202 - "name"
Cohesion: 0.67
Nodes (3): minLength, type, name

### Community 203 - "quote"
Cohesion: 0.67
Nodes (3): quote, minLength, type

### Community 204 - "risk"
Cohesion: 0.67
Nodes (3): risk, minLength, type

### Community 205 - "span_id"
Cohesion: 0.67
Nodes (3): span_id, minLength, type

### Community 206 - "span_ids"
Cohesion: 0.67
Nodes (3): span_ids, minItems, type

### Community 207 - "statement"
Cohesion: 0.67
Nodes (3): statement, minLength, type

### Community 208 - "status"
Cohesion: 0.67
Nodes (3): status, enum, type

### Community 209 - "task"
Cohesion: 0.67
Nodes (3): task, minLength, type

### Community 210 - "term"
Cohesion: 0.67
Nodes (3): term, minLength, type

### Community 211 - "text"
Cohesion: 0.67
Nodes (3): text, minLength, type

### Community 212 - "topic"
Cohesion: 0.67
Nodes (3): topic, minLength, type

### Community 213 - "value"
Cohesion: 0.67
Nodes (3): value, minLength, type

### Community 214 - "what"
Cohesion: 0.67
Nodes (3): what, minLength, type

### Community 215 - "asked_span_id"
Cohesion: 0.67
Nodes (3): minLength, type, asked_span_id

### Community 216 - "end_span_id"
Cohesion: 0.67
Nodes (3): minLength, type, end_span_id

### Community 217 - "gist"
Cohesion: 0.67
Nodes (3): minLength, type, gist

### Community 218 - "id"
Cohesion: 0.67
Nodes (3): minLength, type, id

### Community 219 - "name"
Cohesion: 0.67
Nodes (3): minLength, type, name

### Community 220 - "quote"
Cohesion: 0.67
Nodes (3): quote, minLength, type

### Community 221 - "risk"
Cohesion: 0.67
Nodes (3): risk, minLength, type

### Community 222 - "span_id"
Cohesion: 0.67
Nodes (3): span_id, minLength, type

### Community 223 - "span_ids"
Cohesion: 0.67
Nodes (3): span_ids, minItems, type

### Community 224 - "statement"
Cohesion: 0.67
Nodes (3): statement, minLength, type

### Community 225 - "status"
Cohesion: 0.67
Nodes (3): status, enum, type

### Community 226 - "task"
Cohesion: 0.67
Nodes (3): task, minLength, type

### Community 227 - "term"
Cohesion: 0.67
Nodes (3): term, minLength, type

### Community 228 - "text"
Cohesion: 0.67
Nodes (3): text, minLength, type

### Community 229 - "topic"
Cohesion: 0.67
Nodes (3): topic, minLength, type

### Community 230 - "value"
Cohesion: 0.67
Nodes (3): value, minLength, type

### Community 231 - "what"
Cohesion: 0.67
Nodes (3): what, minLength, type

### Community 232 - "asked_span_id"
Cohesion: 0.67
Nodes (3): minLength, type, asked_span_id

### Community 233 - "end_span_id"
Cohesion: 0.67
Nodes (3): minLength, type, end_span_id

### Community 234 - "gist"
Cohesion: 0.67
Nodes (3): minLength, type, gist

### Community 235 - "id"
Cohesion: 0.67
Nodes (3): minLength, type, id

### Community 236 - "name"
Cohesion: 0.67
Nodes (3): minLength, type, name

### Community 237 - "quote"
Cohesion: 0.67
Nodes (3): quote, minLength, type

### Community 238 - "risk"
Cohesion: 0.67
Nodes (3): risk, minLength, type

### Community 239 - "span_id"
Cohesion: 0.67
Nodes (3): span_id, minLength, type

### Community 240 - "span_ids"
Cohesion: 0.67
Nodes (3): span_ids, minItems, type

### Community 241 - "statement"
Cohesion: 0.67
Nodes (3): statement, minLength, type

### Community 242 - "status"
Cohesion: 0.67
Nodes (3): status, enum, type

### Community 243 - "task"
Cohesion: 0.67
Nodes (3): task, minLength, type

### Community 244 - "term"
Cohesion: 0.67
Nodes (3): term, minLength, type

### Community 245 - "text"
Cohesion: 0.67
Nodes (3): text, minLength, type

### Community 246 - "topic"
Cohesion: 0.67
Nodes (3): topic, minLength, type

### Community 247 - "value"
Cohesion: 0.67
Nodes (3): value, minLength, type

### Community 248 - "what"
Cohesion: 0.67
Nodes (3): what, minLength, type

### Community 249 - "asked_span_id"
Cohesion: 0.67
Nodes (3): minLength, type, asked_span_id

### Community 250 - "end_span_id"
Cohesion: 0.67
Nodes (3): minLength, type, end_span_id

### Community 251 - "gist"
Cohesion: 0.67
Nodes (3): minLength, type, gist

### Community 252 - "id"
Cohesion: 0.67
Nodes (3): minLength, type, id

### Community 253 - "name"
Cohesion: 0.67
Nodes (3): minLength, type, name

### Community 254 - "quote"
Cohesion: 0.67
Nodes (3): quote, minLength, type

### Community 255 - "risk"
Cohesion: 0.67
Nodes (3): risk, minLength, type

### Community 256 - "span_id"
Cohesion: 0.67
Nodes (3): span_id, minLength, type

### Community 257 - "span_ids"
Cohesion: 0.67
Nodes (3): span_ids, minItems, type

### Community 258 - "statement"
Cohesion: 0.67
Nodes (3): statement, minLength, type

### Community 259 - "status"
Cohesion: 0.67
Nodes (3): status, enum, type

### Community 260 - "task"
Cohesion: 0.67
Nodes (3): task, minLength, type

### Community 261 - "term"
Cohesion: 0.67
Nodes (3): term, minLength, type

### Community 262 - "text"
Cohesion: 0.67
Nodes (3): text, minLength, type

### Community 263 - "topic"
Cohesion: 0.67
Nodes (3): topic, minLength, type

### Community 264 - "value"
Cohesion: 0.67
Nodes (3): value, minLength, type

### Community 265 - "what"
Cohesion: 0.67
Nodes (3): what, minLength, type

### Community 276 - "ValueError"
Cohesion: 0.40
Nodes (8): _analysis(), _context(), _media(), _outputs(), parse_job(), Motivation vs Logic Motivation: A caller chooses a raw transcript, analysis…, _safe_key(), ValueError

### Community 277 - "test_digest_visual.py"
Cohesion: 0.36
Nodes (7): The on_screen payload: one row per distinct screen, in time order. A screen…, screen_rows(), _screen(), test_a_known_name_is_listed_and_a_conflicting_model_name_is_refused(), test_a_known_name_the_model_confirms_needs_no_spoken_introduction(), test_screen_rows_are_bounded(), test_screen_rows_fold_a_repeated_screen_and_keep_time_order()

### Community 278 - "Architecture gaps and discrepancies"
Cohesion: 0.17
Nodes (12): Architecture gaps and discrepancies, G10 — Orphan / unused worker modules, G1 — Durable meeting state (staging / production), G2 — Step Functions `MeetingMachine` vs worker `Port`, G3 — Separate ECS worker service vs in-process worker, G4 — `docs/staging.md` vs CDK template, G5 — Integration DynamoDB / S3 jobs vs MCP tasks, G6 — Checkpoint store vs CDK `checkpoints` table (+4 more)

### Community 280 - "test_media.py"
Cohesion: 0.13
Nodes (19): NoAudioTrack, The recording has no audio stream, so there is nothing to transcribe., frame_metrics(), idle_spans(), IdleSpan, OpenCV frame-delta and Bhattacharyya histogram distance. Imported only when…, ffmpeg_pcm_args(), Path (+11 more)

### Community 281 - "api/graph.py"
Cohesion: 0.53
Nodes (5): TestClient, GET /v1/jobs/{id}/graph returns spans, speakers, screens, and times., _stack(), test_graph_route_returns_spans_speakers_screens_and_times(), _token()

### Community 282 - "Component inventory"
Cohesion: 0.17
Nodes (12): API — MCP and HTTP, API — worker boundary, Component inventory, Contracts, Entry points, Infrastructure (CDK), Tests (architectural role), Web portal (+4 more)

### Community 283 - "._apply_identity_state"
Cohesion: 0.50
Nodes (3): _final_voice(), Follow merge links to the voice that was kept (a chain is possible, a loop is…, What a person decided about voices outranks a fresh run: merges are replayed on…

### Community 284 - "Execution traces"
Cohesion: 0.18
Nodes (11): Execution traces, Trace T10 — Staging ECS (documented gap), Trace T1 — Local boot, Trace T2 — MCP `submit_meeting` (portal upload), Trace T3 — MCP `submit_meeting` (derivatives CLI path), Trace T4 — Quality loop (single analysis run), Trace T5 — Ingest / media parallel path, Trace T6 — MCP `read_graph` / resources (+3 more)

### Community 288 - "test_ingest_upload.py"
Cohesion: 0.18
Nodes (5): Checkpointed quality loop. A replay of the same idempotency key returns the…, parametrize, test_local_s3_video_ingest_records_skipped_visual_analysis(), test_pegasus_parts_go_to_the_aws_bucket_when_media_is_on_minio(), test_upload_failure_is_actionable_without_leaking_cli_output()

### Community 289 - "test_one_open_span_is_not_coarse_and_raw_text_is_immutable"
Cohesion: 0.25
Nodes (5): FakeClock, pytest_raises_immutable(), test_handoff_writes_a_seam_and_carries_text_history(), test_one_open_span_is_not_coarse_and_raw_text_is_immutable(), Transport

### Community 290 - ".wrap"
Cohesion: 0.25
Nodes (7): _blob_header(), _encode_frame_raw(), _EventSigner, _open_h2(), Chains the HTTP signature into each Sonic event. The secret is not logged., _signing_key(), _streaming_headers()

### Community 291 - "diarize_pcm"
Cohesion: 0.31
Nodes (8): attach_speakers(), diarize_pcm(), _kill_group(), Path, _python(), Give each speech span the speaker who talks longest inside it; mark spans with…, Speaker turns for 16 kHz mono 16-bit PCM, or None when diarization is…, test_speakers_attach_by_largest_overlap_and_mark_shared_spans()

### Community 293 - "datetime"
Cohesion: 0.40
Nodes (3): _timestamp_header(), datetime, Submit one media object to the local Quotient MCP API and record a benchmark.…

### Community 299 - "._post"
Cohesion: 0.33
Nodes (4): _audit_llm(), _elapsed_ms(), _pegasus_response(), test_pegasus_1_5_stop_reason_becomes_finish_reason()

### Community 300 - "iam_credentials"
Cohesion: 0.33
Nodes (5): _auth_headers(), bearer_token(), _container_credentials(), iam_credentials(), Session credentials for SigV4. The Bedrock API key is not logged and is not…

### Community 301 - "_send_all"
Cohesion: 0.38
Nodes (5): _send_all(), test_respond_posts_to_converse_and_never_the_responses_endpoint(), test_send_all_gives_up_after_its_deadline(), test_send_all_waits_for_a_busy_non_blocking_socket_instead_of_failing(), test_send_all_waits_for_readability_when_tls_needs_to_read_first()

### Community 302 - "IndexedSpan"
Cohesion: 0.73
Nodes (5): apply_omissions(), IndexedSpan, payload_duration_ms(), source_duration_ms(), test_compaction_never_drops_overlap_and_keeps_the_index()

## Knowledge Gaps
- **1050 isolated node(s):** `quotient-api`, `dynamic`, `dynamic`, `metadata`, `RELEASE` (+1045 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1560 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **41 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Table` connect `sandbox.py` to `MeetingCompute`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Why does `MeetingTables` connect `MeetingCompute` to `cluster.py`, `stack.py`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Why does `Port` connect `Port` to `quotient/port.py`, `._save_locked`, `test_context_port.py`, `test_port_persistence.py`, `NotInvocable`, `public/jobs.py`, `test_flow_safety.py`, `._apply_identity_state`, `.media_url`, `Path`, `test_media_robustness.py`, `quality.py`, `test_loop.py`, `_port`, `WorkerPort`, `resolve_visual`, `ingest.py`, `Registry`, `Span`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `Port` (e.g. with `Reasoner` and `Transport`) actually correct?**
  _`Port` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `MemoryPort` (e.g. with `PortError` and `test_brief_withholds_unresolved_claims_and_captions_use_source_time()`) actually correct?**
  _`MemoryPort` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `create_app()` (e.g. with `TokenVerifier` and `KeyDirectory`) actually correct?**
  _`create_app()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `quotient-api`, `dynamic`, `dynamic` to the rest of the system?**
  _1050 weakly-connected nodes found - possible documentation gaps or missing edges._