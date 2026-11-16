"""Tests for domain ResearchDesign models."""

from __future__ import annotations

import unittest

from domain.planning.research_design import (
    EvidenceCoverageContract,
    InformationNeed,
    ResearchDesign,
    ResearchQuestion,
    TemporalGranularity,
)
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature

from tests.fixtures.planner_responses import VALID_RESEARCH_DESIGN_RESPONSE


class ResearchDesignModelTests(unittest.TestCase):
    @staticmethod
    def numeric_need(coverage: EvidenceCoverageContract) -> InformationNeed:
        return InformationNeed(
            id="in-population",
            research_question_id="rq-awareness",
            description="Population",
            evidence_expectation=EvidenceExpectation(
                nature=EvidenceNature.QUANTITATIVE,
                requires_quantitative_evidence=True,
            ),
            evidence_coverage=coverage,
        )

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

    def test_explicit_evidence_coverage_round_trip(self) -> None:
        need = InformationNeed(
            id="in-quarterly",
            research_question_id="rq-awareness",
            description="Quarterly retail trend",
            evidence_coverage=EvidenceCoverageContract(
                temporal_granularity=TemporalGranularity.QUARTERLY,
                required_periods=("2025-Q1", "2025-Q2"),
                required_observations=("turnover",),
                required_metric="retail turnover",
                required_authority_kinds=("official_retail",),
                minimum_independent_sources=2,
                geography="UA",
                eligible_source_types=("official_statistics",),
                prohibited_source_patterns=("cpi_only",),
            ),
        )
        restored = InformationNeed.from_dict(need.to_dict())
        self.assertEqual(restored, need)

    def test_legacy_information_need_has_no_invented_granularity(self) -> None:
        need = InformationNeed.from_dict({
            "id": "legacy",
            "research_question_id": "rq-awareness",
            "description": "Quarterly trend mentioned in prose",
            "timeframe": "2021-2026",
        })
        self.assertIsNone(need.evidence_coverage)

    def test_quarterly_contract_rejects_non_quarter_periods(self) -> None:
        with self.assertRaisesRegex(ValueError, "YYYY-QN"):
            EvidenceCoverageContract(
                temporal_granularity=TemporalGranularity.QUARTERLY,
                required_periods=("2025",),
            )

    def test_numeric_contract_requires_explicit_authoritative_unit(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit required_unit"):
            self.numeric_need(EvidenceCoverageContract(
                required_metric="Population",
                required_periods=("2020",),
                geography="Ukraine",
            ))

    def test_numeric_contract_unit_is_normalized_and_round_trips(self) -> None:
        need = self.numeric_need(EvidenceCoverageContract(
            required_metric="Population",
            required_unit="  thousand   persons ",
            required_periods=("2020",),
            geography="Ukraine",
        ))
        self.assertEqual(need.evidence_coverage.required_unit, "thousand persons")
        payload = need.to_dict()
        self.assertEqual(payload["evidence_coverage"]["required_unit"], "thousand persons")
        self.assertEqual(InformationNeed.from_dict(payload), need)

    def test_legacy_numeric_payload_without_unit_remains_loadable_but_incomplete(self) -> None:
        payload = {
            "id": "legacy-numeric",
            "research_question_id": "rq-awareness",
            "description": "Population",
            "evidence_expectation": {
                "nature": "quantitative",
                "requires_quantitative_evidence": True,
            },
            "evidence_coverage": {
                "required_metric": "Population",
                "required_periods": ["2020"],
                "geography": "Ukraine",
            },
        }
        restored = InformationNeed.from_dict(payload)
        self.assertEqual(restored.evidence_coverage.required_unit, "")
        normalized = restored.to_dict()
        self.assertNotIn("required_unit", normalized["evidence_coverage"])
        self.assertEqual(InformationNeed.from_dict(normalized).to_dict(), normalized)

    def test_nonnumeric_contract_does_not_require_unit(self) -> None:
        need = InformationNeed(
            id="in-methodology", research_question_id="rq-awareness",
            description="Methodology",
            evidence_expectation=EvidenceExpectation(EvidenceNature.QUALITATIVE),
            evidence_coverage=EvidenceCoverageContract(
                required_observations=("methodology",),
            ),
        )
        self.assertEqual(need.evidence_coverage.required_unit, "")
        self.assertNotIn("required_unit", need.to_dict()["evidence_coverage"])

    def test_invalid_unit_is_rejected(self) -> None:
        for invalid in (42, "x" * 201):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                EvidenceCoverageContract(required_unit=invalid)


if __name__ == "__main__":
    unittest.main()
