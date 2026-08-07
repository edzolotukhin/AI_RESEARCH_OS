# ADR-022: P1-06 Semantic Sufficiency Hardening — M1/M2 Foundation

**Status:** Active (P1-06 M1/M2)
**Date:** 2026-08-07
**Deciders:** Platform / Desk Research vertical

## Context

Semantic sufficiency currently merges LLM semantic judgment with deterministic signals inside a single production contract (`SemanticSufficiencyAssessment`) and readiness aggregation path. P1-06 accepted a target architecture that separates:

- **semantic facts** (what evidence supports or fails to support);
- **deterministic policy** (formal requirements, blocking, readiness).

M1/M2 introduce the contract and migration foundation only. Production semantic execution, planner output, readiness aggregation, and targeted research remain unchanged.

## Decision

### 1. `EvidenceExpectation` on `InformationNeed`

`InformationNeed` may now carry optional `evidence_expectation: EvidenceExpectation | None`.

- **Default:** `None` for legacy planner payloads and persisted designs.
- **Write-new / read-old:** legacy payloads without `evidence_expectation` deserialize successfully with `None`.
- **No inference:** legacy records do not receive fabricated research criteria.

`EvidenceExpectation` is a **target/requirement** contract defining what counts as an answer for one InformationNeed. It is not an assessment, LLM output, search plan, remediation plan, or readiness decision.

Required v1 fields:

| Field | Semantics |
|---|---|
| `nature` | `EvidenceNature`: `quantitative`, `qualitative`, `mixed` |
| `required_aspects` | Canonical deterministic aspect identifiers |
| `geography` | Optional geographic scope (`None` = no constraint) |
| `timeframe` | Optional temporal scope (`None` = no constraint) |
| `minimum_independent_sources` | Optional formal threshold (`>= 1` when present) |
| `requires_quantitative_evidence` | Formal deterministic boolean requirement |

### 2. Backward compatibility

- Legacy `InformationNeed` and `ResearchDesign` JSON payloads remain readable.
- New payloads roundtrip deterministically through existing JSON serialization paths.
- **No PostgreSQL schema migration** is required; optional nested JSON is additive.

### 3. Canonical aspect identifiers

`required_aspects` are canonical deterministic identifiers suitable for future comparison against semantic `supported_aspects` / `missing_aspects`.

Normalization (`canonical_aspect_ids`):

- strip whitespace;
- reject blank / whitespace-only identifiers;
- deduplicate deterministically preserving first-seen order;
- serialize as ordered lists without semantic rewriting.

The same normalization applies to `RawSemanticDecision` aspect/conflict fields.

### 4. `RawSemanticDecision`

Introduced as a pure domain contract for future semantic assessor output.

Contains semantic facts only:

- `supported_aspects`
- `missing_aspects`
- `semantic_conflicts`
- `confidence`
- `reason`

Explicitly excludes policy/readiness/remediation fields (`status`, `gap_types`, `blocking`, `ready_for_analysis`, `search_directives`, `coverage`, etc.).

### 5. Deterministic policy foundation

`SufficiencyPolicyResult` stores policy inputs only:

- `coverage`
- `gap_types`

`status` is **derived** via `derive_policy_sufficiency_status(coverage, gap_types)` to prevent contradictory independent decision states.

`blocking` is **derived** from existing `BLOCKING_GAP_TYPES`.

`ready_for_analysis` is intentionally absent; readiness remains downstream in existing aggregation/gate logic.

The derivation helper is a foundation stub for M1/M2 tests and future M3+ wiring — not the full production policy algorithm.

### 6. Runtime status (M1/M2)

M1/M2 do **not** switch production semantic execution:

- `LlmSemanticSufficiencyAssessor` unchanged
- `SemanticSufficiencyAssessment` unchanged
- `readiness_aggregation.py` unchanged
- Planner contract unchanged

## Consequences

### Positive

- Stable contract layer for P1-06 M3+ migration to `RawSemanticDecision`.
- Backward-compatible optional enrichment of `InformationNeed`.
- Single-source-of-truth policy result foundation without readiness duplication.

### Negative / deferred

- Planner does not yet populate `EvidenceExpectation`.
- Production semantic path still uses `SemanticSufficiencyAssessment`.
- Full deterministic sufficiency policy and readiness gate redesign deferred.

## References

- P1-06 Contract Audit and Migration Plan
- ADR-016 Desk Research Design and Semantic Planning
- `domain/planning/evidence_expectation.py`
- `domain/research_quality/raw_semantic_decision.py`
- `domain/research_quality/sufficiency_policy_result.py`
