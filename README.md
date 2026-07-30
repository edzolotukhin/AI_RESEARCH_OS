# AI_RESEARCH_OS

Workflow runtime for marketing research agencies.

AI Research OS models research work as dependency-aware workflows: immutable
definitions (`WorkflowTemplate`, `TaskDefinition`) are materialized into runtime
executions (`WorkflowRun`, `Task`), scheduled and executed through a synchronous
orchestration loop. AI agents are executors inside this runtime — not the
architecture itself.

---

## Current Status

| | |
|---|---|
| **Phase** | Phase B runtime hardening complete |
| **Tests** | 289 automated tests |
| **Demo** | Deterministic offline demo (`examples/deterministic_research_demo.py`) |
| **Architecture** | Definition / runtime separation; dependency-aware workflow execution |
| **License** | Source available · [All Rights Reserved](LICENSE) |

Not production-ready. Early-stage runtime core with a public repository.

---

## What Works Today

- **Agency** facade and composition root (`create_application()`)
- **Planner** with structured-output retry and executor catalog (ADR-008)
- **ResearchPlan** → **WorkflowTemplate** → **WorkflowRun** pipeline
- **WorkflowEngine**, **TaskScheduler**, **TaskExecutor**, **ExecutorResolver**
- Dependency graph validation at planner contract and domain layers
- Registered agent executors: `planner`, `search`, `analysis`, `report`, `proposal`
- OpenAI integration for live planning path (`main.py`, requires API key)
- File-based **ProjectRepository** and architecture documentation

---

## What Does Not Exist Yet

- Client Manager wired to production runtime
- Product Foundation workflows (brief, design, artifacts lifecycle)
- FastAPI service layer
- PostgreSQL storage
- Docker deployment
- Production deployment packaging
- Multi-user platform capabilities
- CI pipeline and release versioning

---

## Links

| | |
|---|---|
| [Architecture](architecture/overview.md) | Layers, runtime flow, domain model |
| [Roadmap](ROADMAP.md) | Current state and planned work |
| [Changelog](CHANGELOG.md) | Notable changes |
| [License](LICENSE) | All Rights Reserved |

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
