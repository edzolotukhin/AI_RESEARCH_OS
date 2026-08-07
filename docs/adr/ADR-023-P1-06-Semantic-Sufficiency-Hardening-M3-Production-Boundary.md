# ADR-023: P1-06 Semantic Sufficiency Hardening — M3 Production Boundary

**Status:** Active (P1-06 M3)
**Date:** 2026-08-07
**Deciders:** Platform / Desk Research vertical

## Context

M1/M2 introduced domain contracts (`RawSemanticDecision`, `EvidenceExpectation`, `SufficiencyPolicyResult`) without changing production semantic execution. Production still used a merged LLM contract where the model chose final `SufficiencyStatus`, `gap_types`, and `search_directives`.

M1/M2 verification established that final status is **not** domain-complete when derived from `coverage + gap_types` alone; `evidence_count` is required to preserve the invariant that `MISSING` is invalid when evidence exists.

## Decision

### 1. RawSemanticDecision is the LLM boundary

`LlmSemanticSufficiencyAssessor` now requires structured output matching `RawSemanticDecision`:

- `supported_aspects`
- `missing_aspects`
- `semantic_conflicts`
- `confidence`
- `reason`

The LLM must not return authoritative policy fields (`status`, `gap_types`, `search_directives`, `blocking`, `ready_for_analysis`, `coverage`).

### 2. Deterministic policy is the single source of truth for status

`apply_sufficiency_policy()` in `domain/research_quality/sufficiency_policy.py` is the authoritative production derivation path:

```
RawSemanticDecision
    + DeterministicSufficiencySignals
    + EvidenceExpectation (optional)
        ↓ normalize
        ↓ derive coverage / gap_types
        ↓ derive_policy_sufficiency_status(coverage, gap_types, evidence_count)
        ↓ SemanticSufficiencyAssessment (compatibility adapter)
```

`SemanticSufficiencyAssessment.status` is populated by policy, not by the LLM.

### 3. evidence_count invariant

`derive_policy_sufficiency_status()` now requires `evidence_count`:

- `evidence_count == 0` → `MISSING`
- `evidence_count > 0` → never `MISSING`

Readiness aggregation retains defensive coercion as a safety net.

### 4. Legacy EvidenceExpectation=None path

When `InformationNeed.evidence_expectation` is absent:

- no requirements are fabricated;
- the assessor prompt instructs the model to derive concise canonical aspect identifiers from the InformationNeed description;
- coverage uses supported/missing aspect ratio when no required aspects exist.

### 5. Search directives compatibility

`RawSemanticDecision` does not own `search_directives`. Policy derives them deterministically from `missing_aspects` for non-SUFFICIENT, non-BLOCKED statuses to preserve downstream targeted-research compatibility.

Remediation/query planning remains a later milestone.

### 6. BLOCKED vs blocking

`UNRESOLVABLE` remains outside `BLOCKING_GAP_TYPES`:

- `status == BLOCKED` when `UNRESOLVABLE` is present;
- `SufficiencyPolicyResult.blocking == False` for UNRESOLVABLE-only gaps.

Downstream readiness uses `SufficiencyStatus` (`READINESS_BLOCKING_STATUSES`, `ACTIONABLE_BLOCKING_STATUSES`), not the policy `blocking` property. This distinction is intentional: BLOCKED needs block readiness but are not actionable for targeted research.

Semantic unresolvability is signaled via `semantic_conflicts` containing the canonical identifier `unresolvable`.

### 7. Confidence

`RawSemanticDecision.confidence` is semantic metadata only. M3 policy does not apply confidence thresholds.

## Consequences

### Positive

- Clear hybrid boundary: LLM semantic facts, deterministic policy decisions.
- Single authoritative status derivation with evidence_count preserved.
- Backward-compatible `SemanticSufficiencyAssessment` adapter minimizes downstream blast radius.

### Deferred

- Planner population of `EvidenceExpectation`.
- Dedicated remediation/query-planning layer replacing derived search_directives.
- Geography/timeframe deterministic enforcement (remain semantic when not safely enforceable).
- Mini-live provider validation gate.

## References

- ADR-022 P1-06 M1/M2 Foundation
- `domain/research_quality/sufficiency_policy.py`
- `application/research_quality/raw_semantic_decision_contract.py`
- `infrastructure/research_quality/llm_semantic_sufficiency_assessor.py`
