from __future__ import annotations

from domain.common.exceptions import ValidationError
from domain.planning.research_design import ResearchDesign
from domain.research_brief import ResearchBrief, normalize_objective_text

from application.planner.objective_coverage import (
    ObjectiveCoverageValidationError,
    evaluate_objective_coverage,
    find_invalid_objective_refs,
    find_uncovered_objectives,
)


def validate_research_design(
    design: ResearchDesign,
    *,
    brief: ResearchBrief | None = None,
) -> None:
    """Semantic validation for desk research design."""
    if not design.research_questions:
        raise ValidationError(
            "ResearchDesign must contain at least one research question.",
        )

    question_ids: set[str] = set()
    normalized_questions: set[str] = set()
    for question in design.research_questions:
        if not question.question.strip():
            raise ValidationError(
                f"ResearchQuestion '{question.id}' must have non-empty text.",
            )
        if question.id in question_ids:
            raise ValidationError(
                f"Duplicate research question id: '{question.id}'.",
            )
        question_ids.add(question.id)

        normalized = normalize_objective_text(question.question)
        if normalized in normalized_questions:
            raise ValidationError(
                f"Duplicate research question after normalization: "
                f"'{question.question}'.",
            )
        normalized_questions.add(normalized)

        if question.priority < 1 or question.priority > 5:
            raise ValidationError(
                f"ResearchQuestion '{question.id}' priority must be 1-5.",
            )

    need_ids: set[str] = set()
    for need in design.information_needs:
        if need.id in need_ids:
            raise ValidationError(
                f"Duplicate information need id: '{need.id}'.",
            )
        need_ids.add(need.id)
        if need.research_question_id not in question_ids:
            raise ValidationError(
                f"InformationNeed '{need.id}' references unknown question "
                f"'{need.research_question_id}'.",
            )
        if not need.description.strip():
            raise ValidationError(
                f"InformationNeed '{need.id}' must have a description.",
            )

    if not design.source_strategy:
        raise ValidationError("ResearchDesign.source_strategy must not be empty.")

    if not design.analysis_plan:
        raise ValidationError("ResearchDesign.analysis_plan must not be empty.")

    if not design.deliverable_plan:
        raise ValidationError("ResearchDesign.deliverable_plan must not be empty.")

    if brief is not None:
        failure = evaluate_objective_coverage(brief, design)
        if failure is not None:
            raise ObjectiveCoverageValidationError.from_failure(failure)


# Re-export objective traceability helpers for existing imports.
__all__ = [
    "find_invalid_objective_refs",
    "find_orphan_questions",
    "find_uncovered_objectives",
    "validate_research_design",
]


def find_orphan_questions(
    brief: ResearchBrief,
    design: ResearchDesign,
) -> tuple[str, ...]:
    """Questions with no objective_refs when brief has objectives."""
    if not brief.objectives:
        return ()
    return tuple(
        question.id
        for question in design.research_questions
        if not question.objective_refs
    )
