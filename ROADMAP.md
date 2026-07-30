# AI Research OS — Development Roadmap

Version: 1.1

---

# Development Philosophy

AI Research OS is developed incrementally. Every sprint must produce a working result, preserve architectural consistency, and reduce technical debt when practical.

---

# Phase A — Stabilization ✅ COMPLETED

Objective: stabilize the synchronous research workflow runtime.

Completed:

- Agency application facade and composition root
- Planner → ResearchPlan → WorkflowTemplate → WorkflowRun pipeline
- ADR-008 Executor Catalog Contract
- Planner constrained to registered executor IDs
- WorkflowEngine synchronous runtime loop
- TaskScheduler, TaskExecutor, ExecutorResolver
- WorkflowCompletionPolicy
- Structured output retry and planner payload contract
- Architecture documentation sync (A.4)
- Phase B Wave 1 cleanup: dead infrastructure, WorkflowPlan, legacy services, dead registries

Result: production demo path (`main.py` → `start_research`) runs end-to-end with mock or real LLM.

---

# Phase B — Runtime Hardening 🚧 CURRENT

Objective: harden runtime contracts and remove remaining legacy surface before product expansion.

Pending:

- AUD-016: terminal WorkflowRun state on executor failure
- AUD-017: Agency initialization contract
- AUD-018: planner dependency validation in retry path
- Catalog/registry synchronization test coverage
- Full runtime E2E test coverage
- Planner runtime-executor semantics (`planner` as registered executor)

Legacy tooling:

- Migrate `scripts/sandbox.py` off `services/project_brief_builder.py`

---

# Phase 2 — Client Qualification (planned)

Objective: client qualification workflow and Project Brief automation.

Not started in production runtime. Client Manager agent exists but is not wired to `create_application()`.

---

# Phase 3 — Research Design (planned)

Research Designer, methodology and sample design automation.

---

# Phase 4 — Proposal Generation (planned)

Commercial proposal generation workflow.

---

# Phase 5 — Research Execution (planned)

Fieldwork and operational research support.

---

# Phase 6 — Analytics (planned)

Analysis, reporting, and presentation generation.

---

# Phase 7 — Knowledge Platform (planned)

Corporate knowledge base and retrieval.

---

# Phase 8 — Business Platform (planned)

CRM, client portal, integrations.

---

# Post-Phase B — Open Source Polish (planned)

Repository presentation only — not started:

- README presentation and badges
- Diagrams and assets
- Repository metadata
- Examples and demo polish
- Releases, contributing, security, and license documentation

---

# Long-term Evolution

Multi-agent collaboration, workflow optimization, financial management, localization, multi-agency support — only after core runtime is stable.

---

# Definition of Done

A phase is complete when functionality works, architecture stays consistent, scoped documentation is updated, and the system is ready for the next phase.
