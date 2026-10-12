# Architecture gaps and discrepancies

Items where documentation, infrastructure, or expectations diverge from **verified** application code. Uncertainty is stated explicitly; nothing below is marked implemented without evidence.

## G1 — Durable meeting state (staging / production)

| Source | Claim |
| --- | --- |
| `README.md` Known limitations | Meeting state in API process memory; DynamoDB tables from stack not used for meetings |
| `apps/worker/quotient/port.py` | Persists to `.local/run/meetings.json` only in local mode with file locking |
| `apps/api/quotient/worker/memory.py` | Non-local fallback can degrade to in-memory `MemoryPort` if worker load fails |

**Gap:** No repository implementation found that writes full meeting ledgers to `axion-meeting-staging-*` DynamoDB tables for live meetings.

**Impact:** ECS API task restart loses in-memory rows; README aligns with code.

---

## G2 — Step Functions `MeetingMachine` vs worker `Port`

| Source | Claim |
| --- | --- |
| `infra/cdk/workflow/machine.py` | SQS token stages: media → sonic∥pegasus → ten council stages → exports |
| `infra/cdk/quotient/stack.py` | `STATE_MACHINE_ARN` on API and worker containers |
| `apps/**` grep `STATE_MACHINE` | **No references** |

**Gap:** CDK defines a distributed workflow; the **implemented** analysis path is `Port._analyze` → `loop/quality.run` in a daemon thread (local: same process as API).

**Status:** SFN is **CDK-only** relative to `apps/` at documentation time. Whether staging worker image uses queue/SFN is **not evidenced** in application source (may exist only in unreleased operator wiring).

---

## G3 — Separate ECS worker service vs in-process worker

| Source | Claim |
| --- | --- |
| `scripts/start-local.sh` comment | Worker in-process via `load_worker_port` |
| `infra/cdk/compute/cluster.py` | Distinct `worker` service scaled on queue depth |

**Gap:** Two deployment models in repo; only in-process `WorkerPort` is fully traced in Python. Fargate worker entrypoint not documented in this pack (search: no second `__main__` for worker service in `apps/worker`).

**Action for operators:** Confirm container command in CDK task definition (`cluster.py` worker container) when documenting runtime staging behavior.

---

## G4 — `docs/staging.md` vs CDK template

Subagent/CDK review noted drift:

| Topic | Older doc risk | Template evidence (`infra/cdk/`) |
| --- | --- | --- |
| API autoscaling max | May say 2 | Pinned max 1 (comment: single task holds meeting state) |
| DynamoDB table count | May say 3 | Four tables including `keys` |
| ECR repos | May say 2 | api, web, worker |
| Log groups | May omit web | Includes web log group |

**Gap:** Human staging doc may be stale; prefer CDK source and [diagrams/10-infra-staging.mmd](./diagrams/10-infra-staging.mmd).

---

## G5 — Integration DynamoDB / S3 jobs vs MCP tasks

| Component | Scope |
| --- | --- |
| `mcp/tasks.py` `TaskBoard` | In-memory per API process |
| `public/jobs.py` `JobBoard` | File or Dynamo + S3 when env tables set |

**Gap:** Two job systems; MCP concurrent limit (`MAX_CONCURRENT=8`) documented bypass with short TTLs in README security section — not fixed in code at doc time.

---

## G6 — Checkpoint store vs CDK `checkpoints` table

| Source | Behavior |
| --- | --- |
| `apps/worker/loop/store.py` | `MemoryStore` — process memory only |
| `infra/cdk/storage/tables.py` | `checkpoints` DynamoDB table provisioned |

**Gap:** Table exists in IaC; worker quality checkpointing does not use it in traced code.

---

## G7 — OAuth / TLS staging

| Source | Behavior |
| --- | --- |
| `infra/cdk/auth/pool.py` | Callbacks `http://localhost:3000` |
| `infra/cdk/compute/cluster.py` | ALB HTTP port 80, no ACM in template |
| `MCP.md` / README | Production auth expectations |

**Gap:** Staging template is HTTP + localhost-oriented Cognito; not production-hardened as-is.

---

## G8 — Planned / partial features (README-aligned)

| Feature | Evidence |
| --- | --- |
| Long recording soak | README: 84-minute run never completed |
| Production licence / security policy | README ownership section |
| Durable exports after API restart | `port.py`: `burned.mp4` and in-memory `_exports` not in JSON file |
| Second-tier "likely" in brief | Implemented as confidence marker in portal; gate still treats non-supported as review |

---

## G9 — Graphify index staleness

| Item | Value |
| --- | --- |
| `graphify-out/GRAPH_REPORT.md` | Built commit `1b50ce87` |
| Git HEAD at doc time | `648c9ed` |

**Gap:** Graph-assisted discovery may miss edits after `1b50ce87`. Run `graphify update .` after substantive changes.

---

## G10 — Orphan / unused worker modules

| Path | Note |
| --- | --- |
| `apps/worker/idle.py` | Present; primary idle handling also in `media/idle.py` — relationship not fully traced in this pass |

**Status:** Listed for future graphify path audit; not claimed as dead code.

---

## Validation limitations

- No live staging ECS or Bedrock calls were made during architecture documentation.
- Test suites (`tests/`) prove contracts offline with fake transports; they do not prove staging wiring.
- Mermaid diagrams validated syntactically via `@mermaid-js/mermaid-cli`; semantic accuracy depends on source citations in [COMPONENT_INVENTORY.md](./COMPONENT_INVENTORY.md).
