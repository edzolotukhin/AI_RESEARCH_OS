# ADR-009: Persistence Boundary and Repository Strategy

**Status:** Active
**Date:** 2026-07-31

---

## Context

Phase B runtime hardening is complete. The synchronous workflow engine, planner contract, and dependency-aware scheduling are implemented and tested (289 automated tests).

Current persistence is minimal:

- `infrastructure/project_repository.py` writes `Project` snapshots to JSON under a configurable directory root.
- Only `create_project()` and `save_project()` are implemented; `load_project()`, `list_projects()`, and `delete_project()` raise `NotImplementedError`.
- Serialization uses `dataclasses.asdict(project)` without a dedicated mapper or schema version.
- `WorkflowTemplate`, `WorkflowRun`, `Task`, execution results, artifacts, and logs are **not** durably persisted in the production path.
- `WorkflowContext` fields (`shared_state`, `intermediate_results`, `artifacts`, `execution_metadata`) are transient and live only for the duration of a run.
- `Agency` and `ApplicationOverrides` depend on the concrete `ProjectRepository` class, not a port.
- `Project.runs: list[WorkflowRun]` exists on the domain model but is not populated by the current runtime flow.

Product Foundation requires PostgreSQL, repository implementations, migrations, FastAPI, background execution, and Docker Compose — without coupling the domain or runtime loop to SQLAlchemy, transport schemas, or container topology.

Direct mapping of mutable runtime objects (especially `WorkflowRun`, `Task`, and `TaskDependencyGraph`) to normalized tables would blur definition/runtime boundaries, complicate state-machine enforcement, and make crash recovery ambiguous.

---

## Decision

Adopt a **ports-and-adapters persistence strategy**:

```
Domain models (unchanged public shape)
        ↑
Repository ports (application/domain-facing interfaces)
        ↑
Persistence adapters (file, in-memory, PostgreSQL)
        ↑
Storage records / ORM models (infrastructure only)
        ↑
PostgreSQL (or test doubles)
```

### Aggregate boundaries

| Aggregate / entity | Layer | Root? | Durable? | Mutability | Storage owner |
|--------------------|-------|-------|----------|------------|---------------|
| **Project** | Business | Yes | Yes | Mutable | `ProjectRepository` |
| **WorkflowTemplate** (+ embedded **TaskDefinition**) | Definition | Yes (versioned snapshot) | Yes | Immutable after publish | `WorkflowTemplateRepository` |
| **WorkflowRun** (+ **Task**, **TaskDependencyGraph**) | Runtime | Yes | Yes | Mutable during execution | `WorkflowRunRepository` |
| **Task result** (per-task output summary) | Runtime | No — child of run | Yes | Append / replace per task | via `WorkflowRunRepository` or `ExecutionLogRepository` |
| **Execution log** (attempt / event stream) | Runtime audit | No — scoped to run/task | Yes | Append-only | `ExecutionLogRepository` |
| **Artifact** (generated deliverable) | Business output | Yes | Yes | Mutable until published | `ArtifactRepository` |
| **Knowledge item** (project-scoped reference) | Business | Yes | Yes | Mutable | `KnowledgeRepository` |
| **Agency configuration** | Application | No | Config only | Environment-driven | Not an aggregate — env / config service |
| **WorkflowContext** | Execution session | No | No | Transient | Not persisted as a blob; mapped to run + task results + logs |
| **Executor** | Infrastructure | No | No | N/A | Registry wiring only |

**Rules:**

1. **Definition and runtime are persisted separately.** A `WorkflowTemplate` snapshot is stored when planning completes. A `WorkflowRun` references `workflow_template_id` and stores runtime task state — it does not mutate the template row/document.
2. **Tasks are persisted through the `WorkflowRun` aggregate.** External code does not update task rows independently except through repository operations that load the run aggregate, apply domain transitions, and save atomically.
3. **Transient execution context is decomposed.** Do not persist `WorkflowContext` as a single JSON document. Map durable subsets: run status, task statuses, structured task results, append-only execution events, artifact references.

### Repository strategy

Introduce **repository ports** in the application layer (or a dedicated `application/ports/` package). Infrastructure provides adapters.

