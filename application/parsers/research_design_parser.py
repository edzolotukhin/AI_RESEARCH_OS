from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from application.dto.research_design_dto import (
    InformationNeedDTO,
    ResearchDesignDTO,
    ResearchQuestionDTO,
)
from application.exceptions.planner_parser_error import PlannerParserError


class ResearchDesignParser:
    """Parses planner ResearchDesign JSON into DTOs."""

    def parse(self, response: Mapping[str, Any]) -> ResearchDesignDTO:
        self._require_mapping(response, "response")

        try:
            questions_data = self._require_sequence(
                response,
                "research_questions",
            )
            questions = tuple(
                self._parse_question(item) for item in questions_data
            )

            needs_data = self._optional_sequence(
                response,
                "information_needs",
            )
            needs = tuple(self._parse_need(item) for item in needs_data)

            return ResearchDesignDTO(
                research_questions=questions,
                information_needs=needs,
                source_strategy=self._optional_string_list(
                    response,
                    "source_strategy",
                ),
                analysis_plan=self._optional_string_list(
                    response,
                    "analysis_plan",
                ),
                deliverable_plan=self._optional_string_list(
                    response,
                    "deliverable_plan",
                ),
                assumptions=self._optional_string_list(
                    response,
                    "assumptions",
                ),
                limitations=self._optional_string_list(
                    response,
                    "limitations",
                ),
                language=self._optional_string(response, "language") or "en",
            )
        except PlannerParserError:
            raise
        except Exception as exc:
            raise PlannerParserError(str(exc)) from exc

    def _parse_question(self, data: Mapping[str, Any]) -> ResearchQuestionDTO:
        self._require_mapping(data, "research_question")
        return ResearchQuestionDTO(
            id=self._require_string(data, "id"),
            question=self._require_string(data, "question"),
            objective_refs=self._optional_string_list(data, "objective_refs"),
            priority=self._optional_int(data, "priority", default=1),
            rationale=self._optional_string(data, "rationale"),
        )

    def _parse_need(self, data: Mapping[str, Any]) -> InformationNeedDTO:
        self._require_mapping(data, "information_need")
        return InformationNeedDTO(
            id=self._require_string(data, "id"),
            research_question_id=self._require_string(
                data,
                "research_question_id",
            ),
            description=self._require_string(data, "description"),
            priority=self._optional_int(data, "priority", default=1),
            preferred_source_types=self._optional_string_list(
                data,
                "preferred_source_types",
            ),
            timeframe=self._optional_string(data, "timeframe"),
            geography=self._optional_string(data, "geography"),
        )

    @staticmethod
    def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise PlannerParserError(f"'{name}' must be an object.")
        return value

    @staticmethod
    def _require_sequence(
        mapping: Mapping[str, Any],
        field: str,
    ) -> Sequence[Any]:
        if field not in mapping:
            raise PlannerParserError(f"Missing required field '{field}'.")
        value = mapping[field]
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise PlannerParserError(f"'{field}' must be a list.")
        if not value:
            raise PlannerParserError(f"'{field}' must not be empty.")
        return value

    @staticmethod
    def _optional_sequence(
        mapping: Mapping[str, Any],
        field: str,
    ) -> Sequence[Any]:
        value = mapping.get(field)
        if value is None:
            return ()
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise PlannerParserError(f"'{field}' must be a list.")
        return value

    @staticmethod
    def _require_string(mapping: Mapping[str, Any], field: str) -> str:
        if field not in mapping:
            raise PlannerParserError(f"Missing required field '{field}'.")
        return ResearchDesignParser._require_non_empty_string(
            mapping,
            field,
        )

    @staticmethod
    def _optional_string(mapping: Mapping[str, Any], field: str) -> str:
        value = mapping.get(field)
        if value is None:
            return ""
        return ResearchDesignParser._require_string_value(value, field)

    @staticmethod
    def _require_string_value(value: Any, field: str) -> str:
        if not isinstance(value, str):
            raise PlannerParserError(f"'{field}' must be a string.")
        return value.strip()

    @staticmethod
    def _require_non_empty_string(mapping: Mapping[str, Any], field: str) -> str:
        value = ResearchDesignParser._require_string_value(
            mapping[field],
            field,
        )
        if not value:
            raise PlannerParserError(f"'{field}' cannot be empty.")
        return value

    @staticmethod
    def _optional_string_list(
        mapping: Mapping[str, Any],
        field: str,
    ) -> tuple[str, ...]:
        value = mapping.get(field)
        if value is None:
            return ()
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise PlannerParserError(f"'{field}' must be a list.")
        items: list[str] = []
        for item in value:
            text = ResearchDesignParser._require_string_value(item, field)
            if text:
                items.append(text)
        return tuple(items)

    @staticmethod
    def _optional_int(
        mapping: Mapping[str, Any],
        field: str,
        *,
        default: int,
    ) -> int:
        value = mapping.get(field, default)
        if not isinstance(value, int):
            raise PlannerParserError(f"'{field}' must be an integer.")
        if value < 1 or value > 5:
            raise PlannerParserError(
                f"'{field}' must be between 1 and 5.",
            )
        return value
