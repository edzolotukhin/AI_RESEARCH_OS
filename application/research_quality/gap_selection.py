from __future__ import annotations

from domain.planning.research_design import ResearchDesign
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.sufficiency_status import ACTIONABLE_BLOCKING_STATUSES
from domain.research_quality.targeted_research_request import TargetedResearchRequest

from application.research_quality.bounded_search_directives import (
    bound_targeted_search_directives,
)


def select_actionable_gaps(
    *,
    result: ResearchReadinessResult,
    design: ResearchDesign,
    workflow_run_id: str,
    attempt: int,
    existing_source_ids: tuple[str, ...],
    existing_evidence_ids: tuple[str, ...],
) -> tuple[TargetedResearchRequest, ...]:
    """Deterministically select actionable blocking gaps for targeted research."""
    known_rq_ids = {question.id for question in design.research_questions}
    known_need_ids = {need.id for need in design.information_needs}
    need_by_id = {need.id: need for need in design.information_needs}

    actionable: list[InformationNeedAssessment] = []
    for rq_assessment in result.research_question_assessments:
        if rq_assessment.research_question_id not in known_rq_ids:
            continue
        for assessment in rq_assessment.information_need_assessments:
            if assessment.information_need_id not in known_need_ids:
                continue
            if assessment.status not in ACTIONABLE_BLOCKING_STATUSES:
                continue
            if assessment.research_question_id != rq_assessment.research_question_id:
                continue
            actionable.append(assessment)

    actionable.sort(key=lambda item: (item.research_question_id, item.information_need_id))

    requests: list[TargetedResearchRequest] = []
    for assessment in actionable:
        need = need_by_id[assessment.information_need_id]
        if need.research_question_id != assessment.research_question_id:
            continue
        requests.append(
            TargetedResearchRequest(
                workflow_run_id=workflow_run_id,
                research_design_id=design.id,
                research_question_id=assessment.research_question_id,
                information_need_id=assessment.information_need_id,
                gap_types=assessment.gap_types or (GapType.NO_EVIDENCE,),
                missing_aspects=assessment.missing_aspects,
                search_directives=bound_targeted_search_directives(
                    assessment.search_directives,
                ),
                attempt=attempt,
                existing_source_ids=existing_source_ids,
                existing_evidence_ids=existing_evidence_ids,
            ),
        )
    return tuple(requests)
