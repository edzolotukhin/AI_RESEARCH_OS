# AI Research OS — Roadmap

## Current State (factual)

AI Research OS is a **workflow runtime platform** for marketing research agencies with an **advanced production foundation** and an **incomplete research product vertical**.

| Dimension | Status |
|-----------|--------|
| Platform foundation (PF-01–PF-08) | **Implemented and merged** — persistence, HTTP API, worker, orchestration, auth |
| Automated tests | **528** discovered; **467** run by default without PostgreSQL; **500+** with full CI/local PostgreSQL suites |
| Research product vertical | **Not validated end-to-end** — agents exist as stubs; desk research flow incomplete |
| Production deployment | **Not production-ready** — Docker Compose is dev-oriented; no SLA, observability stack, or backup automation |

**Readiness framing (not percentages):**

- **Infrastructure / platform foundation:** advanced
- **Research product vertical:** incomplete
- **End-to-end research capability:** not yet validated

---

## Completed Foundation

Each stage below is merged into `main` with ADR coverage and automated tests unless noted.

### PF-01 — Persistence boundary

- **Goal:** Define repository ports, aggregate ownership, and layer boundaries.
- **Outcome:** [ADR-009](docs/adr/ADR-009-Persistence-Boundary-and-Repository-Strategy.md), [architecture/product-foundation-persistence.md](architecture/product-foundation-persistence.md).
- **Limitation:** `Project.runs` in-memory field vs persisted query model still unresolved.

### PF-02 / PF-02.5 — Ports and application services

- **Goal:** Repository ports, in-memory/file adapters, contract tests, application persistence services.
- **Outcome:** `application/ports/`, `application/services/`, Agency decoupled from concrete repositories.

### PF-03 — PostgreSQL persistence

- **Goal:** Durable relational storage for projects, runs, templates, artifacts, knowledge, logs.
- **Outcome:** SQLAlchemy 2.x adapters, Alembic migrations (`001`–`005`), Docker Compose PostgreSQL service.
- **Limitation:** File backend remains for transitional local use; production path is PostgreSQL.

### PF-04 — Durable workflow execution

- **Goal:** Checkpoint workflow state; support resume after partial execution.
- **Outcome:** [ADR-010](docs/adr/ADR-010-Durable-Workflow-Checkpoint-and-Recovery-Policy.md); durable run persistence on memory and PostgreSQL backends.
- **Limitation:** Resume semantics are worker/API-gated; not all backends support durable submission.

### PF-05 — FastAPI application boundary

- **Goal:** HTTP ingress for projects, research submission, runs, results, logs, artifacts.
- **Outcome:** [ADR-011](docs/adr/ADR-011-HTTP-API-Boundary-and-Synchronous-Execution-Policy.md); OpenAPI; health/readiness; Docker `api` service.
- **Limitation:** ADR-011 synchronous policy superseded for research by PF-06 (202 Accepted + background worker).

### PF-06 — Background worker

- **Goal:** Multi-process durable execution with claim, lease, heartbeat, stale recovery.
- **Outcome:** [ADR-012](docs/adr/ADR-012-Background-Execution-Claiming-Lease-and-Recovery.md); `worker/` package; Docker `worker` service; crash recovery tests.
- **Limitation:** Worker does not use HTTP auth; memory backend is test-only for embedded execution.

### PF-07 — External orchestration / n8n

- **Goal:** Machine clients integrate via HTTP; idempotent research submission.
- **Outcome:** [ADR-013](docs/adr/ADR-013-External-Orchestration-and-Idempotent-Submission.md); `Idempotency-Key`; correlation metadata; `examples/n8n/`; optional Compose overlay.
- **Limitation:** Example workflows are reference integrations, not a managed automation platform.

### PF-08 — Authentication and access boundary

- **Goal:** Service API keys, principal-scoped project ownership, resource isolation.
- **Outcome:** [ADR-014](docs/adr/ADR-014-Authentication-and-Access-Boundary.md); Bearer API keys; bootstrap CLI; cross-principal 404 policy.
- **Limitation:** No OAuth/OIDC, RBAC, UI login, or HTTP key-management endpoints.

### Phase B runtime hardening (complete)

- Terminal workflow state on executor failure (AUD-016)
- Agency initialization contract (AUD-017)
- Planner dependency validation in structured-output retry (AUD-018)
- ADR-008 executor catalog contract

### GF-00 — Repository readiness (complete)

- Packaging, deterministic offline demo, license posture, CI baseline

---

## Current Product Phase — Desk Research Vertical

**Next priority:** prove one real research methodology end-to-end using the existing platform foundation — **not** more horizontal infrastructure.

Intended vertical:

```
Client Brief
  → Planning
  → Research Design
  → Search / Source Collection
  → Evidence / Knowledge
  → Analysis
  → Insights
  → Writer
  → Review
  → Final Artifact
```

**What exists today vs what is missing:**

| Stage | Platform support | Product completeness |
|-------|------------------|----------------------|
| Client Brief | HTTP API + `ProjectBrief` model | Partial — not full lifecycle |
| Planning | Planner agent + structured output | Integrated for template generation |
| Research Design | Domain models | Not automated end-to-end |
| Search | `search` executor stub | Not product-complete |
| Source collection / provenance | — | Not implemented |
| Evidence / Knowledge | `KnowledgeRepository` port | Metadata persistence only |
| Analysis | `analysis` executor stub | Not product-complete |
| Insights | — | Not implemented |
| Writer / Report | `report` executor stub | Not product-complete |
| Review | — | Not implemented |
| Final artifact | Artifact metadata API | Blob lifecycle incomplete |

Agent registrations (`planner`, `search`, `analysis`, `report`, `proposal`) are **runtime executors**, not proof of a finished research product.

---

## Future Platform Hardening

Deferred until the desk research vertical validates the foundation:

- Production observability (metrics, tracing, structured ops logging)
- Backup/restore automation
- Deployment hardening beyond Compose dev stacks
- Secret management external to bootstrap CLI
- Rate limiting and API versioning
- OAuth/OIDC and richer RBAC
- Scale-out queue (e.g. Redis) **only if** measured need arises
- Multi-tenant SaaS, UI, webhooks/callbacks

---

## Explicitly Not Committed

This roadmap does **not** promise release dates, production SLAs, autonomous agency replacement, PyPI publication, or full “operating system” completeness.

---

## Maturity Labels

| Label | Meaning |
|-------|---------|
| **Implemented** | Code exists in the repository |
| **Tested** | Covered by automated tests |
| **Demonstrable** | Runnable example or demo path exists |
| **Integrated** | Wired into composition root / HTTP / worker path |
| **Production-ready** | Suitable for external deployment without further hardening |

PF-01 through PF-08 are **implemented, tested, and integrated** at the platform layer. The overall product is **not production-ready**.

---

## Documentation source of truth

Code, migrations, automated tests, and accepted ADRs are authoritative. When a capability merges, update ROADMAP, README, and backlog in the same or next documentation pass. See [docs/README.md](docs/README.md#documentation-reality-rules).
