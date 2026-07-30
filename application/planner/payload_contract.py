from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from application.exceptions.planner_parser_error import PlannerParserError
from application.parsers.planner_response_parser import PlannerResponseParser
from application.planner.executor_catalog import ExecutorCatalog
from application.structured_output.contracts import StructuredPayloadContract

PLANNER_PAYLOAD_VALIDATION_ERRORS = (
    PlannerParserError,
    ValueError,
    TypeError,
)


class PlannerPayloadContract(StructuredPayloadContract):
    """
    Validates that a parsed JSON object matches the Planner payload contract.
    """

    def __init__(
        self,
        executor_catalog: ExecutorCatalog,
        response_parser: PlannerResponseParser | None = None,
    ) -> None:
        self._executor_catalog = executor_catalog
        self._response_parser = response_parser or PlannerResponseParser()
        self._last_validation_error = ""

    @property
    def last_validation_error(self) -> str:
        return self._last_validation_error

    def accepts(
        self,
        payload: Mapping[str, Any],
    ) -> bool:
        self._last_validation_error = ""

        try:
            plan = self._response_parser.parse(payload)
            self._validate_executor_ids(plan)
            self._validate_dependency_graph(plan)
            return True
        except PLANNER_PAYLOAD_VALIDATION_ERRORS as exc:
            self._last_validation_error = str(exc)
            return False

    @staticmethod
    def _validate_dependency_graph(
        plan,
    ) -> None:
        task_dependencies: dict[str, tuple[str, ...]] = {}
        seen_task_ids: set[str] = set()

        for stage in plan.stages:
            for task in stage.tasks:
                task_id = task.id.strip()

                if not task_id:
                    raise PlannerParserError(
                        "Planner task has an empty id.",
                    )

                if task_id in seen_task_ids:
                    raise PlannerParserError(
                        f"Duplicate task id: '{task_id}'.",
                    )

                seen_task_ids.add(task_id)
                task_dependencies[task_id] = task.dependencies

        for task_id, dependencies in task_dependencies.items():
            for dependency_id in dependencies:
                if dependency_id == task_id:
                    raise PlannerParserError(
                        f"Task '{task_id}' cannot depend on itself.",
                    )

                if dependency_id not in task_dependencies:
                    raise PlannerParserError(
                        f"Task '{task_id}' depends on unknown task "
                        f"'{dependency_id}'.",
                    )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise PlannerParserError(
                    "Planner payload contains circular task dependencies.",
                )

            if task_id in visited:
                return

            visiting.add(task_id)

            for dependency_id in task_dependencies[task_id]:
                visit(dependency_id)

            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in task_dependencies:
            visit(task_id)

    def _validate_executor_ids(
        self,
        plan,
    ) -> None:
        allowed = ", ".join(self._executor_catalog.executor_ids)

        for stage in plan.stages:
            for task in stage.tasks:
                executor_id = task.executor_id.strip()

                if not executor_id:
                    raise PlannerParserError(
                        f"Task '{task.id}' has an empty executor_id.",
                    )

                if not self._executor_catalog.contains(executor_id):
                    raise PlannerParserError(
                        "Unknown executor_id "
                        f"'{executor_id}' for task '{task.id}'. "
                        f"Allowed executor IDs: {allowed}.",
                    )
