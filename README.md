# AI_RESEARCH_OS

[![CI](https://github.com/edzolotukhin/AI_RESEARCH_OS/actions/workflows/ci.yml/badge.svg)](https://github.com/edzolotukhin/AI_RESEARCH_OS/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)

Workflow runtime for marketing research agencies.

AI Research OS models research work as dependency-aware workflows: immutable
definitions (`WorkflowTemplate`, `TaskDefinition`) are materialized into runtime
executions (`WorkflowRun`, `Task`), scheduled and executed through a background
worker with durable checkpointing (PF-06). AI agents are executors inside this runtime — not the
architecture itself.

---

## Current Status

| | |
|---|---|
| **Phase** | Phase B runtime hardening complete |
| **Tests** | 464 tests discovered (419 executed by default; 45 PostgreSQL-gated skipped unless configured) |
| **Demo** | Deterministic offline demo (`examples/deterministic_research_demo.py`) |
| **Architecture** | Definition / runtime separation; dependency-aware workflow execution |
| **License** | Source available · [All Rights Reserved](LICENSE) |

Not production-ready. Early-stage runtime core with a public repository.

---

## What Works Today

- **Agency** facade and composition root (`create_application()` / `create_application_container()`)
- **Planner** with structured-output retry and executor catalog (ADR-008)
- **ResearchPlan** → **WorkflowTemplate** → **WorkflowRun** pipeline
- **WorkflowEngine**, **TaskScheduler**, **TaskExecutor**, **ExecutorResolver**
- Dependency graph validation at planner contract and domain layers
- Registered agent executors: `planner`, `search`, `analysis`, `report`, `proposal`
- OpenAI integration for live planning path (`main.py`, requires API key)
- Repository ports, application persistence services, and selectable backends (`file`, `memory`, `postgresql`)
- Durable workflow checkpointing for `memory` and `postgresql` backends (PF-04)
- PostgreSQL persistence adapter (SQLAlchemy 2.x, Alembic, Docker Compose for local PostgreSQL and API)
- **FastAPI HTTP API** (`api/`) with OpenAPI docs, health/readiness, projects, research, workflow runs, logs, artifacts (PF-05)
- **Background worker** (`worker/`) with PostgreSQL claim/lease, heartbeat, and crash recovery (PF-06)
- File-based **ProjectRepository** (transitional) and architecture documentation

---

## What Does Not Exist Yet

- Client Manager wired to production runtime
- Product Foundation workflows (brief, design, artifacts lifecycle)
- Authentication, authorization, and API keys
- Production deployment packaging
- Multi-user platform capabilities
- Release versioning

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

### Persistence

| Variable | Default | Purpose |
|----------|---------|---------|
| `PERSISTENCE_BACKEND` | `file` | `file`, `memory`, or `postgresql` |
| `DATABASE_URL` | — | Required when `PERSISTENCE_BACKEND=postgresql` |

Example PostgreSQL URL (see `.env.example`):

```text
postgresql+psycopg://ai_research_os:ai_research_os_dev@localhost:5432/ai_research_os
```

Local PostgreSQL (Docker Compose):

```bash
docker compose up -d postgres
set DATABASE_URL=postgresql+psycopg://ai_research_os:ai_research_os_dev@localhost:5432/ai_research_os
alembic upgrade head
set PERSISTENCE_BACKEND=postgresql
python run_tests.py
```

PostgreSQL verification (optional; **54** PostgreSQL-gated tests — 33 repository contract + 14 integration + 5 HTTP API integration + related skips; require a **test** database name and explicit opt-in). Run sequentially against the shared `ai_research_os_test` database; parallel local PostgreSQL test runs are not supported yet.

```powershell
# Windows
.\scripts\test_unit.ps1
.\scripts\test_postgres.ps1
.\scripts\test_all.ps1
```

The same checks run in [GitHub Actions CI](#continuous-integration) on every push and pull request.

Manual commands (equivalent to `test_postgres.ps1`):

```bash
# Linux / macOS / CI-style
export POSTGRESQL_INTEGRATION_TESTS=1
export DATABASE_URL_TEST="postgresql+psycopg://ai_research_os:ai_research_os_dev@localhost:5432/ai_research_os_test"
export DATABASE_URL="$DATABASE_URL_TEST"
python -m alembic upgrade head
python -m unittest tests.application.ports.test_postgresql_repository_contracts -v
python -m unittest discover -s tests/integration/postgresql -p "test_*.py" -v
```

```powershell
# Windows (PowerShell)
$env:POSTGRESQL_INTEGRATION_TESTS="1"
$env:DATABASE_URL_TEST="postgresql+psycopg://ai_research_os:ai_research_os_dev@localhost:5432/ai_research_os_test"
python -m unittest discover -s tests/integration/postgresql -p "test_*.py" -v
python -m unittest tests.application.ports.test_postgresql_repository_contracts -v
```

No other environment variables are required by the default runtime.

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
- **WorkflowEngine** — execution loop through workflow completion (invoked by worker for durable backends)

The demo uses in-memory storage only. It does not call OpenAI, does not require `OPENAI_API_KEY`, and does not write files under `agency/projects/`.

---

## Running Tests

```bash
python run_tests.py
```

The suite discovers **464** tests by default; **419** run and pass (**45** PostgreSQL-gated tests skipped unless `POSTGRESQL_INTEGRATION_TESTS=1` and `DATABASE_URL_TEST` point at a test database). With PostgreSQL configured, **473** tests run and pass (0 skipped).

### HTTP API tests

```bash
python -m unittest discover -s tests/api -p "test_*.py" -v
```

With PostgreSQL configured, also run `tests/integration/api/` (included in CI).

### Local API (Docker Compose)

Development startup is explicit — migrations are **not** run automatically on API boot:

```bash
docker compose up -d postgres
docker compose run --rm api alembic upgrade head
docker compose up -d api worker
```

For offline smoke without a live LLM, opt in explicitly:

```bash
docker compose -f docker-compose.yml -f docker-compose.smoke.yml up -d postgres api worker
```

Normal Compose does **not** enable `DETERMINISTIC_PLANNER`. Production planning requires `OPENAI_API_KEY`.

- `GET /health` — liveness only (no database required)
- `GET /ready` — readiness (`503` when PostgreSQL is unavailable, schema is missing, or Alembic revision is not at head)
- `POST /projects/{project_id}/research` — **202 Accepted** when background execution is configured (`external` on PostgreSQL, or `embedded` on memory in tests)
- **Memory without `embedded`**, **file**, and other unsupported topologies return **409** for research/resume
- **PostgreSQL + external worker** is the supported multi-process deployment; **memory** is embedded/test-only

### External orchestration (n8n)

External clients integrate via HTTP only — no direct PostgreSQL or Python imports.

- `Idempotency-Key` header on `POST /research` for durable deduplication (PostgreSQL)
- `correlation_id`, `source` in request body; optional `X-Correlation-ID` header
- Poll `GET /workflow-runs/{id}` until `is_terminal`; then `GET /results` and `/artifacts`
- Optional n8n: `docker compose -f docker-compose.yml -f docker-compose.n8n.yml up -d`
- Examples: `examples/n8n/` — see ADR-013

**Local dev is unauthenticated.** Do not expose to public internet.

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/docs
```

---

## Continuous Integration

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and pull request:

| Step | Command / check |
|------|-----------------|
| Dependencies | Python **3.11**, pip cache, `pip install -r requirements.txt` |
| Repository hygiene | `git diff --check` on the push/PR commit range (`before..sha` or `base..head`) |
| PostgreSQL | Service container (PostgreSQL 16), health-checked |
| Test database | `ai_research_os_test` (created if missing) |
| Migrations | `alembic upgrade head`, `alembic current` |
| Unit tests | `python run_tests.py` (419 executed, 45 PostgreSQL-gated skipped) |
| Contract tests | 33 PostgreSQL repository contract tests |
| Integration tests | 14 PostgreSQL integration tests (including durable runtime) |
| API tests | 23 HTTP API tests (`tests/api/`) |
| PostgreSQL API tests | 5 HTTP integration tests (`tests/integration/api/`) |
| Docker | `docker build .` smoke check |

CI fails on any test failure or whitespace/conflict-marker issues. Database credentials are dev-only values aligned with `docker-compose.yml`; they are not printed in logs.

Local full check before a PR: `.\scripts\test_all.ps1` (unit + PostgreSQL + API + OpenAPI smoke + `git diff --check`).

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

# Runtime Architecture

This section explains how the workflow runtime is designed and why. For layer diagrams and ADRs, see [architecture/overview.md](architecture/overview.md).

---

## Core Concepts

**WorkflowTemplate** — Immutable workflow definition attached to a project after planning. Contains `TaskDefinition` blueprints and dependency structure.

**TaskDefinition** — Blueprint for a single unit of work: name, `executor_id`, `executor_type`, and `depends_on` references to other definition IDs.

**WorkflowRun** — Mutable runtime instance of a template. Owns live `Task` objects, execution status, and a validated dependency graph.

**Task** — Runtime counterpart of a `TaskDefinition`. Carries state (`created`, `ready`, `running`, `completed`, `failed`, …) and resolves dependencies at execution time.

**Executor** — Infrastructure contract (`BaseExecutor`) that receives a `WorkflowContext`, performs one unit of work, and returns the updated context. Agents, tools, human steps, and API calls are all accessed through this interface.

**WorkflowEngine** — Canonical owner of the execution loop. Schedules ready tasks, invokes `TaskExecutor`, applies completion policy, and finalizes workflow status.

---

## Definition vs Runtime

| Definition (immutable) | Runtime (mutable) |
|------------------------|-------------------|
| `WorkflowTemplate` | `WorkflowRun` |
| `TaskDefinition` | `Task` |

Definitions describe *what* should happen. Runtime objects track *what is happening*.

Separating the two yields:

- **Determinism** — the same template materializes the same structural graph every time
- **Reproducibility** — plans can be stored, compared, and re-run without mutating the source definition
- **Immutability** — templates are not altered when a single run fails or retries
- **Execution isolation** — state transitions and failures affect the run, not the definition

Materialization path: `WorkflowTemplate` → `WorkflowRunFactory` → `WorkflowRun` + `TaskDependencyGraph`.

---

## Workflow Lifecycle

```mermaid
flowchart TD
    WT[WorkflowTemplate] --> WR[WorkflowRun]
    WR --> TC[Task creation from TaskDefinition]
    TC --> DV[Dependency graph validation]
    DV --> TS[TaskScheduler]
    TS --> ER[ExecutorResolver]
    ER --> EX[Executor.run]
    EX --> TS
    TS --> WC[Workflow completion policy]
```

Execution order in code:

1. A **WorkflowTemplate** is produced (planner path or programmatic builder).
2. **WorkflowRunFactory** creates a **WorkflowRun** and runtime **Task** instances.
3. The dependency graph is validated (unknown deps, cycles, duplicate IDs rejected).
4. **WorkflowEngine** enters a loop: **TaskScheduler** selects a ready task.
5. **TaskExecutor** resolves an **Executor** via **ExecutorResolver** and runs it.
6. When no ready tasks remain and all tasks are terminal, **WorkflowCompletionPolicy** sets the final workflow status.

The offline demo runs this path without a planner or LLM. The live path adds `PlannerAgent` → `ResearchPlan` → template mapping before step 1.

---

## Executor Model

Every task declares an `executor_id` and an explicit `ExecutorType`:

| Type | Registry | Role |
|------|----------|------|
| **Agent** | `AgentRegistry` | LLM-backed or scripted agents |
| **Tool** | `ToolRegistry` | Deterministic tool adapters |
| **Human** | `HumanExecutorRegistry` | Human-in-the-loop steps |
| **API** | `APIExecutorRegistry` | External API integrations |

**ExecutorResolver** is the single lookup point. It maps `(executor_type, executor_id)` to a `BaseExecutor` implementation.

The **WorkflowEngine** and **TaskScheduler** never import concrete agents. New executors register in the appropriate registry without changing the engine loop. The planner-side **ExecutorCatalog** (ADR-008) constrains which agent IDs may appear in generated plans.

---

## Architectural Principles

- Definition/runtime separation (`WorkflowTemplate` / `TaskDefinition` vs `WorkflowRun` / `Task`)
- Dependency-aware scheduling via an explicit task dependency graph
- Deterministic scheduling order for a given graph and task states
- Pluggable executors resolved through registries, not hard-coded imports
- Clear layer boundaries: business → workflow → execution → infrastructure
- Minimal runtime coupling — engine depends on contracts, not on agent implementations
- Defense in depth — graph validation at planner contract, factory, and scheduler layers

---

## Current Limitations

- Single-process, synchronous runtime loop
- File-based project persistence only; no shared database
- No REST API or service layer
- No UI
- No multi-user or multi-tenant support
- No production deployment packaging (Docker, CI, releases)
- Live planner path requires an external LLM API key

These limits are intentional at the current maturity stage. See [ROADMAP.md](ROADMAP.md).

---

## Future Direction

The runtime is domain-agnostic at its core: templates, dependency graphs, and executor resolution do not assume a specific industry. Marketing research is the first domain implemented — planner output, agent executors, and project models target agency workflows today. Additional domains could reuse the same engine, scheduler, and resolver model with different templates and executors. Product Foundation work (brief, design, artifacts) and platform layers (API, persistence, deployment) are planned next; they are not part of the current runtime core.

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
