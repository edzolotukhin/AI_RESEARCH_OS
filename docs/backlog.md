# AI Research OS Backlog

## Completed (Phase A / Wave 1)

- [x] Synchronous workflow runtime (`WorkflowEngine`, `TaskScheduler`, `TaskExecutor`)
- [x] `WorkflowCompletionPolicy` and dependency-aware scheduling
- [x] Planner constrained to registered executor IDs (ADR-008)
- [x] Structured output retry and planner payload contract
- [x] `ProjectRepository` persistence
- [x] Architecture documentation sync (A.4)
- [x] Wave 1 legacy cleanup (dead infrastructure, `WorkflowPlan`, services, registries)

## Runtime Hardening (remaining)

- [x] AUD-016: terminal `WorkflowRun` state when executor fails during execution
- [x] AUD-017: Agency initialization contract — `WorkflowEngine` remains self-starting via `_ensure_running()`; `Agency.start_research()` performs lazy initialization; explicit `Agency.initialize()` remains supported
- [x] AUD-018: planner dependency validation inside structured-output retry path — graph semantics (unknown dependency, self-dependency, cycle, duplicate task id) validated in `PlannerPayloadContract` after executor ID checks; runtime `WorkflowValidator` / factory graph validation retained; `WorkflowEngine` unchanged
- [ ] Catalog/registry desynchronization test coverage
- [ ] Full runtime E2E test (all registered executors)
- [ ] Planner runtime-executor semantics (`executor_id=planner` re-planning behavior)

## Legacy / tooling

- [ ] Migrate `scripts/sandbox.py` off `services/project_brief_builder.py`

## Product Foundation

- [x] **PF-01** Persistence Architecture Contract — [ADR-009](adr/ADR-009-Persistence-Boundary-and-Repository-Strategy.md), [architecture/product-foundation-persistence.md](../architecture/product-foundation-persistence.md)
- [ ] **PF-02** Persistence ports and in-memory contract tests
- [ ] **PF-03** PostgreSQL adapter and migrations
- [ ] **PF-04** Docker Compose development environment
- [ ] **PF-05** FastAPI application boundary
- [ ] **PF-06** Background workflow execution
- [ ] Extract `ProjectRepository` port; decouple `Agency` from concrete infrastructure class
- [ ] Define `ExecutionLog` persistence record and port (no domain type today)
- [ ] Implement `load_project` / `list_projects` / `delete_project` in file or PostgreSQL adapter
- [ ] Resolve `Project.runs` in-memory field vs persisted query model
- [ ] Artifact blob storage strategy (filesystem vs object store)

PostgreSQL, Docker, FastAPI, and background execution are **not implemented** — contract only.

## Product (not started)

- [ ] Client Manager wired to production runtime
- [ ] Knowledge Manager (beyond static files)
- [ ] Business Consultant / early lifecycle automation

## Future

- Playbooks expansion
- Reviewer role
- Event System
- Handover

## GitHub Face Sprint

- [x] **GF-00 complete** — repository readiness baseline (hygiene, packaging, demo, docs sync, license posture)
- [x] GF-00 / PR-A: Repository Hygiene — removed tracked `agency/projects/` runtime JSON from git index; hardened `.gitignore`; removed generated `strukture.txt`; runtime creates project storage on demand; 289/289 tests pass
- [x] GF-00 / PR-B: Packaging and Environment Contract — runtime deps in `requirements.txt` (`openai`, `python-dotenv`); Python `>=3.11,<3.15` in `pyproject.toml`; `.env.example` for `OPENAI_API_KEY`; clean venv install verified; 289/289 tests pass
- [x] GF-00 / PR-C: Examples Cleanup and Public Demo Contract — removed legacy misleading examples; added offline `examples/deterministic_research_demo.py` (WorkflowTemplate → WorkflowRun → WorkflowEngine); subprocess test; no repo artifacts; 289/289 tests pass
- [x] GF-00 / PR-D: Roadmap and Changelog Synchronization — `ROADMAP.md` and canonical `CHANGELOG.md` aligned with Phase B completion, GF-00 progress, and 289-test baseline
- [x] GF-00 / PR-E: License Posture — proprietary All Rights Reserved `LICENSE`; README legal section aligned; GF-00 closed
