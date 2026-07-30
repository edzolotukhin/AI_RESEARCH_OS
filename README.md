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

## Installation

From the repository root:

```bash
git clone https://github.com/edzolotukhin/AI_RESEARCH_OS.git
cd AI_RESEARCH_OS
python -m venv .venv
```

Activate the virtual environment:

```bash
# Linux / macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

Install runtime dependencies:

```bash
pip install -r requirements.txt
```

---

## Python Requirements

Supported range (see `pyproject.toml`):

**Python >=3.11,<3.15**

The runtime and test suite are verified within this range. Use a virtual environment; do not rely on system-wide packages.

---

## Environment

For live planner execution (`main.py`), copy `.env.example` to `.env` and set `OPENAI_API_KEY`.
The OpenAI SDK reads it after `python-dotenv` loads the file.

| Path | API key required? |
|------|-------------------|
| `python examples/deterministic_research_demo.py` | No |
| `python run_tests.py` | No |
| `python main.py` | Yes |

No other environment variables are required by the current runtime.

---

## Offline Demo

Run the deterministic workflow demo from the repository root:

```bash
python examples/deterministic_research_demo.py
```

The demo exercises the current runtime without network access:

- **WorkflowTemplate** — immutable workflow definition
- **WorkflowRun** — materialized runtime instance
- **Dependency graph** — linear task dependencies
- **TaskScheduler** — dependency-aware ready-task selection
- **ExecutorResolver** — resolves demo executors from a local registry
- **WorkflowEngine** — synchronous execution loop through workflow completion

The demo uses in-memory storage only. It does not call OpenAI, does not require `OPENAI_API_KEY`, and does not write files under `agency/projects/`.

---

## Running Tests

```bash
python run_tests.py
```

The suite currently runs **289 automated tests**. It validates runtime orchestration, planner contracts, dependency graphs, executor resolution, structured-output retry, agency integration, and the offline demo subprocess path. Coverage metrics are not published.

---

## Repository Structure

```
AI_RESEARCH_OS/
├── agency/           Application facade
├── agents/           Agent executors
├── application/      Workflow engine, planner, composition root
├── architecture/     Architecture documentation
├── domain/           Domain and runtime models
├── docs/             ADRs, backlog, project docs
├── examples/         Offline demos
├── infrastructure/   LLM client, repositories
├── registry/         Executor registries
├── tests/            Automated tests
├── main.py           Live demo entry (requires API key)
└── run_tests.py      Test entrypoint
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Architecture entry point |
| [architecture/overview.md](architecture/overview.md) | Layers, runtime flow, executor contract |
| [docs/adr/README.md](docs/adr/README.md) | Architecture decision records |
| [ROADMAP.md](ROADMAP.md) | Current state and planned work |
| [CHANGELOG.md](CHANGELOG.md) | Notable changes |
| [docs/backlog.md](docs/backlog.md) | Internal task backlog |
| [LICENSE](LICENSE) | All Rights Reserved |

---

## Project Status

| Area | Status |
|------|--------|
| **Runtime core** | Complete — Phase B hardening done |
| **Product Foundation** | Next planned work — not integrated in production runtime |
| **Production platform** | Future work — FastAPI, PostgreSQL, Docker, deployment, multi-user |

See [ROADMAP.md](ROADMAP.md) for detail. The project is not production-ready.

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

Further reading: [architecture/layers.md](architecture/layers.md), [architecture/domain-model.md](architecture/domain-model.md), [docs/architecture.md](docs/architecture.md).

---

# Development Principles

- Business before AI
- Architecture before implementation
- Definition vs runtime separation (`WorkflowTemplate` / `TaskDefinition` vs `WorkflowRun` / `Task`)
- **ExecutorResolver** is the single resolution point for executors
- Domain-driven design
- ADRs for significant decisions (`docs/adr/`)

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
