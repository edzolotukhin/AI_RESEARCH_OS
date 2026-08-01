from __future__ import annotations

import unittest

from application.research.brief_normalizer import normalize_research_brief_payload
from application.research.brief_validator import validate_research_brief
from domain.common.exceptions import ValidationError
from domain.research_brief import ResearchBrief
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST, LEGACY_BRIEF_REQUEST


class ResearchBriefDomainTests(unittest.TestCase):
    def test_valid_research_brief_creation(self) -> None:
        brief = normalize_research_brief_payload(CANONICAL_BRIEF_REQUEST)
        validate_research_brief(brief)
        self.assertEqual(brief.title, "Brand Health 2026")

    def test_required_field_validation(self) -> None:
        with self.assertRaises(ValidationError):
            validate_research_brief(
                ResearchBrief(title="", business_question="Q", objectives=("A",)),
            )

    def test_list_normalization(self) -> None:
        brief = normalize_research_brief_payload(
            {
                **CANONICAL_BRIEF_REQUEST,
                "objectives": ["  first ", "first", "", "second"],
            },
        )
        self.assertEqual(brief.objectives, ("first", "second"))

    def test_round_trip_equality(self) -> None:
        brief = normalize_research_brief_payload(CANONICAL_BRIEF_REQUEST)
        restored = ResearchBrief.from_dict(brief.to_dict())
        self.assertEqual(restored, brief)

    def test_legacy_payload_maps_to_canonical(self) -> None:
        brief = ResearchBrief.from_dict(LEGACY_BRIEF_REQUEST)
        self.assertEqual(brief.title, "Brand Health 2026")
        self.assertEqual(brief.business_question, "Assess market position.")
        self.assertEqual(brief.objectives, ("Evaluate brand awareness.",))


if __name__ == "__main__":
    unittest.main()
