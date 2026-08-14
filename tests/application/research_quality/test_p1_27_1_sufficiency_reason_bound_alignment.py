"""P1-27.1 PROPERTY AE: sufficiency reason-bound alignment."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from application.exceptions.structured_output_error import StructuredOutputError
from application.research_quality.exceptions import SemanticSufficiencyAssessmentError
from application.research_quality.raw_semantic_decision_contract import (
    DEFAULT_RAW_SEMANTIC_MAX_REASON_CHARS,
    evaluate_raw_semantic_decision_payload,
    raw_semantic_decision_output_instructions,
)
from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from infrastructure.research_quality.sufficiency_structured_output import (
    DEFAULT_SUFFICIENCY_STRUCTURED_OUTPUT_MAX_ATTEMPTS,
    SufficiencyStructuredOutputGenerator,
    _build_correction_prompt,
)


def _payload(reason: str, *, subject: str = "Ukraine pizza") -> dict[str, object]:
    return {
        "supported_aspects": ["market_size"],
        "missing_aspects": [],
        "semantic_conflicts": [],
        "confidence": 0.8,
        "reason": f"{subject}: {reason}" if subject else reason,
    }


def _exact_reason_payload(length: int, char: str = "x") -> dict[str, object]:
    return _payload(char * length, subject="")


def _response(payload: dict[str, object]) -> LLMResponse:
    return LLMResponse(content=json.dumps(payload), finish_reason="stop")


class ReasonBoundContractTests(unittest.TestCase):
    def test_first_attempt_prompt_contains_canonical_maximum(self) -> None:
        instructions = raw_semantic_decision_output_instructions()
        self.assertIn("reason", instructions)
        self.assertIn(str(DEFAULT_RAW_SEMANTIC_MAX_REASON_CHARS), instructions)
        self.assertIn("at most", instructions)

    def test_reason_499_is_accepted(self) -> None:
        self.assertIsNone(evaluate_raw_semantic_decision_payload(_exact_reason_payload(499)))

    def test_reason_500_is_accepted(self) -> None:
        self.assertIsNone(evaluate_raw_semantic_decision_payload(_exact_reason_payload(500)))

    def test_reason_501_is_rejected(self) -> None:
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(_exact_reason_payload(501)),
            "reason_too_long",
        )

    def test_minimum_one_non_whitespace_character_is_accepted(self) -> None:
        self.assertIsNone(evaluate_raw_semantic_decision_payload(_exact_reason_payload(1)))

    def test_empty_reason_is_rejected(self) -> None:
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(_exact_reason_payload(0)),
            "blank_reason",
        )

    def test_unicode_uses_python_character_length(self) -> None:
        self.assertIsNone(
            evaluate_raw_semantic_decision_payload(_exact_reason_payload(500, "é")),
        )
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(_exact_reason_payload(501, "é")),
            "reason_too_long",
        )

    def test_valid_json_overlong_reason_is_contract_not_syntax_failure(self) -> None:
        generator = SufficiencyStructuredOutputGenerator(
            llm_client=Mock(generate=Mock(return_value=_response(_exact_reason_payload(501)))),
            max_attempts=1,
        )
        with self.assertRaises(StructuredOutputError) as ctx:
            generator.generate(Prompt(system="contract", user="context"))
        self.assertEqual(ctx.exception.stage, "contract")
        self.assertEqual(generator.attempt_history[0].contract_rejection_code, "reason_too_long")


class CorrectiveRetryTests(unittest.TestCase):
    def _correction(self) -> Prompt:
        return _build_correction_prompt(
            original_prompt=Prompt(system="system", user="context"),
            invalid_response=_response(_exact_reason_payload(501)),
            error=StructuredOutputError("contract failure", stage="contract"),
            payload_schema='{"reason": "string"}',
            contract_rejection_code="reason_too_long",
        )

    def test_feedback_identifies_reason_field(self) -> None:
        self.assertIn("field 'reason'", self._correction().user)

    def test_feedback_includes_canonical_maximum(self) -> None:
        self.assertIn(str(DEFAULT_RAW_SEMANTIC_MAX_REASON_CHARS), self._correction().user)
        self.assertIn("maximum", self._correction().user)

    def test_feedback_instructs_correction(self) -> None:
        feedback = self._correction().user
        self.assertIn("corrected JSON response", feedback)
        self.assertIn("fits within this maximum", feedback)

    def test_feedback_has_no_stack_trace_or_provider_internals(self) -> None:
        feedback = self._correction().user
        self.assertNotIn("Traceback", feedback)
        self.assertNotIn("api_key", feedback.casefold())
        self.assertNotIn("bearer", feedback.casefold())

    def test_retry_count_is_unchanged(self) -> None:
        self.assertEqual(DEFAULT_SUFFICIENCY_STRUCTURED_OUTPUT_MAX_ATTEMPTS, 3)

    def test_one_invalid_then_valid_succeeds_without_truncation(self) -> None:
        client = Mock()
        client.generate.side_effect = [
            _response(_exact_reason_payload(501)),
            _response(_exact_reason_payload(500)),
        ]
        generator = SufficiencyStructuredOutputGenerator(llm_client=client)
        result = generator.generate(Prompt(system="contract", user="context"))
        self.assertEqual(len(result["reason"]), 500)
        self.assertEqual(client.generate.call_count, 2)

    def test_two_invalid_then_final_valid_replays_p1_26_2_failure_class(self) -> None:
        client = Mock()
        client.generate.side_effect = [
            _response(_exact_reason_payload(501)),
            _response(_exact_reason_payload(650)),
            _response(_exact_reason_payload(500)),
        ]
        generator = SufficiencyStructuredOutputGenerator(llm_client=client)
        result = generator.generate(Prompt(system="contract", user="IN4 context"))
        self.assertEqual(len(result["reason"]), 500)
        self.assertEqual(client.generate.call_count, 3)
        for call in client.generate.call_args_list[1:]:
            prompt = call.args[0]
            self.assertIn("reason", prompt.user)
            self.assertIn("500", prompt.user)

    def test_all_invalid_preserves_fail_closed_exhaustion(self) -> None:
        client = Mock(generate=Mock(return_value=_response(_exact_reason_payload(501))))
        generator = SufficiencyStructuredOutputGenerator(llm_client=client)
        with self.assertRaises(StructuredOutputError):
            generator.generate(Prompt(system="contract", user="context"))
        self.assertEqual(client.generate.call_count, 3)
        self.assertTrue(all(not item.success for item in generator.attempt_history))

    def test_no_silent_truncation_or_fabricated_reason(self) -> None:
        original = _exact_reason_payload(501)
        client = Mock(generate=Mock(return_value=_response(original)))
        generator = SufficiencyStructuredOutputGenerator(llm_client=client, max_attempts=1)
        with self.assertRaises(StructuredOutputError):
            generator.generate(Prompt(system="contract", user="context"))
        self.assertEqual(len(original["reason"]), 501)


class DomainGeneralReasonBoundTests(unittest.TestCase):
    def test_cross_domain_reasons_share_identical_bound(self) -> None:
        for subject in (
            "Ukraine pizza",
            "New Zealand residential heat pumps",
            "India UPI merchant payments",
            "German industrial electricity",
        ):
            with self.subTest(subject=subject):
                accepted = _payload("x" * (500 - len(subject) - 2), subject=subject)
                rejected = _payload("x" * (501 - len(subject) - 2), subject=subject)
                self.assertIsNone(evaluate_raw_semantic_decision_payload(accepted))
                self.assertEqual(
                    evaluate_raw_semantic_decision_payload(rejected),
                    "reason_too_long",
                )


if __name__ == "__main__":
    unittest.main()
