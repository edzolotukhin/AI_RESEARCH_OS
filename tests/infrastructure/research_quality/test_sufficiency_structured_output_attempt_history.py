"""M3.2 per-attempt structured-output observability tests."""

from __future__ import annotations

import json
import logging
import unittest
from unittest.mock import Mock

from application.exceptions.structured_output_error import StructuredOutputError
from application.execution.execution_budget_retry import consume_llm_call_retry_flag
from application.research_quality.exceptions import SemanticSufficiencyAssessmentError
from application.research_quality.raw_semantic_decision_contract import (
    raw_semantic_decision_payload_contract,
)
from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
    LlmSemanticSufficiencyAssessor,
)
from infrastructure.research_quality.sufficiency_structured_output import (
    DEFAULT_SUFFICIENCY_STRUCTURED_OUTPUT_MAX_ATTEMPTS,
    StructuredOutputAttemptTelemetry,
    SufficiencyStructuredOutputGenerator,
)


def _valid_raw_payload() -> dict[str, object]:
    return {
        "supported_aspects": ["__legacy_need__"],
        "missing_aspects": [],
        "semantic_conflicts": [],
        "confidence": 0.9,
        "reason": "Evidence substantively answers the information need.",
    }


class SufficiencyAttemptHistoryTests(unittest.TestCase):
    def tearDown(self) -> None:
        consume_llm_call_retry_flag()

    def _generator(self, mock_llm: Mock, *, max_attempts: int = 3) -> SufficiencyStructuredOutputGenerator:
        return SufficiencyStructuredOutputGenerator(
            llm_client=mock_llm,
            max_output_tokens=8192,
            reasoning_effort="minimal",
            max_attempts=max_attempts,
        )

    def test_contract_failure_then_success_preserves_two_records(self) -> None:
        mock_llm = Mock()
        inconsistent = json.dumps(
            {
                **_valid_raw_payload(),
                "supported_aspects": ["__legacy_need__"],
                "missing_aspects": ["__legacy_need__"],
            },
        )
        mock_llm.generate.side_effect = [
            LLMResponse(content=inconsistent, finish_reason="stop", output_tokens=50),
            LLMResponse(
                content=json.dumps(_valid_raw_payload()),
                finish_reason="stop",
                output_tokens=87,
            ),
        ]
        generator = self._generator(mock_llm, max_attempts=2)
        generator.generate(Prompt(system="System", user="User"))

        self.assertEqual(len(generator.attempt_history), 2)
        first, second = generator.attempt_history
        self.assertFalse(first.success)
        self.assertEqual(first.stage, "contract")
        self.assertEqual(first.parse_failure_category, "parse_error")
        self.assertEqual(first.contract_failure_category, "invalid_sufficiency_contract")
        self.assertTrue(second.success)
        self.assertIsNone(second.stage)
        self.assertIsNone(second.parse_failure_category)
        self.assertIsNone(second.contract_failure_category)
        self.assertEqual(second.output_tokens, 87)

    def test_parse_failure_then_success_preserves_extract_stage(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.side_effect = [
            LLMResponse(content="plain prose", finish_reason="stop", output_tokens=42),
            LLMResponse(content=json.dumps(_valid_raw_payload()), finish_reason="stop"),
        ]
        generator = self._generator(mock_llm, max_attempts=2)
        generator.generate(Prompt(system="System", user="User"))

        self.assertEqual(generator.attempt_history[0].stage, "extract")
        self.assertFalse(generator.attempt_history[0].success)
        self.assertTrue(generator.attempt_history[1].success)

    def test_truncation_then_success_preserves_truncated_category(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.side_effect = [
            LLMResponse(
                content='{"supported_aspects": ["__legacy_need__"], "missing_aspects": ["',
                finish_reason="length",
                output_tokens=2048,
                max_output_tokens=8192,
                reasoning_tokens=300,
            ),
            LLMResponse(content=json.dumps(_valid_raw_payload()), finish_reason="stop"),
        ]
        generator = self._generator(mock_llm, max_attempts=2)
        generator.generate(Prompt(system="System", user="User"))

        first = generator.attempt_history[0]
        self.assertFalse(first.success)
        self.assertEqual(first.stage, "validate")
        self.assertTrue(first.is_truncated)
        self.assertEqual(first.parse_failure_category, "truncated_output")
        self.assertTrue(generator.attempt_history[1].success)

    def test_clean_first_pass_success_has_one_record(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(_valid_raw_payload()),
            finish_reason="stop",
            output_tokens=88,
        )
        generator = self._generator(mock_llm)
        generator.generate(Prompt(system="System", user="User"))

        self.assertEqual(len(generator.attempt_history), 1)
        self.assertTrue(generator.attempt_history[0].success)
        self.assertEqual(generator.attempt_history[0].attempt, 1)

    def test_three_failed_attempts_history_contains_three_failures(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.side_effect = [
            LLMResponse(content="one", finish_reason="stop", output_tokens=10),
            LLMResponse(content="two", finish_reason="stop", output_tokens=11),
            LLMResponse(content="three", finish_reason="stop", output_tokens=12),
        ]
        generator = self._generator(mock_llm, max_attempts=3)
        with self.assertRaises(StructuredOutputError):
            generator.generate(Prompt(system="System", user="User"))

        self.assertEqual(len(generator.attempt_history), 3)
        self.assertTrue(all(not item.success for item in generator.attempt_history))
        self.assertEqual(mock_llm.generate.call_count, 3)

    def test_history_resets_between_generate_calls(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(_valid_raw_payload()),
            finish_reason="stop",
        )
        generator = self._generator(mock_llm)
        generator.generate(Prompt(system="System", user="User"))
        self.assertEqual(len(generator.attempt_history), 1)
        self.assertEqual(mock_llm.generate.call_count, 1)
        generator.generate(Prompt(system="System", user="User"))
        self.assertEqual(mock_llm.generate.call_count, 2)
        self.assertEqual(len(generator.attempt_history), 1)
        self.assertTrue(generator.attempt_history[0].success)

    def test_history_does_not_retain_full_provider_response(self) -> None:
        secret = "GreenSprout Belgrade supplies fresh microgreens to restaurants"
        mock_llm = Mock()
        mock_llm.generate.side_effect = [
            LLMResponse(content=f"plain prose mentioning {secret}", finish_reason="stop"),
            LLMResponse(content=json.dumps(_valid_raw_payload()), finish_reason="stop"),
        ]
        generator = self._generator(mock_llm, max_attempts=2)
        generator.generate(Prompt(system="System", user="User"))

        serialized = json.dumps(
            [item.to_dict() for item in generator.attempt_history],
        )
        self.assertNotIn(secret, serialized)
        self.assertNotIn("CORRECTION REQUEST", serialized)

    def test_failure_categories_preserved_after_later_success(self) -> None:
        mock_llm = Mock()
        inconsistent = json.dumps(
            {
                **_valid_raw_payload(),
                "supported_aspects": ["__legacy_need__"],
                "missing_aspects": ["__legacy_need__"],
            },
        )
        mock_llm.generate.side_effect = [
            LLMResponse(content=inconsistent, finish_reason="stop"),
            LLMResponse(content=json.dumps(_valid_raw_payload()), finish_reason="stop"),
        ]
        generator = self._generator(mock_llm, max_attempts=2)
        generator.generate(Prompt(system="System", user="User"))

        last = generator.last_telemetry
        assert last is not None
        self.assertEqual(last.attempts, 2)
        self.assertIsNone(last.parse_failure_category)
        self.assertIsNone(last.contract_failure_category)
        self.assertEqual(
            generator.attempt_history[0].contract_failure_category,
            "invalid_sufficiency_contract",
        )

    def test_last_telemetry_remains_backward_compatible_on_success(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(_valid_raw_payload()),
            finish_reason="stop",
            output_tokens=87,
            reasoning_tokens=0,
            max_output_tokens=8192,
        )
        generator = self._generator(mock_llm)
        generator.generate(Prompt(system="System", user="User"))

        last = generator.last_telemetry
        assert last is not None
        self.assertEqual(last.attempts, 1)
        self.assertEqual(last.finish_reason, "stop")
        self.assertEqual(last.output_tokens, 87)
        self.assertEqual(last.reasoning_tokens, 0)
        self.assertEqual(last.max_output_tokens, 8192)
        self.assertEqual(
            last.visible_output_length,
            len(json.dumps(_valid_raw_payload())),
        )
        self.assertIsNone(last.parse_failure_category)
        self.assertIsNone(last.contract_failure_category)

    def test_retry_count_and_max_attempts_unchanged(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.side_effect = [
            LLMResponse(content="plain prose", finish_reason="stop"),
            LLMResponse(content=json.dumps(_valid_raw_payload()), finish_reason="stop"),
        ]
        generator = self._generator(mock_llm, max_attempts=2)
        generator.generate(Prompt(system="System", user="User"))
        self.assertEqual(mock_llm.generate.call_count, 2)
        self.assertEqual(
            DEFAULT_SUFFICIENCY_STRUCTURED_OUTPUT_MAX_ATTEMPTS,
            3,
        )

    def test_same_generation_options_reused_on_retry(self) -> None:
        captured: list[LLMGenerationOptions | None] = []
        mock_llm = Mock()

        def _capture(_prompt, *, options=None):
            captured.append(options)
            if len(captured) == 1:
                return LLMResponse(content="plain prose", finish_reason="stop")
            return LLMResponse(content=json.dumps(_valid_raw_payload()), finish_reason="stop")

        mock_llm.generate.side_effect = _capture
        generator = self._generator(mock_llm, max_attempts=2)
        generator.generate(Prompt(system="System", user="User"))
        self.assertEqual(captured[0].max_output_tokens, 8192)
        self.assertEqual(captured[0].reasoning_effort, "minimal")
        self.assertEqual(captured[1].max_output_tokens, 8192)
        self.assertEqual(captured[1].reasoning_effort, "minimal")

    def test_exhaustion_diagnostics_remain_available(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content="plain prose", finish_reason="stop")
        assessor = LlmSemanticSufficiencyAssessor(
            llm_client=mock_llm,
            max_output_tokens=8192,
            structured_output_max_attempts=1,
        )
        from domain.evidence.evidence import Evidence
        from domain.planning.research_design import InformationNeed, ResearchQuestion
        from domain.research_quality.deterministic_sufficiency_signals import (
            DeterministicSufficiencySignals,
        )

        with self.assertRaises(SemanticSufficiencyAssessmentError) as ctx:
            assessor.assess(
                research_question=ResearchQuestion(
                    id="rq-1",
                    question="Q?",
                    objective_refs=(),
                ),
                information_need=InformationNeed(
                    id="in-1",
                    research_question_id="rq-1",
                    description="Need",
                ),
                evidence=(
                    Evidence(
                        id="evidence-1",
                        project_id="project-1",
                        source_id="source-1",
                        source_content_checksum="checksum-1",
                        workflow_run_id="run-1",
                        research_design_id="design-1",
                        statement="Statement.",
                        source_excerpt="Excerpt.",
                        created_at="2026-01-01T00:00:00+00:00",
                    ),
                ),
                deterministic_signals=DeterministicSufficiencySignals(
                    information_need_id="in-1",
                    research_question_id="rq-1",
                    evidence_count=1,
                    independent_source_count=1,
                    evidence_ids=("evidence-1",),
                    source_ids=("source-1",),
                    deterministic_gap_types=(),
                ),
            )

        self.assertIsNotNone(ctx.exception.diagnostics)
        self.assertEqual(len(assessor._structured_output.attempt_history), 1)
        self.assertFalse(assessor._structured_output.attempt_history[0].success)

    def test_intermediate_retry_emits_compact_warning_log(self) -> None:
        mock_llm = Mock()
        inconsistent = json.dumps(
            {
                **_valid_raw_payload(),
                "supported_aspects": ["__legacy_need__"],
                "missing_aspects": ["__legacy_need__"],
            },
        )
        mock_llm.generate.side_effect = [
            LLMResponse(content=inconsistent, finish_reason="stop"),
            LLMResponse(content=json.dumps(_valid_raw_payload()), finish_reason="stop"),
        ]
        generator = self._generator(mock_llm, max_attempts=2)
        with self.assertLogs(
            "infrastructure.research_quality.sufficiency_structured_output",
            level=logging.WARNING,
        ) as captured:
            generator.generate(Prompt(system="System", user="User"))

        log_text = "\n".join(captured.output)
        self.assertIn("sufficiency_structured_output_retry", log_text)
        self.assertIn("stage=contract", log_text)
        self.assertNotIn(inconsistent, log_text)

    def test_attempt_history_is_immutable_records(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(_valid_raw_payload()),
            finish_reason="stop",
        )
        generator = self._generator(mock_llm)
        generator.generate(Prompt(system="System", user="User"))
        self.assertIsInstance(generator.attempt_history[0], StructuredOutputAttemptTelemetry)


class MiniLiveHarnessAttemptHistoryTests(unittest.TestCase):
    def test_harness_report_exposes_attempt_history(self) -> None:
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        scripts_dir = repo_root / "scripts"
        for path in (str(repo_root), str(scripts_dir)):
            if path not in sys.path:
                sys.path.insert(0, path)

        import sufficiency_mini_live_harness as mini_live
        from infrastructure.research_quality.sufficiency_structured_output import (
            StructuredOutputAttemptTelemetry,
        )

        generator = Mock()
        generator.last_telemetry = Mock(
            attempts=2,
            finish_reason="stop",
            output_tokens=87,
            reasoning_tokens=0,
            max_output_tokens=8192,
            visible_output_length=334,
            parse_failure_category=None,
            contract_failure_category=None,
            estimated_cost_usd=None,
        )
        generator.attempt_history = (
            StructuredOutputAttemptTelemetry(
                attempt=1,
                success=False,
                stage="contract",
                parse_failure_category="parse_error",
                contract_failure_category="invalid_sufficiency_contract",
            ),
            StructuredOutputAttemptTelemetry(
                attempt=2,
                success=True,
                finish_reason="stop",
                output_tokens=87,
            ),
        )

        telemetry = mini_live._telemetry_from_generator(generator, elapsed_seconds=1.5)
        payload = telemetry.to_dict()
        self.assertEqual(len(payload["attempt_history"]), 2)
        self.assertFalse(payload["attempt_history"][0]["success"])
        self.assertEqual(payload["attempt_history"][0]["stage"], "contract")
        self.assertTrue(payload["attempt_history"][1]["success"])


if __name__ == "__main__":
    unittest.main()
