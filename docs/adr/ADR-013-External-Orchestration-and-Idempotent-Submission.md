# PF-07: External Orchestration and Idempotent Submission

## Status

Accepted — PF-07

## Context

PF-06 established HTTP 202 background submission, worker execution, and polling via
`GET /workflow-runs/{id}`. External orchestrators such as n8n must integrate over HTTP
only without direct database or internal Python module access.

## Decision

### Roles

| Component | Role |
|---|---|
| n8n / external client | Business/process orchestration, retries, branching |
| HTTP API | Validation, synchronous planning, durable submission |
| Worker | WorkflowEngine execution, claiming, recovery |
| PostgreSQL | Source of truth for runs, idempotency, correlation |

n8n never schedules internal research tasks. AI Research OS owns WorkflowTemplate
construction, WorkflowRun lifecycle, task scheduling, execution, checkpointing, and
recovery.

### Idempotency

- Header: `Idempotency-Key` on `POST /projects/{id}/research`
- Scoped uniquely per `(project_id, idempotency_key)`
- Durable table: `research_submissions` (Alembic `003_pf07_research_submissions`)
- Atomic first-create via PostgreSQL `INSERT ... ON CONFLICT DO NOTHING`
- Same key + same semantic fingerprint → replay same `run_id` (202)
- Same key + different fingerprint → **409** `idempotency_conflict`
- No key → existing behavior (non-idempotent submission)

Request fingerprint uses canonical JSON of `project_id` + brief fields only.
Excludes `correlation_id`, `source`, timestamps, callback metadata, and transport
headers.

#### Submission state machine

| State | Meaning | Replay behavior |
|---|---|---|
| `pending` | Key claimed; `run_id` pre-assigned; WorkflowRun may not exist yet | Continue submission (plan + persist run) or return existing run if already created |
| `completed` | WorkflowRun successfully created and bound | Return same `run_id` (202, `idempotent_replay=true`) |
| (absent) | Planning/submit failed; row deleted | Key reusable; treated as new submission |

- **Exactly-once WorkflowRun:** one idempotency key creates at most one WorkflowRun.
- **Planning:** best-effort once per completed run; concurrent `pending` peers wait for
  the winning submission via bounded reconciliation instead of racing through planning.
  Duplicate planning can still occur only when a stale `pending` submission times out
  and a takeover request resumes work (crash-recovery path).
- **Crash recovery:** stale `pending` without a run retries planning; stale `pending`
  with an existing run binds completion without creating a duplicate run.
- **Failure:** explicit exception during planning/submit deletes the submission row
  (key not poisoned). No internal error traces are exposed to API clients.
- **PostgreSQL** is the source of truth across API restarts; polling remains the
  orchestration model (no callbacks in PF-07).

### Correlation model (application/persistence layer, not Domain)

| Field | Purpose |
|---|---|
| `correlation_id` | Business/process correlation (body or `X-Correlation-ID`) |
| `external_request_id` | Idempotency-Key when supplied |
| `source` | Caller label (e.g. `n8n`) |

Stored in `research_submissions`, exposed on run responses under `external`.

### Polling contract

`GET /workflow-runs/{id}` exposes `is_terminal`, task summary, `results_available`,
`artifacts_available`, and optional `external` metadata. Recommended poll interval:
**2–5 seconds**, bounded total timeout at orchestrator discretion.

### Results contract

`GET /workflow-runs/{id}/results` includes `results_ready` (true only when terminal),
`status`, `is_terminal`, and task snapshots.

### Callbacks

**Polling-only for PF-07.** Outbound webhooks deferred to avoid delivery infrastructure
and ambiguous guarantees. Callback failure must never alter workflow outcome.

### API versioning

**Deferred.** Paths remain unversioned (`/projects`, `/workflow-runs`). External
workflows will pin host + OpenAPI contract; `/api/v1` introduction requires a
migration strategy and is planned for a later phase.

### Authentication

**Deferred to PF-08.** Local n8n integration is unauthenticated with explicit
documentation warning. Do not expose local stack to public internet.

### n8n local development

Optional `docker-compose.n8n.yml` override. n8n talks to `http://api:8000` only.
Example workflows live in `examples/n8n/`.

## Consequences

- PostgreSQL required for durable idempotency across API restarts
- Memory backend supports in-process idempotency for tests only
- File backend has no idempotency store
- Worker/runtime behavior unchanged regardless of external source

## Deferred

- OAuth/RBAC, API gateway, outbound webhooks, `/api/v1`, Redis, message brokers
