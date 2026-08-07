# P1-06 Semantic Sufficiency — Repeatability Acceptance

## Status

**P1-06 SEMANTIC SUFFICIENCY REPEATABILITY — PASS**

**P1-06 SEMANTIC SUFFICIENCY LIVE ACCEPTANCE — CLOSED**

“CLOSED” means the Semantic Sufficiency component has satisfied its defined offline, mini-live, and repeatability acceptance gates under P1-06. It does **not** mean the complete Desk Research workflow is accepted.

Prior checkpoint: [`P1-06-M3-Semantic-Sufficiency-Mini-Live-Acceptance.md`](P1-06-M3-Semantic-Sufficiency-Mini-Live-Acceptance.md) (commit `3d28bcb`).

## Scope

This document records the final **controlled real-provider repeatability gate** for the Semantic Sufficiency boundary:

```
fixed InformationNeed + fixed Evidence[]
  → LlmSemanticSufficiencyAssessor
  → RawSemanticDecision
  → semantic_decision_normalizer
  → deterministic SufficiencyPolicy
  → application compatibility adapter
  → SemanticSufficiencyAssessment
```

This gate does **not** prove Planner, Search, Evidence acquisition, Analysis, Report, Review, or complete Desk Research E2E quality.

## Configuration

| Setting | Value |
|---------|-------|
| `llm_model` | `gpt-5` |
| `sufficiency_reasoning_effort` | `minimal` |
| `sufficiency_max_output_tokens` | `8192` |
| `structured_output_max_attempts` | `3` |

**Execution order:** A1 → B1 → A2 → B2 → A3 → B3

| Metric | Value |
|--------|-------|
| Planned executions | 6 |
| Completed executions | 6 |

Harness opt-in: `SUFFICIENCY_REPEATABILITY_LIVE=1` (commit `b26892e`).

## Scenario Definitions

### Scenario A — Obviously Sufficient

- **ID:** `scenario_a_obviously_sufficient`
- **Legacy path:** `evidence_expectation=None`
- **Evidence:** `evidence_count=3`, `independent_source_count=2`

**Expected:**

| Field | Value |
|-------|-------|
| `supported_aspects` | `["__legacy_need__"]` |
| `missing_aspects` | `[]` |
| `semantic_conflicts` | `[]` |
| `coverage` | `1.0` |
| Status | `SUFFICIENT` |
| `search_directives` | `[]` |

### Scenario B — Obviously Insufficient

- **ID:** `scenario_b_obviously_insufficient`
- **Legacy path:** `evidence_expectation=None`
- **Evidence:** `evidence_count=2`, `independent_source_count=2`

**Expected:**

| Field | Value |
|-------|-------|
| `supported_aspects` | `[]` |
| `missing_aspects` | `["__legacy_need__"]` |
| `semantic_conflicts` | `[]` |
| `coverage` | `0.0` |
| `gap_types` | includes `INSUFFICIENT_DEPTH` |
| Status | `INSUFFICIENT` |
| `search_directives` | `["__legacy_need__"]` |

## Execution Results

| Execution | Scenario | Status | Result |
|-----------|----------|--------|--------|
| A1 | A | `SUFFICIENT` | PASS |
| B1 | B | `INSUFFICIENT` | PASS |
| A2 | A | `SUFFICIENT` | PASS |
| B2 | B | `INSUFFICIENT` | PASS |
| A3 | A | `SUFFICIENT` | PASS |
| B3 | B | `INSUFFICIENT` | PASS |

**Overall: 6/6 PASS**

All six executions used `attempts=1`, `retries=0`, and clean first-pass structured output.

## Semantic Stability

| Metric | Result |
|--------|--------|
| Scenario A → `SUFFICIENT` | **3/3** |
| Scenario B → `INSUFFICIENT` | **3/3** |
| Unexpected aspect IDs | **0** |
| Scenario A unexpected `semantic_conflicts` | **0** |
| Scenario B unexpected `semantic_conflicts` | **0** |
| Unexpected `MISSING` | **0** |
| Unexpected `BLOCKED` | **0** |
| Domain validation errors | **0** |

Scenario B **never** regressed to `UNRESOLVABLE` → `BLOCKED` across all three repeated executions. All three produced:

```
missing_aspects=["__legacy_need__"]
semantic_conflicts=[]
→ INSUFFICIENT_DEPTH → INSUFFICIENT → search_directives=["__legacy_need__"]
```

This confirms the M3.5 resolvability-boundary correction under repeated real-provider execution.

## Structured-Output Stability

| Metric | Value |
|--------|-------|
| First-pass successes | **6** |
| Retries | **0** |
| Contract failures | **0** |
| Parse failures | **0** |
| Truncations | **0** |

