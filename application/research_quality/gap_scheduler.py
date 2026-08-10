from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.research_quality.targeted_research_request import TargetedResearchRequest

COHORT_FIRST_OPPORTUNITY = "first_opportunity"
COHORT_REPEAT_OPPORTUNITY = "repeat_opportunity"
REASON_NONE_ELIGIBLE = "none_eligible"


def _tie_break_key(request: TargetedResearchRequest) -> tuple[str, str]:
    return (request.research_question_id, request.information_need_id)


@dataclass(frozen=True)
class GapSchedulerDecision:
    """Deterministic allocation record for one scheduler decision (not a domain model)."""

    selected: TargetedResearchRequest | None
    eligible_need_ids: tuple[str, ...]
    attempt_counts: dict[str, int]
    first_opportunity_need_ids: tuple[str, ...]
    repeat_opportunity_need_ids: tuple[str, ...]
    cohort: str | None
    selection_reason: str
    tie_break_key: tuple[str, str] | None
    remaining_remediation_evidence_calls: int | None
    stalled_need_ids: tuple[str, ...]
    prior_improved_need_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        selected_id = (
            self.selected.information_need_id if self.selected is not None else None
        )
        return {
            "eligible_need_ids": list(self.eligible_need_ids),
            "attempt_counts": dict(self.attempt_counts),
            "first_opportunity_need_ids": list(self.first_opportunity_need_ids),
            "repeat_opportunity_need_ids": list(self.repeat_opportunity_need_ids),
            "cohort": self.cohort,
            "selected_need_id": selected_id,
            "selection_reason": self.selection_reason,
            "tie_break_key": list(self.tie_break_key) if self.tie_break_key else None,
            "remaining_remediation_evidence_calls": (
                self.remaining_remediation_evidence_calls
            ),
            "stalled_need_ids": list(self.stalled_need_ids),
            "prior_improved_need_ids": list(self.prior_improved_need_ids),
        }


def decide_next_actionable_gap(
    gaps: tuple[TargetedResearchRequest, ...],
    *,
    gap_attempt_counts: dict[str, int],
    stalled_need_ids: set[str],
    max_attempts_per_gap: int,
    remaining_remediation_evidence_calls: int | None = None,
    prior_improved_need_ids: set[str] | None = None,
) -> GapSchedulerDecision:
    """Choose the next eligible gap using first-opportunity then repeat cohorts."""
    improved = tuple(sorted(prior_improved_need_ids or ()))
    stalled = tuple(sorted(stalled_need_ids))

    eligible: list[TargetedResearchRequest] = []
    for request in gaps:
        need_id = request.information_need_id
        if gap_attempt_counts.get(need_id, 0) >= max_attempts_per_gap:
            continue
        if need_id in stalled_need_ids:
            continue
        eligible.append(request)

    eligible.sort(key=_tie_break_key)
    first = [
        request
        for request in eligible
        if gap_attempt_counts.get(request.information_need_id, 0) == 0
    ]
    repeat = [
        request
        for request in eligible
        if gap_attempt_counts.get(request.information_need_id, 0) > 0
    ]

    if first:
        selected = first[0]
        cohort = COHORT_FIRST_OPPORTUNITY
        reason = COHORT_FIRST_OPPORTUNITY
    elif repeat:
        selected = repeat[0]
        cohort = COHORT_REPEAT_OPPORTUNITY
        reason = COHORT_REPEAT_OPPORTUNITY
    else:
        selected = None
        cohort = None
        reason = REASON_NONE_ELIGIBLE

    attempt_counts = {
        request.information_need_id: int(
            gap_attempt_counts.get(request.information_need_id, 0)
        )
        for request in eligible
    }
    return GapSchedulerDecision(
        selected=selected,
        eligible_need_ids=tuple(request.information_need_id for request in eligible),
        attempt_counts=attempt_counts,
        first_opportunity_need_ids=tuple(
            request.information_need_id for request in first
        ),
        repeat_opportunity_need_ids=tuple(
            request.information_need_id for request in repeat
        ),
        cohort=cohort,
        selection_reason=reason,
        tie_break_key=_tie_break_key(selected) if selected is not None else None,
        remaining_remediation_evidence_calls=remaining_remediation_evidence_calls,
        stalled_need_ids=stalled,
        prior_improved_need_ids=improved,
    )


def select_next_actionable_gap(
    gaps: tuple[TargetedResearchRequest, ...],
    *,
    gap_attempt_counts: dict[str, int],
    stalled_need_ids: set[str],
    max_attempts_per_gap: int,
) -> TargetedResearchRequest | None:
    """Pick the next eligible gap for the current round without starvation."""
    return decide_next_actionable_gap(
        gaps,
        gap_attempt_counts=gap_attempt_counts,
        stalled_need_ids=stalled_need_ids,
        max_attempts_per_gap=max_attempts_per_gap,
    ).selected
