# AI Research OS

> AI-powered Operating System for Marketing Research Agencies

AI Research OS is a modular platform designed to automate and support the complete lifecycle of professional marketing research projects.

Unlike standalone AI agents, AI Research OS is built as a business operating system where AI, workflow automation, knowledge management and human expertise work together.

---

# Vision

Build the most practical AI Operating System for marketing research agencies.

The system is based on real agency workflows and is designed to improve speed, quality, consistency and knowledge reuse while keeping humans in control of business decisions.

---

# Mission

Transform every stage of a marketing research project into an intelligent, reusable and scalable workflow.

---

# Current Status

Architecture aligned with synchronous workflow runtime (Planner → WorkflowTemplate → WorkflowRun → Task execution).

## Implemented

- **Agency** application facade (`agency/agency.py`)
- **Project** domain model and repository
- **PlannerAgent** with structured output validation and executor catalog
- **ResearchPlan** → **WorkflowTemplate** mapping
- **WorkflowRun** factory and dependency graph
- **WorkflowEngine** synchronous runtime loop
- **TaskScheduler**, **TaskExecutor**, **ExecutorResolver**
- Registered agent executors: `planner`, `search`, `analysis`, `report`, `proposal`
- OpenAI LLM integration, file-based prompt templates (`application/prompts/`), knowledge files
- Architecture documentation under `architecture/` and ADRs under `docs/adr/`

## In Progress

- Additional business agents beyond the research workflow path
- Client Manager and early project lifecycle automation

---

# Architecture

The system is organized in four layers. See [architecture/overview.md](architecture/overview.md) for the full description.

```
Business Layer     Agency → Project → Knowledge / Artifacts
Workflow Layer     WorkflowTemplate → TaskDefinition → WorkflowRun → Task
Execution Layer    WorkflowEngine → TaskScheduler → TaskExecutor → ExecutorResolver → Executor
Infrastructure     LLM, Repositories, Storage, Registry
```

**Runtime path** (implemented):

```
main.py → Agency → Planner → ResearchPlan → WorkflowTemplate → WorkflowRun
       → WorkflowEngine → TaskScheduler → TaskExecutor → ExecutorResolver → Executor → Task Result → Workflow Completion
```

The **Project** is the central business aggregate. Executors run inside **WorkflowRun**; they do not replace project ownership.

Executor references use **`executor_id`** only. **ExecutorCatalog** constrains planner output; **Registry** (`AgentRegistry`, `ToolRegistry`, `HumanExecutorRegistry`, `APIExecutorRegistry`) resolves executors at runtime. See [ADR-008](docs/adr/ADR-008-Executor-Catalog-Contract.md).

---

# Project Structure

```
AI_RESEARCH_OS/
├── agency/              Application facade
├── agents/              Agent executors (planner, search, analysis, …)
├── application/         Workflow engine, planner service, composition root, config
├── architecture/        Architecture documentation
├── domain/              Business and runtime domain models
├── infrastructure/      LLM, documents, persistence adapters
├── loaders/             Agent and executor loading
├── registry/            Runtime executor registries (agent, tool, human, api)
├── runtime/             Workflow context helpers
├── services/            Legacy sandbox helper (project_brief_builder)
├── scripts/             Development utilities (sandbox)
├── knowledge/           Static expertise files
├── prompts/             LLM prompt templates
├── docs/                Project documentation and ADRs
├── tests/
├── main.py
├── run_tests.py
└── requirements.txt
```

| Directory | Purpose |
|-----------|---------|
| `agency/` | Application entry facade |
| `agents/` | Concrete agent executors |
| `application/` | Orchestration, planner, workflow runtime |
| `domain/` | Entities, value objects, state machines |
| `infrastructure/` | External system adapters |
| `registry/` | Runtime executor lookup (`AgentRegistry`, `ToolRegistry`, `HumanExecutorRegistry`, `APIExecutorRegistry`) |
| `architecture/` | Layer and domain model docs |
| `docs/` | ADRs, development rules |

---

# Technology Stack

**Current**

- Python
- OpenAI API
- Git / GitHub
- Markdown

**Planned**

- FastAPI, PostgreSQL, Docker (not part of current runtime)

---

# Development Principles

- Business before AI
- Architecture before implementation
- Definition vs runtime separation (`WorkflowTemplate` / `TaskDefinition` vs `WorkflowRun` / `Task`)
- **ExecutorResolver** is the single resolution point for executors
- Domain-driven design
- ADRs for significant decisions (`docs/adr/`)

---

# Documentation

| Document | Description |
|----------|-------------|
| [architecture/overview.md](architecture/overview.md) | Layers, runtime flow, executor contract |
| [architecture/layers.md](architecture/layers.md) | Layer boundaries |
| [architecture/domain-model.md](architecture/domain-model.md) | TaskDefinition vs Task, WorkflowTemplate vs WorkflowRun |
| [docs/architecture.md](docs/architecture.md) | Documentation index |
| [docs/adr/README.md](docs/adr/README.md) | ADR index |

---

# License

Source available. [All Rights Reserved](LICENSE).

Viewing this repository does not grant permission to use, copy, modify,
distribute, or create derivative works except with written permission
from the copyright holder.

---

# Author

Eduard Zolotukhin

AI Research OS © 2026
