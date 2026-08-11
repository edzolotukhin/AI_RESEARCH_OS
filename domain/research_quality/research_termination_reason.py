from __future__ import annotations

# Controlled research termination when a bounded research budget is exhausted.
# Generic platform vocabulary — not domain-specific.
SUFFICIENCY_BUDGET_EXHAUSTED = "sufficiency_budget_exhausted"
EVIDENCE_REMEDIATION_BUDGET_EXHAUSTED = "evidence_remediation_budget_exhausted"
# Same token as ExecutionBudget.assert_can_call reserve protection.
DOWNSTREAM_RESERVE_EXHAUSTED = "downstream_reserve_exhausted"

# Readiness results that stop further targeted research due to budget use this set.
BUDGET_CONTROLLED_TERMINATION_REASONS = frozenset(
    {
        SUFFICIENCY_BUDGET_EXHAUSTED,
        EVIDENCE_REMEDIATION_BUDGET_EXHAUSTED,
        DOWNSTREAM_RESERVE_EXHAUSTED,
    },
)
