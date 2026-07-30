# AI Research OS Backlog

## Completed (Phase A / Wave 1)

- [x] Synchronous workflow runtime (`WorkflowEngine`, `TaskScheduler`, `TaskExecutor`)
- [x] `WorkflowCompletionPolicy` and dependency-aware scheduling
- [x] Planner constrained to registered executor IDs (ADR-008)
- [x] Structured output retry and planner payload contract
- [x] `ProjectRepository` persistence
- [x] Architecture documentation sync (A.4)
- [x] Wave 1 legacy cleanup (dead infrastructure, `WorkflowPlan`, services, registries)

## Runtime Hardening (pending)

- [x] AUD-016: terminal `WorkflowRun` state when executor fails during execution
- [x] AUD-017: Agency initialization contract — `WorkflowEngine` remains self-starting via `_ensure_running()`; `Agency.start_research()` performs lazy initialization; explicit `Agency.initialize()` remains supported
- [x] AUD-018: planner dependency validation inside structured-output retry path — graph semantics (unknown dependency, self-dependency, cycle, duplicate task id) validated in `PlannerPayloadContract` after executor ID checks; runtime `WorkflowValidator` / factory graph validation retained; `WorkflowEngine` unchanged
- [ ] Catalog/registry desynchronization test coverage
- [ ] Full runtime E2E test (all registered executors)
- [ ] Planner runtime-executor semantics (`executor_id=planner` re-planning behavior)

## Legacy / tooling

- [ ] Migrate `scripts/sandbox.py` off `services/project_brief_builder.py`

## Product (not started)

- [ ] Client Manager wired to production runtime
- [ ] Knowledge Manager (beyond static files)
- [ ] Business Consultant / early lifecycle automation

## Future

- Playbooks expansion
- Reviewer role
- Event System
- Handover
