# Architecture Decisions

## RQCL v1 — Research Quality Control Layer (P1-01)

**Status:** Accepted (domain model only; evaluator not implemented)

### Context

Desk research runs need a structured way to decide whether collected evidence is
sufficient to proceed to Analysis, or whether targeted research is still required.
This must not conflate planning intent with run-time knowledge state.

### Decision

Introduce a Research Quality Control Layer (RQCL v1) with three responsibilities:

| Layer | Responsibility |
|---|---|
| **Planner** | Defines *what we need to know* → `ResearchQuestion`, `InformationNeed` |
| **Search / Evidence** | Defines *what we know* → acquired sources and durable evidence |
| **ResearchSufficiencyEvaluator** | Defines *what is still missing* → sufficiency assessments |

**Working unit:** `InformationNeed`, not raw source count and not only
`ResearchQuestion`.

Research sufficiency will be **hybrid** in future milestones:

- deterministic checks (counts, provenance, freshness thresholds)
- semantic assessment (coverage depth, contradiction detection)

P1-01 introduces only the domain model and evaluator port. No runtime gate,
targeted search loop, persistence, or workflow changes are included.

### Domain model

- `SufficiencyStatus` — per-need state: `SUFFICIENT`, `PARTIAL`, `INSUFFICIENT`,
  `MISSING`, `BLOCKED`
- `GapType` — generic gap vocabulary (not case-specific)
- `InformationNeedAssessment` — run-scoped need evaluation
- `ResearchReadinessAssessment` — aggregates needs for one `ResearchQuestion`
- `ResearchReadinessResult` — run-level readiness aggregate

`ResearchDesign` remains unchanged and holds planning intent only. Sufficiency
state belongs to a concrete research run, not the design snapshot.

### Non-goals (P1-01)

- `ResearchReadinessGate` implementation
- Targeted research loop
- Workflow / worker / persistence changes
- LLM or deterministic evaluator implementations

## RQCL v1 — Deterministic Sufficiency Signals (P1-02)

**Status:** Accepted (deterministic facts layer only)

### Decision

Add `DeterministicSufficiencyEvaluator` that maps `ResearchDesign` + run-scoped
`Evidence` to `DeterministicSufficiencySignals` for **every** `InformationNeed`
in the design universe.

Key invariants:

- **Working unit:** `InformationNeed`
- **FACT vs POLICY:** evaluator emits objective counts and availability flags;
  only `GapType.NO_EVIDENCE` is derived when `evidence_count == 0`
- **No guessing:** freshness, quality, diversity, and quantitative signals remain
  unavailable unless explicit deterministic metadata exists on `Evidence`
- **Coverage ≠ sufficiency:** no `InformationNeedAssessment` status is produced

Duplicate semantics use existing stable identifiers: `Evidence.id` and
`Evidence.deduplication_key` (SHA-256 over source, checksum, statement, excerpt,
and information-need refs).

### Non-goals (P1-02)

- LLM sufficiency evaluation
- Final `InformationNeedAssessment` / readiness gate
- Workflow, persistence, API, or runtime integration

## RQCL v1 — Hybrid Sufficiency Evaluator (P1-03)

**Status:** Accepted (application-level only; unwired)

### Decision

Add `HybridResearchSufficiencyEvaluator` that combines P1-02 deterministic facts
with optional semantic assessment via `SemanticSufficiencyAssessor`.

Pipeline:

`ResearchDesign` + `Evidence` → deterministic signals → (optional) semantic
assessment → `InformationNeedAssessment` → `ResearchReadinessAssessment` →
`ResearchReadinessResult`

Key invariants:

- **Short-circuit:** `evidence_count == 0` → `MISSING` / `NO_EVIDENCE` with no LLM call
- **Scope:** semantic assessment is scoped to existing `InformationNeed`; no replanning
- **Insufficiency is data:** research gaps return valid readiness results, not exceptions
- **BLOCKED vs actionable:** `targeted_research_required=True` only when blocking gaps
  are `PARTIAL`, `INSUFFICIENT`, or `MISSING`; all-`BLOCKED` blocking sets
  `targeted_research_required=False` (P1-01 contract refinement)
- **Evidence payload:** only need-mapped evidence; bounded deterministic selection
  by confidence then id (max 10 items)
- **Structured output:** bounded JSON contract with correction retries; technical
  failures raise `SemanticSufficiencyAssessmentError`

Ports:

- `SemanticSufficiencyAssessor` — semantic judgment per need
- `ResearchSufficiencyEvaluator` — run-level hybrid evaluation (implemented, unwired)

### Non-goals (P1-03)

- `ResearchReadinessGate` / workflow integration
- Targeted search loop
- Runtime composition root wiring
- New execution budget stage
- DB persistence or API exposure

## RQCL v1 — Research Readiness Gate (P1-04)

**Status:** Accepted (wired into Desk Research workflow)

### Decision

Insert `task-assess-research-readiness` after evidence extraction and before
analysis in `ResearchDesignWorkflowMapper`.

Runtime path:

`Evidence` → `ResearchReadinessExecutor` → gate → `Analysis` (if ready)

Key invariants:

- **Gate adapter vs evaluator:** `HybridResearchSufficiencyEvaluator` remains
  domain logic; `ResearchReadinessExecutor` is workflow adapter
- **Not ready ≠ failure:** readiness task completes; downstream
  analysis/report/review tasks are `SKIPPED`; workflow `COMPLETED`
- **Outcome channel:** `shared_state.research_readiness.research_outcome`
  distinguishes `ready_for_analysis` vs `insufficient_research`
- **Budget stage:** semantic sufficiency LLM calls use explicit `sufficiency`
  stage (`sufficiency_max_llm_calls`)
- **Technical failures:** provider/budget/structured-output errors fail the
  readiness task normally (`FAILED` workflow)

### Non-goals (P1-04)

- Targeted research loop
- Analysis/Report/Review contract changes
- Adaptive budget
- New WorkflowStatus enum value
