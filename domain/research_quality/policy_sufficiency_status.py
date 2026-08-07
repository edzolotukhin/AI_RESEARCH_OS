from __future__ import annotations

from domain.research_quality.gap_type import BLOCKING_GAP_TYPES, GapType
from domain.research_quality.sufficiency_status import SufficiencyStatus


def derive_policy_sufficiency_status(
    *,
    coverage: float,
    gap_types: tuple[GapType, ...],
    evidence_count: int = 0,
) -> SufficiencyStatus:
    """
    Authoritative deterministic status derivation for policy results.

    evidence_count is required to preserve the production invariant that
    MISSING is invalid when evidence exists.
    """
    if evidence_count == 0:
        return SufficiencyStatus.MISSING

    if GapType.UNRESOLVABLE in gap_types:
        return SufficiencyStatus.BLOCKED

    blocking_gaps = tuple(
        gap_type for gap_type in gap_types if gap_type in BLOCKING_GAP_TYPES
    )
    if not blocking_gaps:
        if coverage >= 1.0:
            return SufficiencyStatus.SUFFICIENT
        if coverage > 0.0:
            return SufficiencyStatus.PARTIAL
        return SufficiencyStatus.INSUFFICIENT

    if coverage > 0.0:
        return SufficiencyStatus.PARTIAL
    return SufficiencyStatus.INSUFFICIENT
