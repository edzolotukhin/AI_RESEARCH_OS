# AI Research OS — Roadmap

## Current State

The synchronous orchestration runtime is **implemented, tested, and demonstrable**. Phase B runtime hardening is **complete**. A deterministic offline workflow demo is available. The repository has **289 automated tests**. The project is **not production-ready** — it is an early-stage research workflow runtime, not a full agency platform.

| Dimension | Status |
|-----------|--------|
| Runtime core | Implemented and tested |
| Planner + structured output | Integrated |
| Offline demo | Available (`examples/deterministic_research_demo.py`) |
| Live LLM demo path | Available (`main.py`, requires API key) |
| Product Foundation | In progress — PF-02.5 application persistence services ([ADR-009](docs/adr/ADR-009-Persistence-Boundary-and-Repository-Strategy.md)) |
| Platform / infra (API, DB, Docker) | Planned only (PF-03–PF-06) |

---

## Completed Foundations

### Phase A — Stabilization

- Agency application facade and composition root
- Planner → ResearchPlan → WorkflowTemplate → WorkflowRun pipeline
- ADR-008 Executor Catalog Contract
- Planner constrained to registered executor IDs
- WorkflowEngine synchronous runtime loop
- TaskScheduler, TaskExecutor, ExecutorResolver
- WorkflowCompletionPolicy
- Structured output retry and planner payload contract
- Architecture documentation sync
- Phase B Wave 1 cleanup: dead infrastructure, legacy services, dead registries

### Phase B — Runtime Hardening

- **AUD-016:** terminal `WorkflowRun` state when executor fails during execution
- **AUD-017:** Agency initialization contract — lazy init in `start_research()`; explicit `initialize()` still supported
- **AUD-018:** planner dependency graph validation inside structured-output retry boundary
- Defense-in-depth graph validation retained at factory/domain layer

### GF-00 — Repository Readiness (partial)

- **PR-A:** repository hygiene — untracked runtime project artifacts, hardened `.gitignore`
- **PR-B:** packaging and environment contract — `requirements.txt`, `pyproject.toml`, `.env.example`
- **PR-C:** deterministic offline research workflow demo; legacy misleading examples removed

---

## Current Work

**GitHub Face Sprint (GF-00, in progress)**

- Public documentation (README v2, architecture visuals)
- CI and trust signals
- License posture decision
- Contribution and security documentation

**Remaining runtime hardening (backlog, not blocking public docs)**

- Catalog/registry desynchronization test coverage
- Full runtime E2E test (all registered executors)
- Planner runtime-executor semantics (`executor_id=planner` re-planning behavior)
- Migrate `scripts/sandbox.py` off legacy `services/project_brief_builder.py`

---

## Next: Product Foundation

**PF-01 (complete):** persistence boundary and repository strategy documented — see [ADR-009](docs/adr/ADR-009-Persistence-Boundary-and-Repository-Strategy.md) and [architecture/product-foundation-persistence.md](architecture/product-foundation-persistence.md).

**PF-02 (complete):** repository ports, file/in-memory adapters, and contract tests.

**PF-02.5 (complete):** application persistence services (`ProjectService`, `WorkflowService`, etc.). Agency delegates project persistence to `ProjectService`. PostgreSQL, Docker, FastAPI, and background execution remain **planned only**.

Product-facing workflow expansion — **not started** in production runtime:

- Project Brief integration into the main research path
- Research Design automation
- Knowledge flow beyond static files
- Artifacts lifecycle
- Product-facing workflow templates
- Client Manager wired to `create_application()`

Existing agent stubs (Client Manager, Research Designer, etc.) are **not integrated** into the production composition root.

---

## Later

Platform and operational capabilities — **explicitly deferred**:

- Persistence hardening beyond file-based `ProjectRepository`
- Workflow resume / cancel semantics
- Observability (logging, metrics, tracing)
- FastAPI service layer
- PostgreSQL storage
- Docker deployment
- Multi-user / multi-agency capabilities
- CRM, client portal, integrations

---

## Explicitly Not Committed

This roadmap does **not** promise:

- Release dates or version timelines
- Production SLA or uptime guarantees
- Autonomous agency replacement of human researchers
- PyPI package publication timeline
- Full “operating system” platform completeness

---

## Maturity Labels

Use these distinctions when reading project status:

| Label | Meaning |
|-------|---------|
| **Implemented** | Code exists in the repository |
| **Tested** | Covered by automated tests |
| **Demonstrable** | Runnable example or demo path exists |
| **Integrated** | Wired into `create_application()` / main runtime path |
| **Production-ready** | Suitable for external deployment without further hardening |

Phase B runtime hardening is **complete** at the runtime-core level. The overall product is **not production-ready**.

---

## Definition of Done (phase gate)

A phase is complete when functionality works, architecture stays consistent, scoped documentation is updated, and the system is ready for the next phase.
