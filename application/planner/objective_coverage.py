from __future__ import annotations

from dataclasses import dataclass

from domain.common.exceptions import ValidationError
from domain.planning.research_design import ResearchDesign
from domain.research_brief import ResearchBrief, normalize_objective_text


@dataclass(frozen=True)
class ObjectiveCoverageFailure:
    uncovered_objectives: tuple[str, ...]
    invalid_objective_refs: tuple[tuple[str, str], ...]

    @property
    def uncovered_objective_count(self) -> int:
        return len(self.uncovered_objectives)

    @property
    def is_correctable(self) -> bool:
        return bool(self.uncovered_objectives or self.invalid_objective_refs)


class ObjectiveCoverageValidationError(ValidationError):
    """Planner design failed brief objective traceability checks."""

    def __init__(
        self,
        message: str,
        *,
        uncovered_objectives: tuple[str, ...] = (),
        invalid_objective_refs: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(message)
        self.uncovered_objectives = uncovered_objectives
        self.invalid_objective_refs = invalid_objective_refs

    @classmethod
    def from_failure(cls, failure: ObjectiveCoverageFailure) -> ObjectiveCoverageValidationError:
        parts: list[str] = []
        if failure.uncovered_objectives:
            parts.append(
                "ResearchDesign does not cover brief objectives: "
                + ", ".join(failure.uncovered_objectives),
            )
        if failure.invalid_objective_refs:
            parts.append(
                "ResearchQuestion objective_refs must match brief objectives: "
                + ", ".join(
                    f"{question_id} -> {ref!r}"
                    for question_id, ref in failure.invalid_objective_refs
                ),
            )
        message = " ".join(parts) if parts else "Objective coverage validation failed."
        return cls(
            message,
            uncovered_objectives=failure.uncovered_objectives,
            invalid_objective_refs=failure.invalid_objective_refs,
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


def evaluate_objective_coverage(
    brief: ResearchBrief | None,
    design: ResearchDesign,
) -> ObjectiveCoverageFailure | None:
    if brief is None or not brief.objectives:
        return None

    uncovered = find_uncovered_objectives(brief, design)
    invalid_refs = find_invalid_objective_refs(brief, design)
    if not uncovered and not invalid_refs:
        return None

    return ObjectiveCoverageFailure(
        uncovered_objectives=uncovered,
        invalid_objective_refs=invalid_refs,
    )
