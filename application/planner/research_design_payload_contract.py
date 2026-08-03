from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from application.exceptions.planner_parser_error import PlannerParserError
from application.parsers.research_design_parser import ResearchDesignParser
from application.planner.planner_bounds import PlannerBounds
from application.structured_output.contracts import StructuredPayloadContract

PLANNER_PAYLOAD_VALIDATION_ERRORS = (
    PlannerParserError,
    ValueError,
    TypeError,
)


class ResearchDesignPayloadContract(StructuredPayloadContract):
    """Validates planner output matches the ResearchDesign JSON contract."""

    def __init__(
        self,
        response_parser: ResearchDesignParser | None = None,
        bounds: PlannerBounds | None = None,
    ) -> None:
        self._response_parser = response_parser or ResearchDesignParser()
        self._bounds = bounds or PlannerBounds.from_env()
        self._last_validation_error = ""

    @property
    def bounds(self) -> PlannerBounds:
        return self._bounds

    @property
    def last_validation_error(self) -> str:
        return self._last_validation_error

    def accepts(self, payload: Mapping[str, Any]) -> bool:
        self._last_validation_error = ""
        try:
            design = self._response_parser.parse(payload)
            self._validate_unique_ids(design)
            self._validate_question_references(design)
            self._validate_cardinality_bounds(design)
            return True
        except PLANNER_PAYLOAD_VALIDATION_ERRORS as exc:
            self._last_validation_error = str(exc)
            return False

    def _validate_cardinality_bounds(self, design) -> None:
        bounds = self._bounds
        checks = (
            (
                len(design.research_questions),
                bounds.max_research_questions,
                "research_questions",
                "Consolidate related brief objectives into fewer questions.",
            ),
            (
                len(design.information_needs),
                bounds.max_information_needs,
                "information_needs",
                "Reduce or merge information needs; keep descriptions concise.",
            ),
            (
                len(design.source_strategy),
                bounds.max_source_strategies,
                "source_strategy",
                "Keep only the highest-value source types.",
            ),
            (
                len(design.analysis_plan),
                bounds.max_analysis_plan_items,
                "analysis_plan",
                "Merge overlapping analysis steps.",
            ),
            (
                len(design.deliverable_plan),
                bounds.max_deliverable_plan_items,
                "deliverable_plan",
                "Align to essential deliverable sections only.",
            ),
            (
                len(design.assumptions),
                bounds.max_assumptions,
                "assumptions",
                "Keep only essential assumptions.",
            ),
            (
                len(design.limitations),
                bounds.max_limitations,
                "limitations",
                "Keep only essential limitations.",
            ),
        )
        for count, maximum, field_name, guidance in checks:
            if count > maximum:
                raise PlannerParserError(
                    f"{field_name} count {count} exceeds maximum {maximum}. "
                    f"{guidance}",
                )

    @staticmethod
    def _validate_unique_ids(design) -> None:
        question_ids: set[str] = set()
        for question in design.research_questions:
            if question.id in question_ids:
                raise PlannerParserError(
                    f"Duplicate research question id: '{question.id}'.",
                )
            question_ids.add(question.id)

        need_ids: set[str] = set()
        for need in design.information_needs:
            if need.id in need_ids:
                raise PlannerParserError(
                    f"Duplicate information need id: '{need.id}'.",
                )
            need_ids.add(need.id)

    @staticmethod
    def _validate_question_references(design) -> None:
        question_ids = {question.id for question in design.research_questions}
        for need in design.information_needs:
            if need.research_question_id not in question_ids:
                raise PlannerParserError(
                    f"InformationNeed '{need.id}' references unknown question "
                    f"'{need.research_question_id}'.",
                )
