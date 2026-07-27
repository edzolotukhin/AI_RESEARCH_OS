"""
AI Research OS

Planner Response Parser.

Converts external planner responses into immutable DTO objects.

Responsibilities:
- validate the external contract;
- convert mappings into DTO objects;
- raise PlannerParserError on invalid input.

The parser never creates domain objects.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from application.dto.planner_plan_dto import PlannerPlanDTO
from application.dto.planner_task_dto import PlannerTaskDTO
from application.dto.research_stage_dto import ResearchStageDTO
from application.exceptions.planner_parser_error import PlannerParserError


class PlannerResponseParser:
    """Converts planner responses into PlannerPlanDTO."""

    def parse(
        self,
        response: Mapping[str, Any],
    ) -> PlannerPlanDTO:
        """
        Parse planner response into PlannerPlanDTO.

        Raises:
            PlannerParserError:
                If the response does not satisfy the required schema.
        """

        self._require_mapping(response, "response")

        try:
            name = self._require_string(response, "name")
            goal = self._require_string(response, "goal")

            methodology = self._optional_string(
                response,
                "methodology",
            )

            stages_data = self._require_sequence(
                response,
                "stages",
            )

            stages = tuple(
                self._parse_stage(stage)
                for stage in stages_data
            )

            metadata = response.get("metadata", {})

            if metadata is None:
                metadata = {}

            self._require_mapping(
                metadata,
                "metadata",
            )

            return PlannerPlanDTO(
                name=name,
                goal=goal,
                methodology=methodology,
                stages=stages,
                metadata=metadata,
            )

        except PlannerParserError:
            raise

        except Exception as exc:
            raise PlannerParserError(
                str(exc)
            ) from exc

    def _parse_stage(
        self,
        data: Mapping[str, Any],
    ) -> ResearchStageDTO:

        self._require_mapping(
            data,
            "stage",
        )

        stage_id = self._require_string(
            data,
            "id",
        )

        name = self._require_string(
            data,
            "name",
        )

        description = self._optional_string(
            data,
            "description",
        )

        tasks_data = self._require_sequence(
            data,
            "tasks",
        )

        tasks = tuple(
            self._parse_task(task)
            for task in tasks_data
        )

        return ResearchStageDTO(
            id=stage_id,
            name=name,
            description=description,
            tasks=tasks,
        )

    def _parse_task(
        self,
        data: Mapping[str, Any],
    ) -> PlannerTaskDTO:

        self._require_mapping(
            data,
            "task",
        )

        task_id = self._require_string(
            data,
            "id",
        )

        title = self._require_string(
            data,
            "title",
        )

        description = self._optional_string(
            data,
            "description",
        )

        suggested_agent = self._optional_string(
            data,
            "suggested_agent",
        )

        dependencies = self._optional_sequence(
            data,
            "dependencies",
        )

        dependency_ids = tuple(
            self._require_string_value(
                value,
                "dependency",
            )
            for value in dependencies
        )

        return PlannerTaskDTO(
            id=task_id,
            title=title,
            description=description,
            suggested_agent=suggested_agent,
            dependencies=dependency_ids,
        )

    @staticmethod
    def _require_mapping(
        value: Any,
        name: str,
    ) -> Mapping[str, Any]:

        if not isinstance(value, Mapping):
            raise PlannerParserError(
                f"'{name}' must be an object."
            )

        return value

    @staticmethod
    def _require_sequence(
        mapping: Mapping[str, Any],
        field: str,
    ) -> Sequence[Any]:
        """
        Return a required sequence field.

        Raises:
            PlannerParserError:
                If the field is missing or is not a sequence.
        """

        if field not in mapping:
            raise PlannerParserError(
                f"Missing required field '{field}'."
            )

        value = mapping[field]

        if (
            not isinstance(value, Sequence)
            or isinstance(value, (str, bytes))
        ):
            raise PlannerParserError(
                f"'{field}' must be a list."
            )

        return value

    @staticmethod
    def _optional_sequence(
        mapping: Mapping[str, Any],
        field: str,
    ) -> Sequence[Any]:

        value = mapping.get(field)

        if value is None:
            return ()

        if (
            not isinstance(value, Sequence)
            or isinstance(value, (str, bytes))
        ):
            raise PlannerParserError(
                f"'{field}' must be a list."
            )

        return value

    @staticmethod
    def _require_string(
        mapping: Mapping[str, Any],
        field: str,
    ) -> str:

        if field not in mapping:
            raise PlannerParserError(
                f"Missing required field '{field}'."
            )

        return PlannerResponseParser._require_string_value(
            mapping[field],
            field,
        )

    @staticmethod
    def _optional_string(
        mapping: Mapping[str, Any],
        field: str,
    ) -> str:

        value = mapping.get(field)

        if value is None:
            return ""

        return PlannerResponseParser._require_string_value(
            value,
            field,
        )

    @staticmethod
    def _require_string_value(
        value: Any,
        field: str,
    ) -> str:

        if not isinstance(value, str):
            raise PlannerParserError(
                f"'{field}' must be a string."
            )

        value = value.strip()

        if not value:
            raise PlannerParserError(
                f"'{field}' cannot be empty."
            )

        return value