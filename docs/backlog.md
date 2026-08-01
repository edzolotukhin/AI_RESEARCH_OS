# AI Research OS Backlog

Actionable future work only. Completed platform items are listed for reference; do not re-open unless regressions appear.

---

## Completed — Platform Foundation

- [x] Phase B runtime hardening (AUD-016–018, ADR-008)
- [x] **PF-01** Persistence architecture — [ADR-009](adr/ADR-009-Persistence-Boundary-and-Repository-Strategy.md)
- [x] **PF-02** Repository ports and contract tests
- [x] **PF-02.5** Application persistence services
- [x] **PF-03** PostgreSQL adapter, Alembic, Docker Compose PostgreSQL
- [x] **PF-04** Durable workflow checkpointing and resume — [ADR-010](adr/ADR-010-Durable-Workflow-Checkpoint-and-Recovery-Policy.md)
- [x] **PF-05** FastAPI HTTP boundary — [ADR-011](adr/ADR-011-HTTP-API-Boundary-and-Synchronous-Execution-Policy.md)
- [x] **PF-06** Background worker, lease/recovery — [ADR-012](adr/ADR-012-Background-Execution-Claiming-Lease-and-Recovery.md)
- [x] **PF-07** External orchestration, idempotency, n8n examples — [ADR-013](adr/ADR-013-External-Orchestration-and-Idempotent-Submission.md)
- [x] **PF-08** API key authentication, ownership, isolation — [ADR-014](adr/ADR-014-Authentication-and-Access-Boundary.md)
- [x] Docker Compose dev stack (`postgres`, `api`, `worker`, optional `n8n` overlay)
- [x] GF-00 repository readiness baseline

---

## Next — Desk Research Vertical

Primary product objective: execute one real desk research methodology end-to-end on the current platform.

- [ ] **DR-01** Canonical research brief contract — [ADR-015](adr/ADR-015-Desk-Research-Brief-and-Research-Contract.md) *(in progress)*
- [ ] **DR-02** ResearchQuestion / Research Design semantic layer
- [ ] **Search / source collection** — real retrieval, not stub executor behavior
- [ ] **Evidence / knowledge** — provenance, ingestion, and query beyond metadata ports
- [ ] **Analysis → Insights** — structured analytical outputs tied to sources
- [ ] **Writer → Review → Final artifact** — report generation and review gate
- [ ] End-to-end vertical integration test (one methodology, real inputs, inspectable artifact)
- [ ] Client Manager integration with production runtime (if required by vertical)

---

## Next — Platform hygiene (non-blocking)

- [ ] Catalog/registry desynchronization test coverage
- [ ] Full runtime E2E test (all registered executors)
- [ ] Planner `executor_id=planner` re-planning semantics
- [ ] Migrate `scripts/sandbox.py` off legacy `services/project_brief_builder.py`
- [ ] Resolve `Project.runs` in-memory field vs persisted query model
- [ ] Artifact **blob** storage strategy (filesystem vs object store)

---

## Later — Platform hardening

- [ ] Production observability (logging, metrics, tracing)
- [ ] Backup/restore automation
- [ ] Deployment hardening (beyond dev Compose)
- [ ] External secrets manager integration
- [ ] Rate limiting
- [ ] API versioning policy
- [ ] OAuth/OIDC identity (if human users required)
- [ ] Richer RBAC / organizations

---

## Deferred / Not Planned Yet

- UI / client portal
- SaaS multi-tenancy
- Outbound webhooks/callbacks
- Redis or distributed queue (unless scale requires)
- Async planning pipeline
- Automatic retry policy productization
- CRM / billing integrations
- Event system / handover automation (legacy roadmap ideas)

---

## Documentation

When merging platform capabilities, sync [ROADMAP.md](../ROADMAP.md), [README.md](../README.md), and this backlog. ADRs own architectural decisions.