| Port | Aggregate | Required operations (initial) | Query boundary |
|------|-----------|-------------------------------|----------------|
| **ProjectRepository** | `Project` | `create`, `save`, `get_by_id`, `list`, `delete` | By project id; list with pagination/filter by status |
| **WorkflowTemplateRepository** | `WorkflowTemplate` | `save_snapshot`, `get_by_id`, `list_for_project` | By template id; by owning project |
| **WorkflowRunRepository** | `WorkflowRun` | `create`, `get_by_id`, `save`, `list_for_project` | By run id; by project + status |
| **ArtifactRepository** | `Artifact` | `save`, `get_by_id`, `list_for_project`, `list_for_run` | By project/run; optional type filter |
| **KnowledgeRepository** | Knowledge item (new persistence record; maps from static files today) | `save`, `get_by_id`, `list_for_project`, `delete` | By project scope |
| **ExecutionLogRepository** | Execution log entry | `append`, `list_for_run`, `list_for_task` | Append-only; by run/task, time-ordered |

Avoid generic `CRUD[T]` repositories. Each port expresses aggregate semantics.

**Repository construction rule:** Repositories persist aggregates; they never construct business objects. `ProjectFactory` creates projects; `WorkflowRunFactory` assembles runs from templates; repositories receive fully constructed aggregates via `create()` or `save()`.

**ProjectRepository semantics:** `create()` accepts only new aggregates (rejects duplicate IDs, initializes version). `save()` accepts only existing aggregates (rejects missing IDs, enforces optimistic concurrency).

**WorkflowRunRepository semantics:** `create(workflow_run, project_id=...)` persists a pre-built aggregate. Assembly from `WorkflowTemplate` belongs to `WorkflowRunFactory` in the application layer.

**Partial updates:** Not exposed at the port level for `WorkflowRun`. Callers pass the aggregate (or a domain command that mutates it); the adapter persists the full consistent snapshot or uses internal row mapping with aggregate-level locking.

**Optimistic concurrency:** `WorkflowRun` and `Project` carry a monotonic `version` or `updated_at` token at the persistence record layer. Saves reject stale writes (`ConcurrentModificationError` at port boundary).

### Domain / ORM separation

- Domain models remain plain Python dataclasses / domain types with state machines.
- SQLAlchemy (or other ORM) models live under `infrastructure/persistence/records/` (or equivalent).
- Mappers translate record ↔ domain in adapters only.
- FastAPI request/response schemas live in the API layer and **must not** be used as ORM models.
- Domain must not import `infrastructure`, SQLAlchemy, FastAPI, or Docker SDK.

### Transaction model

| Scenario | Atomic unit | Idempotency note |
|----------|-------------|------------------|
| Create `WorkflowRun` + tasks + dependency graph | Single transaction | Application layer builds aggregate via `WorkflowRunFactory`; repository `create()` keyed by run id; reject duplicate create with same id |
| Start task (claim / `RUNNING`) | Single transaction: load run, transition one task, save run | Worker retry must tolerate already-`RUNNING` same attempt token |
| Complete task | Single transaction: task → terminal, persist result summary, save run | Completion handler idempotent on `(run_id, task_id, attempt_id)` |
| Fail task | Same as complete | Same idempotency key |
| Finalize `WorkflowRun` | Single transaction: workflow status terminal + optional completion metadata | Finalize noop if already terminal with same outcome |
| Append execution log | Single insert transaction | Append-only; duplicate `(event_id)` ignored |
| Persist artifact metadata (+ blob ref) | Transaction: artifact row + optional link to run/project | Content-addressable or unique artifact id |
| Recover interrupted workflow | Load run aggregate at last committed state; scheduler resumes from task statuses | No automatic re-execution of `RUNNING` tasks without explicit reclaim policy (deferred to PF-06) |

Operations that **must be atomic:** run creation, task state transition + run save, workflow finalization, artifact metadata + linkage.

Operations that **may be eventually consistent:** large artifact blob upload (metadata transaction after blob store succeeds).

### Concurrency and idempotency

- Single-process runtime today; Product Foundation background workers introduce concurrent claim races.
- Task claim uses optimistic locking on the run aggregate version.
- Execution log entries carry stable `event_id` for at-least-once writers.
- Background worker implementations (PF-06) must document reclaim timeout for stuck `RUNNING` tasks.

### Docker-readiness constraints (implementation phase)

Future persistence implementations must:

- Read database URL, credentials, and paths from environment variables.
- Never hard-code hostnames, Windows paths, or credentials in source.
- Run locally and inside containers with the same configuration contract.
- Allow PostgreSQL to be replaced by in-memory or test-container adapters in tests.
- Run schema migrations as an **explicit** step (`migrate` command or init job), not implicit DDL on application import.
- Prevent container startup from silently mutating production schema.
- Treat Docker Compose as development orchestration only — not a domain dependency.

