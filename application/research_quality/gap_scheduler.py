from __future__ import annotations

from domain.research_quality.targeted_research_request import TargetedResearchRequest


def select_next_actionable_gap(
    gaps: tuple[TargetedResearchRequest, ...],
    *,
    gap_attempt_counts: dict[str, int],
    stalled_need_ids: set[str],
    max_attempts_per_gap: int,
) -> TargetedResearchRequest | None:
    """Pick the next eligible gap for the current round without starvation."""
    for request in gaps:
        need_id = request.information_need_id
        if gap_attempt_counts.get(need_id, 0) >= max_attempts_per_gap:
            continue
        if need_id in stalled_need_ids:
            continue
        return request
    return None
