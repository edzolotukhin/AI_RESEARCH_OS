"""Cross-field consistency tests for semantic sufficiency structured output."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from application.exceptions.structured_output_error import StructuredOutputError
from application.execution.execution_budget_retry import consume_llm_call_retry_flag
from application.research_quality.exceptions import SemanticSufficiencyAssessmentError
from application.research_quality.readiness_aggregation import (
    build_information_need_assessment,
)
from application.research_quality.semantic_sufficiency_contract import (
    semantic_sufficiency_payload_contract,
)
from domain.ai.llm_response import LLMResponse
from domain.common.exceptions import ValidationError
from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchQuestion
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.gap_type import GapType
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus

from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
    LlmSemanticSufficiencyAssessor,
)


def _valid_sufficient_payload() -> dict[str, object]:
    return {
        "status": "sufficient",
        "missing_aspects": [],
        "gap_types": [],
        "search_directives": [],
        "confidence": 0.9,
        "reason": "Evidence substantively answers the information need.",
    }


def _signals(*, evidence_count: int = 2) -> DeterministicSufficiencySignals:
    return DeterministicSufficiencySignals(
        information_need_id="in-1",
        research_question_id="rq-1",
        evidence_count=evidence_count,
        independent_source_count=evidence_count,
        evidence_ids=tuple(f"evidence-{index}" for index in range(evidence_count)),
        source_ids=tuple(f"source-{index}" for index in range(evidence_count)),
        deterministic_gap_types=(),
    )


class SemanticSufficiencyContractConsistencyTests(unittest.TestCase):
    def test_sufficient_with_insufficient_depth_is_rejected(self) -> None:
        payload = {
            **_valid_sufficient_payload(),
            "gap_types": ["insufficient_depth"],
        }
        self.assertFalse(semantic_sufficiency_payload_contract(payload))

    def test_sufficient_with_insufficient_diversity_is_rejected(self) -> None:
        payload = {
            **_valid_sufficient_payload(),
            "gap_types": ["insufficient_diversity"],
        }
        self.assertFalse(semantic_sufficiency_payload_contract(payload))

    def test_sufficient_with_no_evidence_is_rejected(self) -> None:
        payload = {
            **_valid_sufficient_payload(),
            "gap_types": ["no_evidence"],
        }
        self.assertFalse(semantic_sufficiency_payload_contract(payload))

    def test_sufficient_with_missing_aspects_is_rejected(self) -> None:
        payload = {
            **_valid_sufficient_payload(),
            "missing_aspects": ["recent figures"],
        }
        self.assertFalse(semantic_sufficiency_payload_contract(payload))

    def test_sufficient_with_search_directives_is_rejected(self) -> None:
        payload = {
            **_valid_sufficient_payload(),
            "search_directives": ["Find 2025 data"],
        }
        self.assertFalse(semantic_sufficiency_payload_contract(payload))

    def test_sufficient_valid_payload_is_accepted(self) -> None:
        self.assertTrue(semantic_sufficiency_payload_contract(_valid_sufficient_payload()))

    def test_partial_with_blocking_gap_is_accepted(self) -> None:
        payload = {
            "status": "partial",
            "missing_aspects": ["recent data"],
            "gap_types": ["insufficient_depth"],
            "search_directives": ["Find 2025 figures"],
            "confidence": 0.6,
            "reason": "Depth is insufficient.",
        }
        self.assertTrue(semantic_sufficiency_payload_contract(payload))

    def test_insufficient_with_blocking_gap_is_accepted(self) -> None:
        payload = {
            "status": "insufficient",
            "missing_aspects": ["quantitative detail"],
            "gap_types": ["missing_quantitative_data"],
            "search_directives": ["Find market size"],
            "confidence": 0.4,
            "reason": "Quantitative evidence is missing.",
        }
        self.assertTrue(semantic_sufficiency_payload_contract(payload))

    def test_blocked_with_unresolvable_is_accepted(self) -> None:
        payload = {
            "status": "blocked",
            "missing_aspects": [],
            "gap_types": ["unresolvable"],
            "search_directives": [],
            "confidence": 0.2,
            "reason": "Need cannot be resolved with available sources.",
        }
        self.assertTrue(semantic_sufficiency_payload_contract(payload))


class SemanticSufficiencyAssessorRetryTests(unittest.TestCase):
    def tearDown(self) -> None:
        consume_llm_call_retry_flag()

    def _assess(self, assessor: LlmSemanticSufficiencyAssessor):
        return assessor.assess(
            research_question=ResearchQuestion(
                id="rq-1",
                question="What is the market outlook?",
                objective_refs=(),
            ),
            information_need=InformationNeed(
                id="in-1",
                research_question_id="rq-1",
                description="Need market data",
            ),
            evidence=(
                Evidence(
                    id="evidence-1",
                    project_id="project-1",
                    source_id="source-1",
                    source_content_checksum="checksum-1",
                    workflow_run_id="run-1",
                    research_design_id="design-1",
                    research_question_refs=("rq-1",),
                    information_need_refs=("in-1",),
                    statement="Market grew 10%.",
                    source_excerpt="Market grew 10% in 2025.",
                    created_at="2026-01-01T00:00:00+00:00",
                    deduplication_key="dedup-1",
                ),
            ),
            deterministic_signals=_signals(),
        )

    def test_inconsistent_first_response_is_corrected_on_retry(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.side_effect = [
            LLMResponse(
                content=json.dumps(
                    {
                        "status": "sufficient",
                        "missing_aspects": [],
                        "gap_types": ["insufficient_depth"],
                        "search_directives": [],
                        "confidence": 0.9,
                        "reason": "Looks sufficient.",
                    },
                ),
                finish_reason="stop",
            ),
            LLMResponse(
                content=json.dumps(_valid_sufficient_payload()),
                finish_reason="stop",
            ),
        ]
        assessor = LlmSemanticSufficiencyAssessor(
            llm_client=mock_llm,
            structured_output_max_attempts=2,
        )

        result = self._assess(assessor)

        self.assertEqual(result.status, SufficiencyStatus.SUFFICIENT)
        self.assertEqual(mock_llm.generate.call_count, 2)

    def test_repeated_inconsistent_output_raises_semantic_error_not_validation(
        self,
    ) -> None:
        mock_llm = Mock()
        inconsistent = json.dumps(
            {
                "status": "sufficient",
                "missing_aspects": [],
                "gap_types": ["insufficient_depth"],
                "search_directives": [],
                "confidence": 0.9,
                "reason": "Looks sufficient.",
            },
        )
        mock_llm.generate.side_effect = [
            LLMResponse(content=inconsistent, finish_reason="stop"),
            LLMResponse(content=inconsistent, finish_reason="stop"),
        ]
        assessor = LlmSemanticSufficiencyAssessor(
            llm_client=mock_llm,
            structured_output_max_attempts=2,
        )

        with self.assertRaises(SemanticSufficiencyAssessmentError) as ctx:
            self._assess(assessor)

        self.assertIsInstance(ctx.exception.__cause__, StructuredOutputError)
        self.assertNotIsInstance(ctx.exception, ValidationError)


class ReadinessAggregationConsistencyTests(unittest.TestCase):
    def test_missing_with_evidence_is_coerced_to_insufficient(self) -> None:
        assessment = build_information_need_assessment(
            signals=_signals(),
            semantic=SemanticSufficiencyAssessment(
                status=SufficiencyStatus.MISSING,
                reason="Still missing detail.",
            ),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.INSUFFICIENT)

    def test_semantic_domain_rejects_sufficient_with_blocking_gaps(self) -> None:
        with self.assertRaises(ValidationError):
            SemanticSufficiencyAssessment(
                status=SufficiencyStatus.SUFFICIENT,
                gap_types=(GapType.INSUFFICIENT_DEPTH,),
                reason="Invalid combination.",
            )

    def test_defensive_aggregation_rejects_merged_sufficient_with_blocking_gaps(
        self,
    ) -> None:
        with self.assertRaises(SemanticSufficiencyAssessmentError):
            build_information_need_assessment(
                signals=DeterministicSufficiencySignals(
                    information_need_id="in-1",
                    research_question_id="rq-1",
                    evidence_count=2,
                    independent_source_count=2,
                    evidence_ids=("evidence-1", "evidence-2"),
                    source_ids=("source-1", "source-2"),
                    deterministic_gap_types=(GapType.INSUFFICIENT_DEPTH,),
                ),
                semantic=SemanticSufficiencyAssessment(
                    status=SufficiencyStatus.SUFFICIENT,
                    reason="Looks sufficient.",
                ),
            )

    def test_partial_with_blocking_gap_is_accepted(self) -> None:
        assessment = build_information_need_assessment(
            signals=_signals(),
            semantic=SemanticSufficiencyAssessment(
                status=SufficiencyStatus.PARTIAL,
                gap_types=(GapType.INSUFFICIENT_DEPTH,),
                missing_aspects=("recent data",),
                search_directives=("Find 2025 data",),
                reason="Partial coverage.",
            ),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.PARTIAL)
        self.assertIn(GapType.INSUFFICIENT_DEPTH, assessment.gap_types)


if __name__ == "__main__":
    unittest.main()