Dockerfile and `compose.yaml` are **out of scope** for PF-01.

---

## Alternatives considered

### 1. Persist entire `WorkflowContext` as JSON per step

**Rejected.** Hides domain state, breaks state-machine guarantees, complicates partial recovery, and couples storage to session shape.

### 2. Single `Project` JSON document containing runs and tasks (extend current file repo)

**Rejected.** Does not scale for concurrent workers, optimistic locking, or query boundaries; `asdict` cannot round-trip `TaskDependencyGraph`, enums, and nested aggregates safely.

### 3. Domain models as SQLAlchemy mapped classes

**Rejected.** Couples business rules to ORM session lifecycle and migration churn; violates current layer boundaries.

### 4. Generic CRUD repository per table

**Rejected.** Encourages cross-aggregate updates and bypasses `WorkflowRun` as consistency boundary.

### 5. Event sourcing for all runtime state

**Deferred.** Valuable for audit/recovery but excessive for PF-02/PF-03; execution log provides partial audit without full event sourcing.

---

## Consequences

### Positive

- Clear migration path from file-based `ProjectRepository` to PostgreSQL without changing domain models.
- Runtime loop continues to operate on in-memory aggregates; persistence is explicit at application boundaries.
- Test adapters (in-memory) can validate port contracts before PostgreSQL lands.
- API and worker layers can share the same ports.

### Negative

- Mapping layer and migrations add implementation cost (PF-02–PF-04).
- Aggregate-level saves may write more rows than naive per-field PATCH APIs.
- `Project.runs` list on the domain model may diverge from persisted query model until explicitly modeled or deprecated in a future ADR.

### Neutral

- Existing file-based `ProjectRepository` remains in place until an adapter implements the new port; runtime behavior unchanged in PF-01.

---

## Deferred decisions

| Topic | Target phase |
|-------|----------------|
| Exact SQLAlchemy version | PF-03 |
| Sync vs async database access | PF-03 |
| Migration tool (Alembic config, naming) | PF-03 |
| PostgreSQL schema details (table layout, indexes) | PF-03 |
| Background worker technology | PF-06 |
| Redis (claim locks, queues) | PF-06+ |
| Blob storage for artifact content (filesystem vs S3-compatible) | PF-04+ |
| n8n integration topology | Later |
| Deployment topology (single vs multi-service) | Later |
| Whether to remove or repurpose `Project.runs` in-memory list | Future ADR |
| `WorkflowRun.project_id` on domain model vs persistence record | PF-03 |
| Full `Project` aggregate mapping (replace transitional file adapter) | PF-03 |

---

## PF-03 implementation notes (2026-07-31)

PF-03 adds `infrastructure/persistence/postgresql/` with SQLAlchemy 2.x ORM models, explicit mappers, repository adapters, Alembic migrations, and Docker Compose (PostgreSQL only). Key outcomes:

- **Backend selection:** `PERSISTENCE_BACKEND=file|memory|postgresql` via `build_persistence_bundle()` in the composition root.
- **WorkflowRun ownership:** `project_id` on the domain aggregate and `workflow_runs.project_id` FK.
- **Artifact persistence:** `ArtifactRecord` remains an application persistence DTO (not a domain aggregate).
- **Optimistic concurrency:** atomic `UPDATE … WHERE version = expected` for `Project` and `WorkflowRun`.
- **Execution logs:** append-only rows; duplicate `event_id` is an idempotent no-op.
- **Unit of Work:** not introduced; one repository operation per service method with per-method session/transaction in adapters.
- **Schema:** normalized tables for aggregate roots and task children; JSONB for nested Project value objects and dependency graph snapshots.

---

## Related ADRs

- [ADR-008: Executor Catalog Contract](ADR-008-Executor-Catalog-Contract.md)
- ADR-001 Project Model (Planned — align during PF-02)
- ADR-002 Workflow Architecture (Planned — align during PF-02)
- ADR-006 Artifact Model (Planned — align during PF-04+)

---

## References

- [architecture/product-foundation-persistence.md](../../architecture/product-foundation-persistence.md)
- Current implementation: `infrastructure/project_repository.py`
- Runtime factories: `domain/factories/workflow_run_factory.py`, `domain/factories/task_factory.py`
