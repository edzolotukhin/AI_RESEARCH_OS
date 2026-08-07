"""Diagnostics tests for LlmSemanticSufficiencyAssessor structured-output failures."""

from __future__ import annotations

import ast
import json
import logging
import unittest
from unittest.mock import Mock

from application.exceptions.structured_output_error import StructuredOutputError
from application.execution.execution_budget_retry import consume_llm_call_retry_flag
from application.research_quality.exceptions import SemanticSufficiencyAssessmentError
from domain.ai.llm_response import LLMResponse
from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchQuestion
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.gap_type import GapType
from domain.research_quality.sufficiency_status import SufficiencyStatus

from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
    LlmSemanticSufficiencyAssessor,
)


def _assess_inputs() -> tuple[
    ResearchQuestion,
    InformationNeed,
    tuple[Evidence, ...],
    DeterministicSufficiencySignals,
]:
    research_question = ResearchQuestion(
        id="rq-1",
        question="What is the market outlook?",
        objective_refs=(),
    )
    information_need = InformationNeed(
        id="in-1",
        research_question_id="rq-1",
        description="Need market data",
    )
    evidence = (
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
    )
    signals = DeterministicSufficiencySignals(
        information_need_id="in-1",
        research_question_id="rq-1",
        evidence_count=1,
        independent_source_count=1,
        evidence_ids=("evidence-1",),
        source_ids=("source-1",),
        deterministic_gap_types=(),
    )
    return research_question, information_need, evidence, signals


def _assessor(
    mock_llm: Mock,
    *,
    max_attempts: int = 3,
    max_output_tokens: int = 2048,
) -> LlmSemanticSufficiencyAssessor:
    return LlmSemanticSufficiencyAssessor(
        llm_client=mock_llm,
        max_output_tokens=max_output_tokens,
        structured_output_max_attempts=max_attempts,
    )


