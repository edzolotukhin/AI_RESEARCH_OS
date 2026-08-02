from __future__ import annotations

from domain.planning.research_design import (
    InformationNeed,
    ResearchDesign,
    ResearchQuestion,
)

from api.schemas.workflow_runs import (
    InformationNeedResponse,
    ResearchDesignResponse,
    ResearchQuestionResponse,
)


def research_design_to_response(
    design: ResearchDesign | None,
) -> ResearchDesignResponse | None:
    if design is None:
        return None
    return ResearchDesignResponse(
        id=design.id,
        research_questions=[
            _question_to_response(question)
            for question in design.research_questions
        ],
        information_needs=[
            _need_to_response(need) for need in design.information_needs
        ],
        source_strategy=list(design.source_strategy),
        analysis_plan=list(design.analysis_plan),
        deliverable_plan=list(design.deliverable_plan),
        assumptions=list(design.assumptions),
        limitations=list(design.limitations),
        language=design.language,
    )


def _question_to_response(question: ResearchQuestion) -> ResearchQuestionResponse:
    return ResearchQuestionResponse(
        id=question.id,
        question=question.question,
        objective_refs=list(question.objective_refs),
        priority=question.priority,
        rationale=question.rationale,
    )


def _need_to_response(need: InformationNeed) -> InformationNeedResponse:
    return InformationNeedResponse(
        id=need.id,
        research_question_id=need.research_question_id,
        description=need.description,
        priority=need.priority,
        preferred_source_types=list(need.preferred_source_types),
        timeframe=need.timeframe,
        geography=need.geography,
    )
