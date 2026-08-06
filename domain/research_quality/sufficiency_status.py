from __future__ import annotations

from enum import Enum


class SufficiencyStatus(str, Enum):
    """Per-InformationNeed research sufficiency state for a concrete run."""

    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    MISSING = "missing"
    BLOCKED = "blocked"


READINESS_BLOCKING_STATUSES = frozenset(
    {
        SufficiencyStatus.PARTIAL,
        SufficiencyStatus.INSUFFICIENT,
        SufficiencyStatus.MISSING,
        SufficiencyStatus.BLOCKED,
    },
)