class LlmSemanticSufficiencyAssessorDiagnosticsTests(unittest.TestCase):
    def tearDown(self) -> None:
        consume_llm_call_retry_flag()

    def _assert_diagnostics_shape(
        self,
        exc: SemanticSufficiencyAssessmentError,
        *,
        expected_stage: str,
        expected_parse_category: str | None,
        expected_contract_category: str | None = None,
        expected_attempts: int = 3,
        expected_truncated: bool = False,
    ) -> None:
        self.assertIsInstance(exc.__cause__, StructuredOutputError)
        self.assertIsNotNone(exc.diagnostics)
        diagnostics = exc.diagnostics
        assert diagnostics is not None
        payload = diagnostics.to_dict()
        self.assertEqual(diagnostics.stage, expected_stage)
        self.assertEqual(diagnostics.is_truncated, expected_truncated)
        self.assertEqual(diagnostics.attempts, expected_attempts)
        self.assertEqual(diagnostics.parse_failure_category, expected_parse_category)
        self.assertEqual(
            diagnostics.contract_failure_category,
            expected_contract_category,
        )
        self.assertIn("structured_output_message", payload)
        self.assertNotIn("source_preview", payload)
        self.assertNotIn("candidate_preview", payload)
        self.assertNotIn("evidence", payload)
        self.assertIn("stage=", str(exc))
        self.assertIn("attempts=", str(exc))
        self.assertIn(diagnostics.structured_output_message, str(exc))

    def test_invalid_json_parse_failure_exposes_diagnostics(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content="plain prose response without json",
            finish_reason="stop",
            output_tokens=42,
            max_output_tokens=2048,
            reasoning_tokens=11,
        )
        assessor = _assessor(mock_llm, max_attempts=1)
        rq, need, evidence, signals = _assess_inputs()

        with self.assertRaises(SemanticSufficiencyAssessmentError) as ctx:
            assessor.assess(
                research_question=rq,
                information_need=need,
                evidence=evidence,
                deterministic_signals=signals,
            )

        self._assert_diagnostics_shape(
            ctx.exception,
            expected_stage="extract",
            expected_parse_category="parse_error",
            expected_attempts=1,
        )
        self.assertEqual(ctx.exception.diagnostics.output_tokens, 42)
        self.assertEqual(ctx.exception.diagnostics.reasoning_tokens, 11)

    def test_contract_validation_failure_exposes_diagnostics(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(
                {
                    "supported_aspects": ["__legacy_need__"],
                    "missing_aspects": ["__legacy_need__"],
                    "semantic_conflicts": [],
                    "confidence": 0.5,
                    "reason": "Overlapping aspects.",
                },
            ),
            finish_reason="stop",
            output_tokens=88,
            max_output_tokens=2048,
        )
        assessor = _assessor(mock_llm, max_attempts=1)
        rq, need, evidence, signals = _assess_inputs()

        with self.assertRaises(SemanticSufficiencyAssessmentError) as ctx:
            assessor.assess(
                research_question=rq,
                information_need=need,
                evidence=evidence,
                deterministic_signals=signals,
            )

        self._assert_diagnostics_shape(
            ctx.exception,
            expected_stage="contract",
            expected_parse_category="parse_error",
            expected_contract_category="invalid_sufficiency_contract",
            expected_attempts=1,
        )

    def test_truncated_output_exposes_diagnostics(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content='{"supported_aspects": ["__legacy_need__"], "missing_aspects": ["',
            finish_reason="length",
            output_tokens=2048,
            max_output_tokens=2048,
            reasoning_tokens=300,
        )
        assessor = _assessor(mock_llm, max_attempts=1)
        rq, need, evidence, signals = _assess_inputs()

        with self.assertRaises(SemanticSufficiencyAssessmentError) as ctx:
            assessor.assess(
                research_question=rq,
                information_need=need,
                evidence=evidence,
                deterministic_signals=signals,
            )

        self._assert_diagnostics_shape(
            ctx.exception,
            expected_stage="validate",
            expected_parse_category="truncated_output",
            expected_attempts=1,
            expected_truncated=True,
        )
        self.assertEqual(ctx.exception.diagnostics.finish_reason, "length")

    def test_max_attempt_exhaustion_exposes_attempt_count(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.side_effect = [
            LLMResponse(content="plain prose one", finish_reason="stop", output_tokens=10),
            LLMResponse(content="plain prose two", finish_reason="stop", output_tokens=11),
            LLMResponse(content="plain prose three", finish_reason="stop", output_tokens=12),
        ]
        assessor = _assessor(mock_llm, max_attempts=3)
        rq, need, evidence, signals = _assess_inputs()

        with self.assertRaises(SemanticSufficiencyAssessmentError) as ctx:
            assessor.assess(
                research_question=rq,
                information_need=need,
                evidence=evidence,
                deterministic_signals=signals,
            )

        self._assert_diagnostics_shape(
            ctx.exception,
            expected_stage="extract",
            expected_parse_category="parse_error",
            expected_attempts=3,
        )
        self.assertEqual(mock_llm.generate.call_count, 3)

    def test_structured_log_emitted_without_sensitive_payload(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content="plain prose response without json",
            finish_reason="stop",
            output_tokens=7,
        )
        assessor = _assessor(mock_llm, max_attempts=1)
        rq, need, evidence, signals = _assess_inputs()

        with self.assertLogs(
            "infrastructure.research_quality.llm_semantic_sufficiency_assessor",
            level=logging.ERROR,
        ) as captured:
            with self.assertRaises(SemanticSufficiencyAssessmentError):
                assessor.assess(
                    research_question=rq,
                    information_need=need,
                    evidence=evidence,
                    deterministic_signals=signals,
                )

        log_text = "\n".join(captured.output)
        self.assertIn("sufficiency_structured_output_failed", log_text)
        self.assertIn("parse_failure_category", log_text)
        self.assertNotIn("Market grew 10%", log_text)
        self.assertNotIn("CORRECTION REQUEST", log_text)

        diagnostics_text = log_text.split("diagnostics=", 1)[-1]
        parsed = ast.literal_eval(diagnostics_text.strip())
        self.assertEqual(parsed["attempts"], 1)
        self.assertNotIn("source_preview", parsed)


if __name__ == "__main__":
    unittest.main()
