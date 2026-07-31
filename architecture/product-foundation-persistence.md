# Product Foundation — Persistence Architecture

This document defines the persistence contract for Product Foundation (PF-01). It does **not** introduce PostgreSQL, ORM models, migrations, or API code. Runtime behavior remains unchanged until PF-02+.

**Authoritative decision record:** [ADR-009: Persistence Boundary and Repository Strategy](../docs/adr/ADR-009-Persistence-Boundary-and-Repository-Strategy.md)

---

## Persistence context

```mermaid
flowchart TB
    subgraph domain [Domain Layer]
        P[Project]
        WT[WorkflowTemplate]
        TD[TaskDefinition]
        WR[WorkflowRun]
        T[Task]
        A[Artifact]
        K[Knowledge item]
    end

    subgraph app [Application Layer]
        Ports[Repository ports]
        WE[WorkflowEngine]
        Agency[Agency]
    end

    subgraph infra [Infrastructure Layer]
        FileAdapter[File adapter - current]
        MemAdapter[In-memory adapter - PF-02]
        PgAdapter[PostgreSQL adapter - PF-03]
        ORM[Persistence records / ORM]
    end

    subgraph external [External]
        PG[(PostgreSQL)]
        FS[Project filesystem dirs]
    end

    Agency --> Ports
    WE --> Ports
    Ports --> FileAdapter
    Ports --> MemAdapter
    Ports --> PgAdapter
    FileAdapter --> FS
    PgAdapter --> ORM
    ORM --> PG

    P -.-> Ports
    WT -.-> Ports
    WR -.-> Ports
    A -.-> Ports
    K -.-> Ports
    TD --> WT
    T --> WR
```

**Current state:** Only `Project` metadata is partially persisted via `infrastructure/project_repository.py` (JSON + directory scaffold). All workflow runtime objects are in-memory for the duration of `Agency.start_research()`.

---

## Aggregate ownership

| Object | Definition / runtime | Aggregate root | Durable | Mutable | Storage ownership | Repository access |
|--------|---------------------|----------------|---------|---------|-------------------|-------------------|
| Agency configuration | Application config | No | Env/config only | N/A | Environment / `ApplicationConfig` | Not a repository |
| **Project** | Business | **Yes** | Yes | Mutable | Project record + directory scaffold | `ProjectRepository` |
| **WorkflowTemplate** | Definition | **Yes** | Yes | Immutable snapshot | Template store | `WorkflowTemplateRepository` |
| **TaskDefinition** | Definition | No (child of template) | Yes (embedded in template) | Immutable | With template | Via template repository |
| **WorkflowRun** | Runtime | **Yes** | Yes | Mutable (state machine) | Run store | `WorkflowRunRepository` |
| **Task** | Runtime | No (child of run) | Yes | Mutable (state machine) | With run | Via run repository only |
| **TaskDependencyGraph** | Runtime | No (child of run) | Yes | Rebuilt at create; edges immutable | With run | Via run repository only |
| **Task result** | Runtime output | No | Yes | Replace per task completion | With run or log | Run save or log append |
| **Execution log** | Runtime audit | No (scoped to run/task) | Yes | Append-only | Log store | `ExecutionLogRepository` |
| **Artifact** | Business output | **Yes** | Yes | Mutable until published | Artifact store + blob ref | `ArtifactRepository` |
| **Knowledge item** | Business reference | **Yes** | Yes | Mutable | Knowledge store / files | `KnowledgeRepository` |
| **WorkflowContext** | Execution session | No | **No** | Transient | Not persisted as blob | Decomposed into run/results/logs |
| **Executor** | Infrastructure | No | No | Registry wiring | Code registry | Not persisted |

---

## Repository contract

| Repository | Aggregate managed | Required operations | Query boundaries | Transaction boundary | Partial updates | Optimistic concurrency | Child persistence |
|------------|--------------------|--------------------|------------------|---------------------|-----------------|------------------------|-------------------|
| **ProjectRepository** | `Project` | `create`, `save`, `get_by_id`, `list`, `delete` | By id; list with filters | Per project save | Full aggregate replace | `version` / `updated_at` on save | N/A |
| **WorkflowTemplateRepository** | `WorkflowTemplate` (+ definitions) | `save_snapshot`, `get_by_id`, `list_for_project` | By template id; by project | Per template snapshot | No — immutable snapshot | Optional content hash dedup | TaskDefinitions embedded |
| **WorkflowRunRepository** | `WorkflowRun` (+ tasks, graph) | `create_from_template`, `get_by_id`, `save`, `list_for_project` | By run id; by project + status | Per run lifecycle transition | No — aggregate save | Required on `save` | Tasks and graph via root |
| **ArtifactRepository** | `Artifact` | `save`, `get_by_id`, `list_for_project`, `list_for_run` | By project/run/type | Metadata + linkage | Metadata fields only after create | On metadata update | Optional run/project FK |
| **KnowledgeRepository** | Knowledge item | `save`, `get_by_id`, `list_for_project`, `delete` | By project scope | Per item | Allowed for content/metadata | On update | N/A |
| **ExecutionLogRepository** | Log entry | `append`, `list_for_run`, `list_for_task` | Time-ordered by run/task | Per append | N/A (append-only) | N/A | Scoped to run/task |

