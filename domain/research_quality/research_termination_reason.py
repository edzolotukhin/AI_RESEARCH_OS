from __future__ import annotations

# Controlled research termination when a bounded research budget is exhausted.
# Generic platform vocabulary — not domain-specific.
SUFFICIENCY_BUDGET_EXHAUSTED = "sufficiency_budget_exhausted"

# Readiness results that stop further targeted research due to budget use this set.
BUDGET_CONTROLLED_TERMINATION_REASONS = frozenset(
    {
        SUFFICIENCY_BUDGET_EXHAUSTED,
    },
)
