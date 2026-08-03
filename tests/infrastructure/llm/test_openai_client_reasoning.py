"""Mocked OpenAI Responses API reasoning-budget tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from application.structured_output.generation_policy import StructuredGenerationPolicy
from application.structured_output.generator import StructuredOutputGenerator
from application.planner.payload_contract import PlannerPayloadContract
from application.structured_output.parser import StructuredOutputParser
from domain.ai.prompt import Prompt
from infrastructure.llm.llm_configuration import LLMConfiguration
from infrastructure.llm.openai_client import OpenAIClient
from domain.ai.reasoning_budget import is_reasoning_budget_exhaustion

from tests.fixtures.planner_responses import LEGACY_PLANNER_JSON, TRUNCATED_PLANNER_JSON
from tests.helpers.executor_catalog import make_test_executor_catalog


def _response_namespace(**kwargs):
    defaults = {
        "status": "completed",
        "output_text": "{}",
        "usage": SimpleNamespace(
            output_tokens=0,
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
        "incomplete_details": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class ReasoningBudgetDetectionTests(unittest.TestCase):
    def test_small_visible_json_with_high_reasoning_usage_is_reasoning_exhaustion(self):
        from domain.ai.llm_response import LLMResponse

        response = LLMResponse(
            content=TRUNCATED_PLANNER_JSON,
            finish_reason="length",
            output_tokens=4096,
            max_output_tokens=4096,
            reasoning_tokens=3200,
            incomplete_reason="max_output_tokens",
            configured_reasoning_effort="low",
        )

        self.assertTrue(is_reasoning_budget_exhaustion(response))
        self.assertTrue(response.reasoning_budget_exhausted)

    def test_completed_response_is_not_reasoning_exhaustion(self):
        from domain.ai.llm_response import LLMResponse

        response = LLMResponse(
            content=LEGACY_PLANNER_JSON,
            finish_reason="stop",
            output_tokens=900,
            max_output_tokens=8192,
            reasoning_tokens=400,
        )

        self.assertFalse(is_reasoning_budget_exhaustion(response))


class OpenAIClientReasoningTests(unittest.TestCase):
    @patch("openai.OpenAI")
    def test_planner_request_sends_configured_reasoning_effort(self, openai_cls):
        api_client = Mock()
        openai_cls.return_value = api_client
        api_client.responses.create.return_value = _response_namespace(
            output_text=LEGACY_PLANNER_JSON,
            usage=SimpleNamespace(
                output_tokens=900,
                output_tokens_details=SimpleNamespace(reasoning_tokens=200),
            ),
        )

        client = OpenAIClient(
            LLMConfiguration(model="gpt-5", max_tokens=4096),
        )
        options = StructuredGenerationPolicy(
            reasoning_effort="minimal",
            max_output_tokens=8192,
        ).initial_options()

        response = client.generate(
            Prompt(system="System", user="User"),
            options=options,
        )

        create_kwargs = api_client.responses.create.call_args.kwargs
        self.assertEqual(create_kwargs["reasoning"], {"effort": "minimal"})
        self.assertEqual(create_kwargs["max_output_tokens"], 8192)
        self.assertEqual(response.reasoning_tokens, 200)
        self.assertEqual(response.configured_reasoning_effort, "minimal")

    @patch("openai.OpenAI")
    def test_truncated_response_captures_incomplete_reason_and_reasoning_tokens(
        self,
        openai_cls,
    ):
        api_client = Mock()
        openai_cls.return_value = api_client
        api_client.responses.create.return_value = _response_namespace(
            status="incomplete",
            output_text=TRUNCATED_PLANNER_JSON,
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            usage=SimpleNamespace(
                output_tokens=4096,
                output_tokens_details=SimpleNamespace(reasoning_tokens=3500),
            ),
        )

        client = OpenAIClient(LLMConfiguration(model="gpt-5", max_tokens=4096))
        response = client.generate(
            Prompt(system="System", user="User"),
            options=StructuredGenerationPolicy(
                reasoning_effort="minimal",
                max_output_tokens=4096,
            ).initial_options(),
        )

        self.assertEqual(response.finish_reason, "length")
        self.assertEqual(response.incomplete_reason, "max_output_tokens")
        self.assertEqual(response.reasoning_tokens, 3500)
        self.assertTrue(response.reasoning_budget_exhausted)


class StructuredOutputGeneratorReasoningRetryTests(unittest.TestCase):
    def setUp(self):
        self.llm_client = Mock()
        self.policy = StructuredGenerationPolicy(
            reasoning_effort="low",
            max_output_tokens=6144,
            escalation_reasoning_effort="minimal",
            escalation_max_output_tokens=8192,
        )
        self.generator = StructuredOutputGenerator(
            llm_client=self.llm_client,
            parser=StructuredOutputParser(),
            max_attempts=3,
            generation_policy=self.policy,
        )
        self.contract = PlannerPayloadContract(
            executor_catalog=make_test_executor_catalog(),
        )
        self.prompt = Prompt(system="System", user="User")

    def test_reasoning_budget_truncation_retries_with_escalated_configuration(self):
        from domain.ai.llm_response import LLMResponse

        self.llm_client.generate.side_effect = [
            LLMResponse(
                content=TRUNCATED_PLANNER_JSON,
                finish_reason="length",
                output_tokens=6144,
                max_output_tokens=6144,
                reasoning_tokens=5000,
                incomplete_reason="max_output_tokens",
                configured_reasoning_effort="low",
            ),
            LLMResponse(
                content=LEGACY_PLANNER_JSON,
                finish_reason="stop",
                configured_reasoning_effort="minimal",
            ),
        ]

        payload = self.generator.generate(
            self.prompt,
            payload_contract=self.contract,
        )

        self.assertEqual(payload["name"], "Brand Health Workflow")
        self.assertEqual(self.llm_client.generate.call_count, 2)

        first_options = self.llm_client.generate.call_args_list[0].kwargs["options"]
        second_options = self.llm_client.generate.call_args_list[1].kwargs["options"]
        self.assertEqual(first_options.reasoning_effort, "low")
        self.assertEqual(first_options.max_output_tokens, 6144)
        self.assertEqual(second_options.reasoning_effort, "minimal")
        self.assertEqual(second_options.max_output_tokens, 8192)

    def test_valid_json_on_first_attempt_unchanged(self):
        from domain.ai.llm_response import LLMResponse

        self.llm_client.generate.return_value = LLMResponse(
            content=LEGACY_PLANNER_JSON,
            finish_reason="stop",
        )

        payload = self.generator.generate(
            self.prompt,
            payload_contract=self.contract,
        )

        self.assertEqual(payload["name"], "Brand Health Workflow")
        self.llm_client.generate.assert_called_once()
        options = self.llm_client.generate.call_args.kwargs["options"]
        self.assertEqual(options.reasoning_effort, "low")
        self.assertEqual(options.max_output_tokens, 6144)

    def test_reasoning_budget_error_includes_telemetry(self):
        from domain.ai.llm_response import LLMResponse

        from application.exceptions.structured_output_error import StructuredOutputError

        self.llm_client.generate.side_effect = [
            LLMResponse(
                content=TRUNCATED_PLANNER_JSON,
                finish_reason="length",
                output_tokens=6144,
                max_output_tokens=6144,
                reasoning_tokens=5200,
                incomplete_reason="max_output_tokens",
                configured_reasoning_effort="low",
            ),
            LLMResponse(
                content=TRUNCATED_PLANNER_JSON,
                finish_reason="length",
                output_tokens=8192,
                max_output_tokens=8192,
                reasoning_tokens=7000,
                incomplete_reason="max_output_tokens",
                configured_reasoning_effort="minimal",
            ),
            LLMResponse(
                content=TRUNCATED_PLANNER_JSON,
                finish_reason="length",
                output_tokens=8192,
                max_output_tokens=8192,
                reasoning_tokens=7000,
                incomplete_reason="max_output_tokens",
                configured_reasoning_effort="minimal",
            ),
        ]

        with self.assertRaises(StructuredOutputError) as ctx:
            self.generator.generate(
                self.prompt,
                payload_contract=self.contract,
            )

        message = str(ctx.exception)
        self.assertIn("reasoning_tokens=", message)
        self.assertIn("reasoning_budget_exhausted=true", message)
        self.assertIn("incomplete_reason=max_output_tokens", message)
        self.assertIn("reasoning_effort=", message)


if __name__ == "__main__":
    unittest.main()
