"""Tests for ResearchDesign semantic validation."""

from __future__ import annotations

import unittest

from domain.common.exceptions import ValidationError
from domain.planning.research_design import ResearchDesign, ResearchQuestion

from application.planner.objective_coverage import ObjectiveCoverageValidationError
from application.research.design_validator import (
    find_orphan_questions,
    find_uncovered_objectives,
    validate_research_design,
)

from tests.fixtures.research_brief import sample_research_brief


def _sample_design(**overrides) -> ResearchDesign:
    payload = {
        "id": "design-1",
        "research_questions": [
            {
                "id": "rq-1",
                "question": "What is brand awareness?",
                "objective_refs": ["Evaluate brand awareness."],
                "priority": 1,
                "rationale": "Core metric.",
            },
        ],
        "information_needs": [
            {
                "id": "in-1",
                "research_question_id": "rq-1",
                "description": "Published awareness statistics.",
                "priority": 1,
                "preferred_source_types": ["official statistics"],
                "timeframe": "2026",
                "geography": "Germany",
            },
        ],
        "source_strategy": ["official statistics"],
        "analysis_plan": ["brand awareness benchmarking"],
        "deliverable_plan": ["executive summary"],
        "language": "en",
    }
    payload.update(overrides)
    design = ResearchDesign.from_dict(payload)
    assert design is not None
    return design


class ResearchDesignValidatorTests(unittest.TestCase):
    def test_valid_design_passes(self) -> None:
        brief = sample_research_brief()
        validate_research_design(_sample_design(), brief=brief)

    def test_empty_questions_rejected(self) -> None:
        design = _sample_design(research_questions=[])
        with self.assertRaises(ValidationError):
            validate_research_design(design)

    def test_duplicate_question_ids_rejected(self) -> None:
        design = _sample_design(
            research_questions=[
                {
                    "id": "rq-dup",
                    "question": "Question one?",
                    "objective_refs": ["Evaluate brand awareness."],
                    "priority": 1,
                },
                {
                    "id": "rq-dup",
                    "question": "Question two?",
                    "objective_refs": ["Evaluate brand awareness."],
                    "priority": 2,
                },
            ],
        )
        with self.assertRaises(ValidationError):
            validate_research_design(design)

    def test_duplicate_normalized_questions_rejected(self) -> None:
        design = _sample_design(
            research_questions=[
                {
                    "id": "rq-1",
                    "question": "What is market size?",
                    "objective_refs": ["Evaluate brand awareness."],
                    "priority": 1,
                },
                {
                    "id": "rq-2",
                    "question": "  what   is  market  size? ",
                    "objective_refs": ["Evaluate brand awareness."],
                    "priority": 2,
                },
            ],
        )
        with self.assertRaises(ValidationError):
            validate_research_design(design)

    def test_uncovered_objectives_detected(self) -> None:
        brief = sample_research_brief(
            objectives=["Evaluate brand awareness.", "Identify competitors."],
        )
        design = _sample_design()
        uncovered = find_uncovered_objectives(brief, design)
        self.assertIn("Identify competitors.", uncovered)

    def test_uncovered_objectives_fail_validation(self) -> None:
        brief = sample_research_brief(
            objectives=["Evaluate brand awareness.", "Identify competitors."],
        )
        with self.assertRaises(ObjectiveCoverageValidationError):
            validate_research_design(_sample_design(), brief=brief)

    def test_orphan_questions_visible(self) -> None:
        brief = sample_research_brief()
        design = _sample_design(
            research_questions=[
                {
                    "id": "rq-orphan",
                    "question": "Unlinked question?",
                    "objective_refs": [],
                    "priority": 1,
                },
            ],
            information_needs=[],
        )
        orphans = find_orphan_questions(brief, design)
        self.assertEqual(orphans, ("rq-orphan",))

    def test_information_need_unknown_question_rejected(self) -> None:
        design = _sample_design(
            information_needs=[
                {
                    "id": "in-bad",
                    "research_question_id": "missing-rq",
                    "description": "Data.",
                    "priority": 1,
                },
            ],
        )
        with self.assertRaises(ValidationError):
            validate_research_design(design)

    def test_invalid_objective_refs_rejected(self) -> None:
        brief = sample_research_brief()
        design = _sample_design(
            research_questions=[
                {
                    "id": "rq-bad",
                    "question": "What is awareness?",
                    "objective_refs": ["Nonexistent objective."],
                    "priority": 1,
                },
            ],
            information_needs=[],
        )
        with self.assertRaises(ObjectiveCoverageValidationError):
            validate_research_design(design, brief=brief)


if __name__ == "__main__":
    unittest.main()
