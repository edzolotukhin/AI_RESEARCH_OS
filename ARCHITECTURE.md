# AI Research OS — Architecture

> **Canonical documentation** lives in the [`architecture/`](architecture/) directory. This file is a short entry point; prefer the linked documents for detail.

---

# Overview

AI Research OS is a business operating system for marketing research agencies. The **Project** is the central business aggregate. Workflow **definitions** are immutable; **runtime** objects track execution state.

---

# Layers

| Layer | Key components |
|-------|----------------|
| **Business** | `Agency`, `Project`, knowledge artifacts |
| **Workflow** | `WorkflowTemplate`, `TaskDefinition`, `WorkflowRun`, `Task` |
| **Execution** | `WorkflowEngine`, `TaskScheduler`, `TaskExecutor`, `ExecutorResolver` |
| **Infrastructure** | LLM client, repositories, executor registry |

See [architecture/layers.md](architecture/layers.md).

---

# Runtime Flow

```
main.py
  → create_application() / Agency
  → PlannerAgent (LLM + PlannerPayloadContract + ExecutorCatalog)
  → ResearchPlan → WorkflowTemplate
  → WorkflowRunFactory → WorkflowRun + Task instances
  → WorkflowEngine.run()
       → TaskScheduler.schedule() / find_ready_task()
       → TaskExecutor.execute()
       → ExecutorResolver.resolve(task)   // by executor_id
       → registered Executor
       → task state update
  → WorkflowCompletionPolicy → terminal WorkflowRun status
```

See [architecture/overview.md](architecture/overview.md) for diagrams.

---

# Workflow Model

| Type | Role |
|------|------|
| **WorkflowTemplate** | Immutable workflow plan |
| **TaskDefinition** | Immutable task blueprint inside a template |
| **WorkflowRun** | Runtime workflow instance |
| **Task** | Runtime task instance with status and lifecycle |

**TaskDefinition** is the template; **Task** is what the scheduler and executor operate on.

See [architecture/domain-model.md](architecture/domain-model.md).

---

# Executor Contract

- Planner output uses **`executor_id`** only (registered executor IDs).
- **ExecutorCatalog** constrains planner prompts; **PlannerPayloadContract** validates output.
- **ExecutorResolver** is the only runtime resolution point.

Full decision record: [ADR-008: Executor Catalog Contract](docs/adr/ADR-008-Executor-Catalog-Contract.md).

---

# Dependency Direction

```
Business (Agency, Project)
      ↓
Workflow (Template, Run, Task)
      ↓
Execution (Engine, Scheduler, Executor, Resolver)
      ↓
Infrastructure (LLM, Registry, Repository)
```

Domain models do not depend on LLM or executor implementations.

---

# Design Principles

1. **Project** owns business context for a research initiative.
2. **WorkflowEngine** owns `WorkflowRun.status`.
3. **TaskScheduler** schedules; **TaskExecutor** executes — never combined.
4. One ready task per synchronous loop iteration.
5. Major decisions are recorded as ADRs under `docs/adr/`.

---

# Related Documents

- [architecture/overview.md](architecture/overview.md)
- [architecture/layers.md](architecture/layers.md)
- [architecture/domain-model.md](architecture/domain-model.md)
- [docs/adr/README.md](docs/adr/README.md)

---

# Evolution

Extend existing layers before introducing new abstractions. Supersede ADRs with new records rather than rewriting accepted decisions.
