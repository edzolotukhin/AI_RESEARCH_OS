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
            return True
        except PLANNER_PAYLOAD_VALIDATION_ERRORS as exc:
            self._last_validation_error = str(exc)
            return False

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
