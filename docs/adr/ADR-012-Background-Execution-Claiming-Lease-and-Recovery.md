# ADR-012: Background Execution, Claiming, Lease and Recovery

## Status

Accepted — PF-06

## Context

PF-05 exposed research via synchronous HTTP execution (ADR-011). PF-06 moves workflow runtime execution to a background worker so `POST /projects/{id}/research` returns before workflow execution completes.

PostgreSQL remains the source of truth for WorkflowRun aggregates, optimistic versioning, task results, and execution logs.

## Decision

### HTTP semantics (supersedes ADR-011 synchronous research policy)

- `POST /projects/{id}/research` → **202 Accepted** with `Location: /workflow-runs/{run_id}` on supported backends
- **Never** calls `WorkflowEngine.run` in the HTTP request path
- Unsupported backends (e.g. `file`) → **409** `durable_execution_unavailable` — no silent inline fallback
- `POST /workflow-runs/{id}/resume` → **202 Accepted** for resumable runs; **200** for terminal runs
- `GET /workflow-runs/{id}` is the polling contract

### Synchronous planning / async execution (PF-06)

`POST /research` in order:

1. Validate request
2. Run planning **synchronously** in the API process (LLM)
3. Persist `WorkflowTemplate` snapshot
4. Persist durable `WorkflowRun` (CREATED)
5. Notify/submit for background worker
6. Return **202**

**202 means workflow execution is accepted for background processing**, not that planning is async. Planning latency affects HTTP response time. Async planning/submission is deferred.

`WorkflowEngine` runs **only in the worker** (or in-process test coordinator).

### Backend capabilities

Configured via `BACKGROUND_EXECUTION_MODE` (`disabled` | `embedded` | `external`):

| Topology | HTTP 202 | In-process drain | Multi-process worker |
|---|---|---|---|
| PostgreSQL + `external` (default) | Yes | Yes (tests) | Yes (production) |
| Memory + `embedded` (explicit) | Yes | Yes (tests only) | **No** |
| Memory without `embedded` | **No** (409) | No | No |
| File | **No** (409) | No | No |

Capability is resolved in `application/runtime/background_execution_capability.py` and exposed via `ApplicationContainer`. Routers do not inspect backend strings directly.

### Planner behavior

- Planning remains **synchronous** before 202 in the API process
- Production runtime uses the configured LLM client (`OPENAI_API_KEY`)
- `DeterministicLLMClient` is a **test/smoke fixture only**; enable with `DETERMINISTIC_PLANNER=1` explicitly (e.g. `docker-compose.smoke.yml`, CI)

### Source of truth

- **PostgreSQL WorkflowRun row** is authoritative
- **Lease columns**: `claimed_by`, `lease_expires_at`, `heartbeat_at`
- No Redis in PF-06; workers poll PostgreSQL with `FOR UPDATE SKIP LOCKED`

### Claim / lease model

- Worker must hold a valid lease before `execute_claimed_run`
- Claim is atomic; does not perform domain status transitions
- Heartbeat renews lease; verifies `claimed_by`
- `release_lease` is owner-checked — stale worker cannot clear a reclaimed lease

### Lost lease guarantee (cooperative, not preemptive)

- Heartbeat detects lost ownership and marks `LeaseGuard` lost
- **No further durable checkpoint** may commit as the old owner after loss is observed
- Worker aborts at the next cooperative guard/checkpoint boundary
- An in-flight executor may complete local/external side effects before the main path observes loss
- Interrupted `RUNNING` tasks are **not** automatically retried (PF-04 policy)

### Stale lease recovery

- Expired lease → another worker reclaims atomically
- PF-04 marks orphaned `RUNNING` task **FAILED**; dependents **SKIPPED**

### Queue

- `NoOpRunQueue` — polling only; lost notification cannot lose work

### Worker process

- Entry point: `python -m worker.main`
- Healthcheck requires PostgreSQL readiness **and** multi-process capability
- Docker Compose: `api` + `worker` + `postgres`

### Deferred

- Redis, SSE/WebSockets, async planning jobs, automatic non-idempotent retries, n8n

## Consequences

- Alembic `002_pf06_worker_leases` required for PostgreSQL
- Process-level crash/recovery integration test validates reclaim behavior
- Memory backend is for embedded/unit/API tests with in-process `drain_runnable_runs`, not separate worker deployment
