"""Tests for domain ResearchDesign models."""

from __future__ import annotations

import unittest

from domain.planning.research_design import (
    InformationNeed,
    ResearchDesign,
    ResearchQuestion,
)

from tests.fixtures.planner_responses import VALID_RESEARCH_DESIGN_RESPONSE


class ResearchDesignModelTests(unittest.TestCase):
    def test_from_dict_round_trip(self) -> None:
        design = ResearchDesign.from_dict(
            {"id": "design-1", **VALID_RESEARCH_DESIGN_RESPONSE},
        )
        self.assertIsNotNone(design)
        assert design is not None
        restored = ResearchDesign.from_dict(design.to_dict())
        assert restored is not None
        self.assertEqual(len(restored.research_questions), 2)
        self.assertEqual(restored.research_questions[0].id, "rq-awareness")
        self.assertEqual(len(restored.information_needs), 2)

    def test_question_fields_preserved(self) -> None:
        question = ResearchQuestion.from_dict(
            VALID_RESEARCH_DESIGN_RESPONSE["research_questions"][0],
        )
        self.assertEqual(question.objective_refs, ("Evaluate brand awareness.",))
        self.assertEqual(question.priority, 1)

    def test_information_need_fields_preserved(self) -> None:
        need = InformationNeed.from_dict(
            VALID_RESEARCH_DESIGN_RESPONSE["information_needs"][0],
        )
        self.assertEqual(need.research_question_id, "rq-awareness")
        self.assertIn("official statistics", need.preferred_source_types)


if __name__ == "__main__":
    unittest.main()
