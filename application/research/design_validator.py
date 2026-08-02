from __future__ import annotations

from domain.common.exceptions import ValidationError
from domain.planning.research_design import ResearchDesign
from domain.research_brief import ResearchBrief, normalize_objective_text


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
        invalid_refs = find_invalid_objective_refs(brief, design)
        if invalid_refs:
            raise ValidationError(
                "ResearchQuestion objective_refs must match brief objectives: "
                + ", ".join(
                    f"{question_id} -> {ref!r}"
                    for question_id, ref in invalid_refs
                ),
            )
        uncovered = find_uncovered_objectives(brief, design)
        if uncovered:
            raise ValidationError(
                "ResearchDesign does not cover brief objectives: "
                + ", ".join(uncovered),
            )


def find_invalid_objective_refs(
    brief: ResearchBrief,
    design: ResearchDesign,
) -> tuple[tuple[str, str], ...]:
    """Refs that do not resolve to a brief objective after normalization."""
    if not brief.objectives:
        return ()

    valid = set(brief.normalized_objectives())
    invalid: list[tuple[str, str]] = []
    for question in design.research_questions:
        for ref in question.objective_refs:
            if normalize_objective_text(ref) not in valid:
                invalid.append((question.id, ref))
    return tuple(invalid)


def find_uncovered_objectives(
    brief: ResearchBrief,
    design: ResearchDesign,
) -> tuple[str, ...]:
    """Return brief objectives not referenced by any research question."""
    if not brief.objectives:
        return ()

    covered: set[str] = set()
    for question in design.research_questions:
        for ref in question.objective_refs:
            covered.add(normalize_objective_text(ref))

    uncovered: list[str] = []
    for objective in brief.objectives:
        if normalize_objective_text(objective) not in covered:
            uncovered.append(objective)
    return tuple(uncovered)


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
