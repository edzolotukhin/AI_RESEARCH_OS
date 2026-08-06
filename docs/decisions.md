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