Every execution: `attempts=1`. No correction attempt was required.

This confirms repeatability of the M3.4 first-pass prompt/contract alignment for this controlled matrix. Two obvious scenarios × three repetitions is **not** universal statistical proof of first-pass reliability across all inputs.

## Policy Stability

The LLM continued to produce bounded `RawSemanticDecision` semantic facts. Final status remained deterministic policy output.

**Scenario A (all three):** `coverage=1.0` → `SUFFICIENT`

**Scenario B (all three):** `coverage=0.0` + `INSUFFICIENT_DEPTH` + `evidence_count > 0` → `INSUFFICIENT`

- No `evidence_count > 0` case produced `MISSING`.
- No insufficient-evidence case produced `BLOCKED`.

## Confidence Variation

Confidence is semantic metadata only; no threshold was used for acceptance.

| Scenario | Min | Max | Mean |
|----------|-----|-----|------|
| A | 0.78 | 0.80 | 0.79 |
| B | 0.12 | 0.20 | 0.1533 |

Confidence varied within a narrow, non-authoritative range while final domain classifications remained stable across all six executions.

## Usage

| Metric | Value |
|--------|-------|
| `scenario_executions` | 6 |
| `llm_calls` | 6 |
| `retries` | 0 |
| `elapsed_seconds` | 22.984 |
| `total_output_tokens` | 614 |
| `total_reasoning_tokens` | 0 |

`estimated_cost_usd` was not exposed by telemetry. No cost estimate is recorded.

## Acceptance Chain

P1-06 progression (verified via repository history):

| Commit | Milestone |
|--------|-----------|
| `d0c69d3` | feat: harden semantic sufficiency boundary |
| `263df32` | chore: add sufficiency attempt diagnostics |
| `55d8b0f` | fix: align semantic sufficiency first-pass contract |
| `dfd2e16` | fix: harden semantic resolvability boundary |
| `3d28bcb` | docs: record P1-06 semantic sufficiency mini-live acceptance |
| `b26892e` | test: add semantic sufficiency repeatability gate |

Related architecture: ADR-022 (M1/M2 foundation), ADR-023 (M3 production boundary). ADRs describe design decisions; this document records runtime acceptance evidence.

## Acceptance Evidence

Runtime result artifact:

```
artifacts/acceptance/p1_06_semantic_repeatability.json
```

**Status:** present locally, **untracked** (not committed to the repository).

The artifact matches the results recorded in this document (`acceptance_verdict`: `P1-06 SEMANTIC SUFFICIENCY REPEATABILITY — PASS`, `passed`: true, 6/6 executions). It contains configuration, per-execution summaries, aggregate metrics, and attempt history. It does **not** include API keys, full prompts, full provider responses, or source payloads.

## Limitations

- Repeatability matrix contains **two deliberately obvious scenarios**, each repeated three times.
- This is **controlled acceptance**, not statistical certification of all possible semantic judgments.
- Both scenarios exercise **legacy** `evidence_expectation=None`.
- **EvidenceExpectation-backed** real-provider behavior has not yet been live-accepted by this gate.
- Borderline or ambiguous semantic cases were not part of this gate.
- Complete Desk Research E2E is **not** accepted by P1-06.
- Search, Evidence acquisition, Analysis, Report, and Review quality are outside this acceptance scope.

These limitations do **not** prevent closure of P1-06 under its defined acceptance scope.

## Closure Decision

**P1-06 Semantic Sufficiency live acceptance is CLOSED.**

Rationale:

1. Offline contract/policy regression suites passed.
2. Controlled mini-live passed 2/2 (`3d28bcb`).
3. First-pass structured-output alignment was validated (M3.4).
4. Resolvability boundary was corrected and validated (M3.5).
5. Repeatability gate passed **6/6**.
6. All six repeatability executions succeeded first-pass.
7. No retries occurred.
8. Semantic classifications were stable (A: 3/3 SUFFICIENT; B: 3/3 INSUFFICIENT).
9. Policy invariants were stable (no unexpected MISSING/BLOCKED).
10. No MISSING/BLOCKED regression occurred on Scenario B.

No additional Semantic Sufficiency mini-live tuning is required before Desk Research E2E.

Reopen P1-06 only if a future E2E failure provides evidence pointing back to this component.

## Next Project Gate

**ONE CONTROLLED SERBIA MICROGREENS DESK RESEARCH E2E ACCEPTANCE RUN**

This is a **separate acceptance gate**. It validates integration across the broader workflow and must not be represented as part of the P1-06 acceptance result.
