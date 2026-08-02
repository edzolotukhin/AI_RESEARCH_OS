from __future__ import annotations

from uuid import uuid4

from application.dto.research_design_dto import ResearchDesignDTO
from domain.planning.research_design import (
    InformationNeed,
    ResearchDesign,
    ResearchQuestion,
)


class ResearchDesignFactory:
    """Creates ResearchDesign value objects from validated DTOs."""

    def create(self, dto: ResearchDesignDTO) -> ResearchDesign:
        return ResearchDesign(
            id=str(uuid4()),
            research_questions=tuple(
                self._create_question(item) for item in dto.research_questions
            ),
            information_needs=tuple(
                self._create_need(item) for item in dto.information_needs
            ),
            source_strategy=dto.source_strategy,
            analysis_plan=dto.analysis_plan,
            deliverable_plan=dto.deliverable_plan,
            assumptions=dto.assumptions,
            limitations=dto.limitations,
            language=dto.language,
        )

    @staticmethod
    def _create_question(dto) -> ResearchQuestion:
        return ResearchQuestion(
            id=dto.id,
            question=dto.question,
            objective_refs=dto.objective_refs,
            priority=dto.priority,
            rationale=dto.rationale,
        )

    @staticmethod
    def _create_need(dto) -> InformationNeed:
        return InformationNeed(
            id=dto.id,
            research_question_id=dto.research_question_id,
            description=dto.description,
            priority=dto.priority,
            preferred_source_types=dto.preferred_source_types,
            timeframe=dto.timeframe,
            geography=dto.geography,
        )
