"""Tests for ResearchDesign planner payload contract."""

from __future__ import annotations

import unittest

from application.planner.research_design_payload_contract import (
    ResearchDesignPayloadContract,
)
from application.structured_output.parser import StructuredOutputParser

from tests.fixtures.planner_responses import (
    INVALID_DUPLICATE_QUESTION_JSON,
    UNKNOWN_EXECUTOR_PLANNER_JSON,
    VALID_RESEARCH_DESIGN_JSON,
)


class ResearchDesignPayloadContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = ResearchDesignPayloadContract()
        self.parser = StructuredOutputParser()

    def test_accepts_valid_design(self) -> None:
        payload = self.parser.parse(VALID_RESEARCH_DESIGN_JSON)
        self.assertTrue(self.contract.accepts(payload))

    def test_rejects_empty_questions(self) -> None:
        payload = self.parser.parse(UNKNOWN_EXECUTOR_PLANNER_JSON)
        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("research_questions", self.contract.last_validation_error)

    def test_rejects_duplicate_question_ids(self) -> None:
        payload = self.parser.parse(INVALID_DUPLICATE_QUESTION_JSON)
        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("Duplicate research question id", self.contract.last_validation_error)

    def test_rejects_excessive_information_needs(self) -> None:
        payload = self.parser.parse(VALID_RESEARCH_DESIGN_JSON)
        design = dict(payload)
        design["information_needs"] = [
            {
                "id": f"in-{index}",
                "research_question_id": "rq-awareness",
                "description": f"Need {index}",
                "priority": 1,
                "preferred_source_types": ["reputable media"],
                "timeframe": "2025-2026",
                "geography": "Serbia",
            }
            for index in range(13)
        ]
        self.assertFalse(self.contract.accepts(design))
        self.assertIn("information_needs count", self.contract.last_validation_error)


if __name__ == "__main__":
    unittest.main()
