# ADR-016: Desk Research Design and Semantic Planning

**Status:** Active (DR-02)
**Date:** 2026-08-01
**Deciders:** Platform / Desk Research vertical

## Context

DR-01 introduced the canonical `ResearchBrief` as durable input and an immutable `WorkflowTemplate.research_brief_snapshot`. The planner previously emitted a runtime-oriented `ResearchPlan` (stages, tasks, executor IDs), using task topology as an implicit substitute for semantic research design.

Desk Research requires an explicit, reviewable layer describing *how* a brief will be investigated — research questions, information needs, source strategy, analysis intent, and deliverable structure — without implementing search, evidence extraction, or report generation yet.

## Decision

### 1. Canonical model: `ResearchDesign`

Introduce `ResearchDesign` as a **frozen domain value object** in `domain/planning/research_design.py`.

| Field | Semantics |
|---|---|
| `research_questions[]` | Explicit questions guiding investigation |
| `information_needs[]` | Data/evidence required per question (DR-03 prep) |
| `source_strategy[]` | High-level evidence categories (no provider URLs) |
| `analysis_plan[]` | Intended analytical approaches (semantic, not executable) |
| `deliverable_plan[]` | Expected report structure/sections |
| `assumptions[]` | Planning assumptions |
| `limitations[]` | Known scope limits |
| `language` | Primary language (default `en`) |

`ResearchDesign` is **not** the workflow graph, search results, artifacts, or final report.

### 2. `ResearchQuestion` and `InformationNeed`

Minimal shapes:

**ResearchQuestion:** `id`, `question`, `objective_refs[]`, `priority` (1–5), `rationale`

**InformationNeed:** `id`, `research_question_id`, `description`, `priority`, `preferred_source_types[]`, `timeframe`, `geography`

Information needs are modeled at design level with explicit linkage to questions. Design-level lists remain the aggregate boundary; question-level `information_needs[]` on `ResearchQuestion` are not duplicated.

### 3. Planner authority (Option B)

**PlannerAgent** remains the single planning authority. Its LLM output is now **ResearchDesign JSON only** — no stages, tasks, or executor IDs in the planner contract.

Runtime task topology is derived **deterministically** in application code:

```
ResearchBrief
    → PlannerAgent (LLM)
    → ResearchDesign
    → ResearchDesignWorkflowMapper
    → WorkflowTemplate / TaskDefinitions
    → WorkflowRun
```

Legacy `ResearchPlan` parsing/mapping is retained for unit tests only; production path uses design → mapper.

Fixed desk-research pipeline (DR-02):

1. `task-collect-evidence` (`search`) — placeholder for DR-03
2. `task-analyze` (`analysis`) — placeholder for DR-05
3. `task-write-report` (`report`) — placeholder for DR-06

Task metadata includes `research_design_id` for traceability.

### 4. Objective traceability

`ResearchQuestion.objective_refs` link to `ResearchBrief.objectives` by exact text (normalized for duplicate/coverage checks). When the brief has objectives, validation requires all objectives be covered; orphan questions (no refs) are detectable via `find_orphan_questions`.

### 5. Durable snapshot

`WorkflowTemplate.research_design_snapshot` stores an immutable copy alongside `research_brief_snapshot`.

- PostgreSQL: persisted in template JSONB snapshot
- Memory: full round-trip
- File backend: **no separate workflow-template persistence**; design snapshot exists only for in-process runs (same limitation as pre-DR-01 template snapshots on file backend)

Later changes to `Project.research_brief` or replanning do **not** mutate existing run snapshots.

### 6. Replanning policy

Every research submission creates a new immutable design snapshot tied to a new `WorkflowTemplate` / `WorkflowRun`. Replanning = new submission/run. No design versioning UI in DR-02.

### 7. Idempotency (PF-07)

`ResearchDesign` is **generated output**, not client input. Idempotency fingerprint remains based on canonical `ResearchBrief` (+ project, principal, key). Idempotent replay returns the same run and design snapshot without replanning.

### 8. Authorization (PF-08)

Research design is exposed only on runs the caller owns. Cross-principal lookup returns **404** with no design leakage.

### 9. API representation

`POST /projects/{id}/research` (202) and `GET /workflow-runs/{id}` expose `research_design` with questions, information needs, source strategy, analysis plan, and deliverable plan. Internal planner DTOs and executor wiring are not exposed.

### 10. Validation

Semantic validation (`validate_research_design`) enforces:

- ≥1 research question; non-empty question text
- Unique question IDs and information-need IDs
- No duplicate questions after normalization
- Non-empty `source_strategy`, `analysis_plan`, `deliverable_plan`
- Information-need references resolve to existing questions
- Brief objective coverage when objectives exist

Planner structured-output contract validates parseability and ID uniqueness before workflow creation. Invalid planner output fails safely (structured-output retry, then error).

### 11. Deferred scope

DR-02 explicitly does **not** implement:

- Web search / `SearchProvider`
- Source discovery, evidence extraction
- Analysis, writer, reviewer agents
- Vector DB, Redis, WorkflowEngine redesign

### 12. Runtime execution honesty (DR-02)

ResearchDesign and the three-task runtime skeleton (`task-collect-evidence` →
`task-analyze` → `task-write-report`) are **planned stages only** in production.

| Mode | search / analysis / report executors |
|---|---|
| **Production (default)** | `UnimplementedCapabilityExecutor` — raises `CapabilityNotImplementedError` before any task success transition |
| **Explicit test/smoke** (`DETERMINISTIC_STAGE_EXECUTORS=1` or `ApplicationConfig.deterministic_stage_executors=True`) | `DeterministicStageExecutor` — synthetic completion for infrastructure verification only |

Production invariant until DR-03/05/06:

- A desk-research run **must not** reach `WorkflowStatus.COMPLETED` because placeholder agents set success flags.
- The first unimplemented stage fails explicitly; PF-04 policy marks the task `FAILED`, dependents `SKIPPED`, workflow `FAILED`.
- No report artifact is produced or implied.

Legacy `SearchAgent` / `AnalysisAgent` / `ReportAgent` classes remain in the codebase but are **not registered** in the production composition root.

## Consequences

### Positive

- Clear separation: semantic planning (LLM) vs runtime planning (deterministic mapper)
- External clients can inspect research intent without parsing task graphs
- DR-03+ can target `information_needs` and `source_strategy` directly

### Negative / limitations

- Fixed three-task pipeline until DR-03+ adds real executors
- Legacy `MethodologyProposal` (`domain/legacy/methodology_proposal.py`) persists in PostgreSQL `projects.research_design` JSONB for backward compatibility only — distinct from desk-research `ResearchDesign`
- File backend does not durably persist workflow template snapshots

## Related

- ADR-015 (ResearchBrief — DR-01 complete)
- ADR-008 (Executor catalog — runtime executors unchanged in planner output)
- ADR-013 (Idempotency)
- ADR-014 (Ownership)
- DR-03 (Search — planned)
