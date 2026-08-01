# AI Research OS — Architecture Documentation

This page indexes architecture documentation that matches the **current production code**. For narrative detail, start with [architecture/overview.md](../architecture/overview.md).

---

# Layer Model

```mermaid
flowchart TB
    BL[Business Layer] --> WL[Workflow Layer]
    WL --> EL[Execution Layer]
    EL --> IL[Infrastructure]
```

| Layer | Components |
|-------|------------|
| Business | `Agency`, `Project`, `ProjectBrief`, knowledge files |
| Workflow | `WorkflowTemplate`, `TaskDefinition`, `WorkflowRun`, `Task` |
| Execution | `WorkflowEngine`, `TaskScheduler`, `TaskExecutor`, `ExecutorResolver` |
| Infrastructure | `OpenAIClient`, `ProjectRepository`, agent registry |

---

# Runtime Entry Point

| Step | Component | Module |
|------|-----------|--------|
| 1 | Application bootstrap | `main.py` → `application/composition_root.py` |
| 2 | Research start | `agency/agency.py` |
| 3 | Planning | `agents/planner/` + `application/planner/` |
| 4 | Template mapping | `ResearchPlanWorkflowTemplateMapper` |
| 5 | Run creation | `WorkflowRunFactory` |
| 6 | Execution loop | `application/workflow_engine.py` |
| 7 | Scheduling | `application/task_scheduler.py` |
| 8 | Task execution | `application/task_executor.py` |
| 9 | Executor resolution | `application/executor_resolver.py` |

---

# Task and Workflow Models

### Definition (immutable)

- **WorkflowTemplate** — workflow plan attached to a project after planning
- **TaskDefinition** — single task blueprint with `executor_id` and `depends_on`

### Runtime (mutable)

- **WorkflowRun** — instance of a template; owns tasks and dependency graph
- **Task** — runtime instance with status; scheduled and executed by the engine

---

# Executor Contract

Planner and runtime share **`executor_id`**.

- **ExecutorCatalog** — allowed IDs injected into planner prompts
- **PlannerPayloadContract** — semantic validation before run creation
- **ExecutorResolver** — sole runtime mapping from `executor_id` to executor instance

See [ADR-008: Executor Catalog Contract](adr/ADR-008-Executor-Catalog-Contract.md). Other documents should reference ADR-008 rather than duplicating the full contract.

---

# Architecture Documents

| Document | Content |
|----------|---------|
| [architecture/overview.md](../architecture/overview.md) | Layers, runtime flow, principles |
| [architecture/layers.md](../architecture/layers.md) | Layer responsibilities and forbidden dependencies |
| [architecture/domain-model.md](../architecture/domain-model.md) | Entities, TaskDefinition vs Task |
| [architecture/product-foundation-persistence.md](../architecture/product-foundation-persistence.md) | PF-01 contract; PF-02 ports; PF-02.5 services; PF-03 PostgreSQL |
| [ARCHITECTURE.md](../ARCHITECTURE.md) | Short entry point |
| [adr/README.md](adr/README.md) | ADR index |
| [adr/ADR-009-Persistence-Boundary-and-Repository-Strategy.md](adr/ADR-009-Persistence-Boundary-and-Repository-Strategy.md) | Persistence ADR |

---

# Product Foundation status

**Completed (PF-01–PF-08):**

- **PF-01–PF-03** — Persistence boundary, ports, services, PostgreSQL ([ADR-009](adr/ADR-009-Persistence-Boundary-and-Repository-Strategy.md))
- **PF-04** — Durable checkpoints and resume ([ADR-010](adr/ADR-010-Durable-Workflow-Checkpoint-and-Recovery-Policy.md))
- **PF-05** — FastAPI HTTP boundary ([ADR-011](adr/ADR-011-HTTP-API-Boundary-and-Synchronous-Execution-Policy.md))
- **PF-06** — Background worker ([ADR-012](adr/ADR-012-Background-Execution-Claiming-Lease-and-Recovery.md))
- **PF-07** — External orchestration / idempotency ([ADR-013](adr/ADR-013-External-Orchestration-and-Idempotent-Submission.md))
- **PF-08** — Authentication and access boundary ([ADR-014](adr/ADR-014-Authentication-and-Access-Boundary.md))

**Production path (HTTP + worker):**

```mermaid
flowchart TD
    Client[External Client / n8n] --> API[FastAPI]
    API --> Auth[Authentication / Authorization]
    Auth --> App[Application Services]
    App --> Submit[Durable Research Submission]
    Submit --> PG[(PostgreSQL)]
    Worker[Background Worker] --> PG
    Worker --> Engine[WorkflowEngine]
    Engine --> Exec[Executors]
    Exec --> Out[Checkpoints / Results / Artifacts]
```

**Still not product-complete:**

- Desk research vertical end-to-end
- Full knowledge management, artifact blob lifecycle, search/source provenance
- OAuth/OIDC, UI, multi-tenant SaaS
- Production observability and backup automation
