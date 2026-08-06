from __future__ import annotations

from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.sufficiency_status import (
    ACTIONABLE_BLOCKING_STATUSES,
    SufficiencyStatus,
)

# Control-only ordering for improvement detection between readiness passes.
# Not a domain truth / confidence score.
STATUS_RANK: dict[SufficiencyStatus, int] = {
    SufficiencyStatus.MISSING: 0,
    SufficiencyStatus.INSUFFICIENT: 1,
    SufficiencyStatus.PARTIAL: 2,
    SufficiencyStatus.SUFFICIENT: 3,
}


def status_rank(status: SufficiencyStatus) -> int | None:
    if status == SufficiencyStatus.BLOCKED:
        return None
    return STATUS_RANK.get(status)


def readiness_improved(
    before: ResearchReadinessResult,
    after: ResearchReadinessResult,
) -> bool:
    if after.ready_for_analysis:
        return True
    before_by_need = _assessments_by_need(before)
    after_by_need = _assessments_by_need(after)
    before_blocking = _blocking_need_ids(before)
    after_blocking = _blocking_need_ids(after)
    if len(after_blocking) < len(before_blocking):
        return True
    for need_id in before_blocking:
        before_rank = status_rank(before_by_need[need_id].status)
        after_rank = status_rank(after_by_need[need_id].status)
        if before_rank is None or after_rank is None:
            continue
        if after_rank > before_rank:
            return True
    return False


def _assessments_by_need(
    result: ResearchReadinessResult,
) -> dict[str, InformationNeedAssessment]:
    mapped: dict[str, InformationNeedAssessment] = {}
    for rq in result.research_question_assessments:
        for assessment in rq.information_need_assessments:
            mapped[assessment.information_need_id] = assessment
    return mapped


def need_readiness_improved(
    before: ResearchReadinessResult,
    after: ResearchReadinessResult,
    information_need_id: str,
) -> bool:
    if after.ready_for_analysis:
        return True
    before_by_need = _assessments_by_need(before)
    after_by_need = _assessments_by_need(after)
    if information_need_id not in before_by_need or information_need_id not in after_by_need:
        return readiness_improved(before, after)
    before_rank = status_rank(before_by_need[information_need_id].status)
    after_rank = status_rank(after_by_need[information_need_id].status)
    if before_rank is None or after_rank is None:
        return False
    return after_rank > before_rank


def blocking_need_ids(result: ResearchReadinessResult) -> tuple[str, ...]:
    return _blocking_need_ids(result)


def _blocking_need_ids(result: ResearchReadinessResult) -> tuple[str, ...]:
    ids: list[str] = []
    for rq in result.research_question_assessments:
        for assessment in rq.information_need_assessments:
            if assessment.status in ACTIONABLE_BLOCKING_STATUSES:
                ids.append(assessment.information_need_id)
    return tuple(sorted(ids))
