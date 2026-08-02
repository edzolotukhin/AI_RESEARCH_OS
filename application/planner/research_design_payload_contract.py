from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from application.exceptions.planner_parser_error import PlannerParserError
from application.parsers.research_design_parser import ResearchDesignParser
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
    ) -> None:
        self._response_parser = response_parser or ResearchDesignParser()
        self._last_validation_error = ""

    @property
    def last_validation_error(self) -> str:
        return self._last_validation_error

    def accepts(self, payload: Mapping[str, Any]) -> bool:
        self._last_validation_error = ""
        try:
            design = self._response_parser.parse(payload)
            self._validate_unique_ids(design)
            self._validate_question_references(design)
            return True
        except PLANNER_PAYLOAD_VALIDATION_ERRORS as exc:
            self._last_validation_error = str(exc)
            return False

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
