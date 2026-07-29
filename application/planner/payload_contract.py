from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from application.parsers.planner_response_parser import PlannerResponseParser
from application.structured_output.contracts import StructuredPayloadContract


class PlannerPayloadContract(StructuredPayloadContract):
    """
    Validates that a parsed JSON object matches the Planner payload contract.
    """

    def __init__(
        self,
        response_parser: PlannerResponseParser | None = None,
    ) -> None:
        self._response_parser = response_parser or PlannerResponseParser()

    def accepts(
        self,
        payload: Mapping[str, Any],
    ) -> bool:
        try:
            self._response_parser.parse(payload)
            return True
        except Exception:
            return False
