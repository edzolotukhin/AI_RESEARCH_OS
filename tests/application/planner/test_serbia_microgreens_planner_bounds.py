"""Serbia Microgreens live-acceptance planner bounds regression tests."""

from __future__ import annotations

import json
import unittest

from application.factories.research_design_factory import ResearchDesignFactory
from application.parsers.research_design_parser import ResearchDesignParser
from application.planner.design_service import PlannerDesignServiceImpl
from application.planner.planner_bounds import PlannerBounds
from application.planner.research_design_payload_contract import (
    ResearchDesignPayloadContract,
)
from application.research.design_validator import find_uncovered_objectives
from application.structured_output.parser import StructuredOutputParser

from domain.project import Project

from tests.fixtures.serbia_bounded_research_design import (
    SERBIA_BOUNDED_RESEARCH_DESIGN,
    SERBIA_BOUNDED_RESEARCH_DESIGN_JSON,
)
from tests.fixtures.serbia_microgreens_brief import serbia_microgreens_brief


class SerbiaMicrogreensPlannerBoundsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bounds = PlannerBounds()
        self.contract = ResearchDesignPayloadContract(bounds=self.bounds)
        self.parser = StructuredOutputParser()
        self.design_service = PlannerDesignServiceImpl(
            response_parser=ResearchDesignParser(),
            design_factory=ResearchDesignFactory(),
        )
        self.project = Project(
            id="project-serbia",
            name="Serbia Microgreens",
            research_brief=serbia_microgreens_brief(),
        )

    def test_bounded_design_passes_contract_validation(self) -> None:
        payload = self.parser.parse(SERBIA_BOUNDED_RESEARCH_DESIGN_JSON)
        self.assertTrue(self.contract.accepts(payload))

    def test_bounded_design_passes_semantic_validation(self) -> None:
        design = self.design_service.create_design(
            self.project,
            SERBIA_BOUNDED_RESEARCH_DESIGN,
        )
        self.assertEqual(len(design.research_questions), 6)
        self.assertLessEqual(len(design.information_needs), self.bounds.max_information_needs)

    def test_all_brief_objectives_are_covered(self) -> None:
        design = self.design_service.create_design(
            self.project,
            SERBIA_BOUNDED_RESEARCH_DESIGN,
        )
        uncovered = find_uncovered_objectives(self.project.research_brief, design)
        self.assertEqual(uncovered, ())

    def test_bounded_json_fits_within_output_budget(self) -> None:
        encoded = json.dumps(SERBIA_BOUNDED_RESEARCH_DESIGN, ensure_ascii=True)
        # Conservative char budget well below typical 4096-token planner ceiling.
        self.assertLess(len(encoded), 6000)

    def test_contract_rejects_excessive_question_count(self) -> None:
        payload = dict(SERBIA_BOUNDED_RESEARCH_DESIGN)
        payload["research_questions"] = [
            *payload["research_questions"],
            {
                "id": "rq-extra",
                "question": "Extra question?",
                "objective_refs": [self.project.research_brief.objectives[0]],
                "priority": 5,
                "rationale": "Overflow.",
            },
        ]
        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("research_questions count", self.contract.last_validation_error)
        self.assertIn("Consolidate", self.contract.last_validation_error)


if __name__ == "__main__":
    unittest.main()
