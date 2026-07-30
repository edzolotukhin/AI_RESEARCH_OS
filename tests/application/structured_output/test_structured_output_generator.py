import unittest
from unittest.mock import Mock

from application.exceptions.structured_output_error import StructuredOutputError
from application.planner.payload_contract import PlannerPayloadContract
from tests.helpers.executor_catalog import make_test_executor_catalog
from application.structured_output.correction_prompt import (
    PLANNER_PAYLOAD_SCHEMA,
    StructuredOutputCorrectionPromptBuilder,
)
from application.structured_output.generator import StructuredOutputGenerator
from application.structured_output.parser import StructuredOutputParser

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt

from tests.fixtures.planner_responses import (
    TRUNCATED_PLANNER_JSON,
    VALID_PLANNER_JSON,
)


class StructuredOutputGeneratorTests(unittest.TestCase):

    def setUp(self):
        self.llm_client = Mock()
        self.parser = StructuredOutputParser()
        self.contract = PlannerPayloadContract(
            executor_catalog=make_test_executor_catalog(),
        )
        self.prompt = Prompt(
            system="System prompt",
            user="User prompt",
        )
        self.generator = StructuredOutputGenerator(
            llm_client=self.llm_client,
            parser=self.parser,
            max_attempts=3,
        )

    def test_valid_json_on_first_attempt_uses_single_llm_call(self):
        self.llm_client.generate.return_value = LLMResponse(
            content=VALID_PLANNER_JSON,
            finish_reason="stop",
        )

        payload = self.generator.generate(
            self.prompt,
            payload_contract=self.contract,
        )

        self.assertEqual(payload["name"], "Brand Health Workflow")
        self.llm_client.generate.assert_called_once()

    def test_malformed_json_then_valid_json_retries_once(self):
        self.llm_client.generate.side_effect = [
            LLMResponse(content="{ invalid json"),
            LLMResponse(content=VALID_PLANNER_JSON, finish_reason="stop"),
        ]

        payload = self.generator.generate(
            self.prompt,
            payload_contract=self.contract,
        )

        self.assertEqual(payload["name"], "Brand Health Workflow")
        self.assertEqual(self.llm_client.generate.call_count, 2)

    def test_contract_invalid_then_valid_json_retries(self):
        invalid_contract = """
        {
          "goal": "Evaluate brand awareness, usage and loyalty.",
          "methodology": "Quantitative brand tracking survey",
          "stages": [],
          "metadata": {}
        }
        """

        self.llm_client.generate.side_effect = [
            LLMResponse(content=invalid_contract),
            LLMResponse(content=VALID_PLANNER_JSON, finish_reason="stop"),
        ]

        payload = self.generator.generate(
            self.prompt,
            payload_contract=self.contract,
        )

        self.assertEqual(len(payload["stages"]), 1)
        self.assertEqual(self.llm_client.generate.call_count, 2)

    def test_three_malformed_attempts_raise_structured_output_error(self):
        self.llm_client.generate.side_effect = [
            LLMResponse(content="{ broken"),
            LLMResponse(content="{ still broken"),
            LLMResponse(content="{ final broken"),
        ]

        with self.assertRaises(StructuredOutputError) as ctx:
            self.generator.generate(
                self.prompt,
                payload_contract=self.contract,
            )

        self.assertEqual(ctx.exception.attempts, 3)
        self.assertEqual(self.llm_client.generate.call_count, 3)

    def test_authentication_error_is_not_retried(self):
        class AuthenticationError(Exception):
            pass

        self.llm_client.generate.side_effect = AuthenticationError(
            "Invalid API key",
        )

        with self.assertRaises(AuthenticationError):
            self.generator.generate(
                self.prompt,
                payload_contract=self.contract,
            )

        self.llm_client.generate.assert_called_once()

    def test_parser_remains_strict_and_does_not_repair_truncated_json(self):
        parser = StructuredOutputParser()

        with self.assertRaises(StructuredOutputError) as ctx:
            parser.parse(
                TRUNCATED_PLANNER_JSON,
                llm_truncated=True,
                finish_reason="length",
            )

        self.assertTrue(ctx.exception.is_truncated)
        self.assertEqual(ctx.exception.stage, "validate")

    def test_truncated_first_response_then_compact_valid_payload_retries_once(self):
        self.llm_client.generate.side_effect = [
            LLMResponse(
                content=TRUNCATED_PLANNER_JSON,
                finish_reason="length",
                output_tokens=4096,
                max_output_tokens=4096,
            ),
            LLMResponse(
                content=VALID_PLANNER_JSON,
                finish_reason="stop",
            ),
        ]

        payload = self.generator.generate(
            self.prompt,
            payload_contract=self.contract,
        )

        self.assertEqual(payload["name"], "Brand Health Workflow")
        self.assertEqual(self.llm_client.generate.call_count, 2)

        correction_prompt = self.llm_client.generate.call_args_list[1].args[0]
        self.assertIn("truncated", correction_prompt.user.lower())
        self.assertIn("JSON only", correction_prompt.user)


class StructuredOutputCorrectionPromptBuilderTests(unittest.TestCase):

    def setUp(self):
        self.builder = StructuredOutputCorrectionPromptBuilder()
        self.prompt = Prompt(system="System", user="User")
        self.error = StructuredOutputError(
            "LLM response does not contain a syntactically valid JSON object.",
            stage="validate",
            candidate_count=1,
            json_decode_message="Unterminated string starting at",
            json_error_line=172,
            json_error_column=7,
            is_truncated=True,
            finish_reason="length",
        )

    def test_correction_prompt_requires_json_only(self):
        correction = self.builder.build(
            original_prompt=self.prompt,
            invalid_response=LLMResponse(
                content=TRUNCATED_PLANNER_JSON,
                finish_reason="length",
            ),
            error=self.error,
            payload_schema=PLANNER_PAYLOAD_SCHEMA,
            truncated=True,
        )

        self.assertIn("Return only one JSON object", correction.system)
        self.assertIn("Return JSON only", correction.user)
        self.assertNotIn("```", correction.user)

    def test_correction_prompt_contains_validation_summary(self):
        correction = self.builder.build(
            original_prompt=self.prompt,
            invalid_response=LLMResponse(content="{"),
            error=self.error,
            payload_schema=PLANNER_PAYLOAD_SCHEMA,
            truncated=True,
        )

        self.assertIn("stage=validate", correction.user)
        self.assertIn("truncated=true", correction.user)
        self.assertIn("finish_reason=length", correction.user)

    def test_correction_prompt_contains_payload_schema(self):
        correction = self.builder.build(
            original_prompt=self.prompt,
            invalid_response=LLMResponse(content="{"),
            error=self.error,
            payload_schema=PLANNER_PAYLOAD_SCHEMA,
            truncated=True,
        )

        self.assertIn('"stages"', correction.user)
        self.assertIn('"executor_id"', correction.user)

    def test_truncated_correction_prompt_requests_compact_regeneration(self):
        correction = self.builder.build(
            original_prompt=self.prompt,
            invalid_response=LLMResponse(
                content=TRUNCATED_PLANNER_JSON,
                finish_reason="length",
            ),
            error=self.error,
            payload_schema=PLANNER_PAYLOAD_SCHEMA,
            truncated=True,
        )

        self.assertIn("truncated", correction.user.lower())
        self.assertIn(
            "Regenerate the complete JSON object from the beginning",
            correction.user,
        )
        self.assertIn("Reduce verbosity", correction.user)


if __name__ == "__main__":
    unittest.main()
