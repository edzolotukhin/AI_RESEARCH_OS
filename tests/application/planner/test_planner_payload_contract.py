import unittest
from unittest.mock import Mock, patch

from application.exceptions.structured_output_error import StructuredOutputError
from application.exceptions.planner_parser_error import PlannerParserError
from application.planner.payload_contract import (
    PLANNER_PAYLOAD_VALIDATION_ERRORS,
    PlannerPayloadContract,
)
from application.structured_output.generator import StructuredOutputGenerator
from application.structured_output.parser import StructuredOutputParser

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt

from tests.fixtures.planner_responses import (
    UNKNOWN_EXECUTOR_PLANNER_JSON,
    VALID_PLANNER_JSON,
)
from tests.helpers.executor_catalog import make_test_executor_catalog


class PlannerPayloadContractTests(unittest.TestCase):

    def setUp(self):
        self.catalog = make_test_executor_catalog()
        self.contract = PlannerPayloadContract(
            executor_catalog=self.catalog,
        )
        self.parser = StructuredOutputParser()

    def test_unknown_executor_id_is_contract_violation(self):
        payload = self.parser.parse(UNKNOWN_EXECUTOR_PLANNER_JSON)

        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("ResearchLead", self.contract.last_validation_error)

    def test_missing_required_field_is_contract_violation(self):
        payload = {"goal": "Evaluate brand awareness.", "stages": []}

        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("Missing required field 'name'", self.contract.last_validation_error)

    def test_attribute_error_is_not_swallowed(self):
        with patch.object(
            self.contract,
            "_validate_executor_ids",
            side_effect=AttributeError("catalog regression"),
        ):
            with self.assertRaises(AttributeError):
                self.contract.accepts({"name": "Plan", "goal": "Goal", "stages": []})

        self.assertEqual(self.contract.last_validation_error, "")

    def test_runtime_error_is_not_swallowed(self):
        with patch.object(
            self.contract,
            "_validate_executor_ids",
            side_effect=RuntimeError("registry failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.contract.accepts({"name": "Plan", "goal": "Goal", "stages": []})

    def test_assertion_error_is_not_swallowed(self):
        with patch.object(
            self.contract,
            "_validate_executor_ids",
            side_effect=AssertionError("internal invariant"),
        ):
            with self.assertRaises(AssertionError):
                self.contract.accepts({"name": "Plan", "goal": "Goal", "stages": []})

    def test_expected_validation_errors_tuple(self):
        self.assertIn(PlannerParserError, PLANNER_PAYLOAD_VALIDATION_ERRORS)
        self.assertIn(ValueError, PLANNER_PAYLOAD_VALIDATION_ERRORS)
        self.assertIn(TypeError, PLANNER_PAYLOAD_VALIDATION_ERRORS)


class PlannerPayloadContractRetryPolicyTests(unittest.TestCase):

    def setUp(self):
        self.catalog = make_test_executor_catalog()
        self.contract = PlannerPayloadContract(
            executor_catalog=self.catalog,
        )
        self.llm_client = Mock()
        self.generator = StructuredOutputGenerator(
            llm_client=self.llm_client,
            parser=StructuredOutputParser(),
            executor_catalog=self.catalog,
        )
        self.prompt = Prompt(system="System", user="User")

    def test_unknown_executor_id_allows_structured_output_retry(self):
        self.llm_client.generate.side_effect = [
            LLMResponse(content=UNKNOWN_EXECUTOR_PLANNER_JSON),
            LLMResponse(content=VALID_PLANNER_JSON, finish_reason="stop"),
        ]

        payload = self.generator.generate(
            self.prompt,
            payload_contract=self.contract,
        )

        self.assertEqual(payload["name"], "Brand Health Workflow")
        self.assertEqual(self.llm_client.generate.call_count, 2)

    def test_programming_error_does_not_trigger_retry(self):
        broken_contract = PlannerPayloadContract(
            executor_catalog=self.catalog,
        )

        with patch.object(
            broken_contract,
            "_validate_executor_ids",
            side_effect=RuntimeError("programming defect"),
        ):
            self.llm_client.generate.return_value = LLMResponse(
                content=VALID_PLANNER_JSON,
            )

            with self.assertRaises(RuntimeError):
                self.generator.generate(
                    self.prompt,
                    payload_contract=broken_contract,
                )

        self.llm_client.generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