---

## Transaction scenarios

### 1. Create WorkflowRun and Tasks

```
BEGIN
  INSERT workflow_run (id, project_id, template_id, status=CREATED, version=1)
  INSERT tasks[] from template
  INSERT dependency_edges[] from graph
COMMIT
```

**Atomic.** Duplicate `run_id` → reject (idempotent create only if same payload hash — otherwise conflict).

### 2. Claim / start Task

```
BEGIN
  SELECT workflow_run FOR UPDATE (or version check)
  domain: task.transition(RUNNING)
  UPDATE run + tasks + version
COMMIT
```

**Atomic.** Retry safe if task already `RUNNING` with same worker attempt id.

### 3. Complete Task

```
BEGIN
  load run aggregate
  domain: complete task + store result summary
  append execution log (optional same txn or follow-up)
  save run
COMMIT
```

**Atomic** for run state + result summary. Log append may share transaction or follow immediately after.

### 4. Fail Task

Same pattern as complete; terminal status `FAILED` or policy-driven workflow failure.

### 5. Finalize WorkflowRun

```
BEGIN
  load run
  domain: WorkflowCompletionPolicy → terminal workflow status
  save run
COMMIT
```

**Atomic.** No-op if already terminal with equivalent outcome.

### 6. Persist execution logs

```
BEGIN
  INSERT execution_log (event_id, run_id, task_id, payload, ts)
COMMIT
```

**Atomic per event.** Duplicate `event_id` ignored (idempotent append).

### 7. Persist artifacts

```
BEGIN
  INSERT artifact metadata
  LINK to project_id / run_id
COMMIT
-- blob upload may precede or follow; metadata txn after blob success
```

**Metadata transaction atomic;** blob storage eventual.

### 8. Recover interrupted workflow

```
load WorkflowRun at last committed version
TaskScheduler reads task statuses from aggregate
reclaim policy for stale RUNNING (PF-06)
```

**Not a single transaction** — recovery is read + scheduler decision. No automatic re-run without explicit policy.

---

## Domain / ORM separation

```
┌─────────────────────────────────────┐
│ Domain models (dataclasses, enums,  │
│ state machines) — no infra imports   │
└─────────────────┬───────────────────┘
                  │ used by
┌─────────────────▼───────────────────┐
│ Repository ports (application)       │
└─────────────────┬───────────────────┘
                  │ implemented by
┌─────────────────▼───────────────────┐
│ Adapters + mappers (infrastructure)  │
└─────────────────┬───────────────────┘
                  │ uses
┌─────────────────▼───────────────────┐
│ ORM records / SQL (infrastructure)   │
└─────────────────────────────────────┘

FastAPI schemas ── separate ──► map to/from domain at API boundary
```

**Do not** make domain models SQLAlchemy models. **Do not** expose ORM records to `WorkflowEngine`.

---

## Current implementation findings

| Area | Finding |
|------|---------|
| Repository abstractions | Single concrete `ProjectRepository` in infrastructure; no port interface |
| File persistence | `create_project` + `save_project` only; JSON via `asdict(project)` |
| Unimplemented | `load_project`, `list_projects`, `delete_project` → `NotImplementedError` |
| Dependency direction | `Agency`, `ApplicationConfig`, `ApplicationOverrides` import concrete `ProjectRepository` |
| Domain purity | Domain layer does not import infrastructure (verified) |
| ID generation | `uuid4()` for projects and tasks; workflow run id caller-supplied (default `"run-001"`) |
| Serialization risk | Populating `Project.runs` would break JSON round-trip (`TaskDependencyGraph`, enums) |
| Execution log | No domain type yet — introduce at persistence boundary in PF-02 |
| Artifacts | Domain stub; `WorkflowRun.artifacts` returns empty list |

---

## Docker-readiness constraints

| Constraint | Requirement |
|------------|-------------|
| Configuration | `DATABASE_URL`, credentials, paths via environment variables |
| Portability | No hard-coded DB host, credentials, or Windows-specific paths |
| Local + container | Same config contract in both environments |
| Testability | PostgreSQL replaceable with in-memory / test container adapters |
| Migrations | Explicit migrate step; no silent DDL on import or prod startup |
| Compose scope | Development orchestration only; not imported by domain or application |
| File paths | Use configurable roots; POSIX-friendly defaults inside containers |

---

## Implementation sequence

| Phase | Scope | Depends on |
|-------|-------|------------|
| **PF-01** | Persistence contract (this doc + ADR-009) | Phase B runtime |
| **PF-02** | Repository ports + in-memory adapters + contract tests | PF-01 |
| **PF-03** | PostgreSQL adapter + Alembic migrations + mappers | PF-02 |
| **PF-04** | Docker Compose dev environment | PF-03 |
| **PF-05** | FastAPI application boundary | PF-02 (ports), PF-03 (optional for full stack) |
| **PF-06** | Background workflow execution + reclaim policy | PF-03, PF-05 |

PF-05 may begin against in-memory adapters before PF-03 completes; full stack integration requires PF-03.

---

## Related documents

- [architecture/overview.md](overview.md)
- [architecture/domain-model.md](domain-model.md)
- [architecture/layers.md](layers.md)
- [docs/backlog.md](../docs/backlog.md)
