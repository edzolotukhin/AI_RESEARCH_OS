import json
import unittest
from unittest.mock import Mock, patch

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
    INVALID_DUPLICATE_QUESTION_JSON,
    LEGACY_PLANNER_JSON,
    LEGACY_UNKNOWN_EXECUTOR_PLANNER_JSON,
)
from tests.helpers.executor_catalog import make_test_executor_catalog


def _planner_payload(tasks: list[dict]) -> dict:
    return {
        "name": "Test Plan",
        "goal": "Evaluate brand awareness.",
        "methodology": "Quantitative survey",
        "stages": [
            {
                "id": "stage-design",
                "name": "Research Design",
                "description": "Define methodology.",
                "tasks": tasks,
            }
        ],
        "metadata": {},
    }


def _task(
    task_id: str,
    *,
    executor_id: str = "planner",
    dependencies: list[str] | None = None,
) -> dict:
    return {
        "id": task_id,
        "title": f"Task {task_id}",
        "description": f"Description for {task_id}.",
        "executor_id": executor_id,
        "dependencies": dependencies or [],
    }


UNKNOWN_DEPENDENCY_PLANNER_JSON = json.dumps(
    _planner_payload(
        [
            _task("task-a", executor_id="planner"),
            _task("task-b", executor_id="search", dependencies=["task-missing"]),
        ]
    )
)

CYCLE_TWO_NODE_PLANNER_JSON = json.dumps(
    _planner_payload(
        [
            _task("task-a", executor_id="planner", dependencies=["task-b"]),
            _task("task-b", executor_id="search", dependencies=["task-a"]),
        ]
    )
)


class PlannerPayloadContractTests(unittest.TestCase):

    def setUp(self):
        self.catalog = make_test_executor_catalog()
        self.contract = PlannerPayloadContract(
            executor_catalog=self.catalog,
        )
        self.parser = StructuredOutputParser()

    def test_unknown_executor_id_is_contract_violation(self):
        payload = self.parser.parse(LEGACY_UNKNOWN_EXECUTOR_PLANNER_JSON)

        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("ResearchLead", self.contract.last_validation_error)

    def test_missing_required_field_is_contract_violation(self):
        payload = {"goal": "Evaluate brand awareness.", "stages": []}

        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("Missing required field 'name'", self.contract.last_validation_error)

    def test_accepts_valid_linear_dag(self):
        payload = self.parser.parse(LEGACY_PLANNER_JSON)

        self.assertTrue(self.contract.accepts(payload))
        self.assertEqual(self.contract.last_validation_error, "")

    def test_accepts_valid_disconnected_dag(self):
        payload = _planner_payload(
            [
                _task("task-a", executor_id="planner"),
                _task("task-b", executor_id="search", dependencies=["task-a"]),
                _task("task-c", executor_id="planner"),
                _task("task-d", executor_id="search", dependencies=["task-c"]),
            ]
        )

        self.assertTrue(self.contract.accepts(payload))

    def test_accepts_orphan_task(self):
        payload = _planner_payload(
            [
                _task("task-a", executor_id="planner"),
                _task("task-b", executor_id="search", dependencies=["task-a"]),
                _task("task-orphan", executor_id="planner"),
            ]
        )

        self.assertTrue(self.contract.accepts(payload))

    def test_rejects_duplicate_task_ids(self):
        payload = _planner_payload(
            [
                _task("task-a", executor_id="planner"),
                _task("task-a", executor_id="search"),
            ]
        )

        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("Duplicate task id", self.contract.last_validation_error)
        self.assertIn("task-a", self.contract.last_validation_error)

    def test_rejects_unknown_dependency(self):
        payload = _planner_payload(
            [
                _task("task-a", executor_id="planner"),
                _task("task-b", executor_id="search", dependencies=["task-missing"]),
            ]
        )

        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("task-b", self.contract.last_validation_error)
        self.assertIn("task-missing", self.contract.last_validation_error)
        self.assertIn("unknown task", self.contract.last_validation_error.lower())

    def test_rejects_self_dependency(self):
        payload = _planner_payload(
            [
                _task("task-a", executor_id="planner", dependencies=["task-a"]),
                _task("task-b", executor_id="search"),
            ]
        )

        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("task-a", self.contract.last_validation_error)
        self.assertIn("depend on itself", self.contract.last_validation_error.lower())

    def test_rejects_two_node_cycle(self):
        payload = _planner_payload(
            [
                _task("task-a", executor_id="planner", dependencies=["task-b"]),
                _task("task-b", executor_id="search", dependencies=["task-a"]),
            ]
        )

        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("circular", self.contract.last_validation_error.lower())

    def test_rejects_three_node_cycle(self):
        payload = _planner_payload(
            [
                _task("task-a", executor_id="planner", dependencies=["task-b"]),
                _task("task-b", executor_id="search", dependencies=["task-c"]),
                _task("task-c", executor_id="planner", dependencies=["task-a"]),
            ]
        )

        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("circular", self.contract.last_validation_error.lower())

    def test_accepts_duplicate_dependency_edges(self):
        payload = _planner_payload(
            [
                _task("task-a", executor_id="planner"),
                {
                    "id": "task-b",
                    "title": "Task task-b",
                    "description": "Description for task-b.",
                    "executor_id": "search",
                    "dependencies": ["task-a", "task-a"],
                },
            ]
        )

        self.assertTrue(self.contract.accepts(payload))

    def test_valid_graph_with_valid_executors_is_accepted(self):
        payload = _planner_payload(
            [
                _task("task-a", executor_id="planner"),
                _task("task-b", executor_id="search", dependencies=["task-a"]),
            ]
        )

        self.assertTrue(self.contract.accepts(payload))

    def test_dependency_graph_validation_raises_planner_parser_error(self):
        payload = _planner_payload(
            [
                _task("task-a", executor_id="planner"),
                _task("task-b", executor_id="search", dependencies=["task-missing"]),
            ]
        )

        with patch.object(
            self.contract,
            "_validate_executor_ids",
        ) as validate_executors:
            self.assertFalse(self.contract.accepts(payload))

        validate_executors.assert_called_once()
        self.assertIn("unknown task", self.contract.last_validation_error.lower())

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
            LLMResponse(content=LEGACY_UNKNOWN_EXECUTOR_PLANNER_JSON),
            LLMResponse(content=LEGACY_PLANNER_JSON, finish_reason="stop"),
        ]

        payload = self.generator.generate(
            self.prompt,
            payload_contract=self.contract,
        )

        self.assertEqual(payload["name"], "Brand Health Workflow")
        self.assertEqual(self.llm_client.generate.call_count, 2)

    def test_unknown_dependency_allows_structured_output_retry(self):
        self.llm_client.generate.side_effect = [
            LLMResponse(content=UNKNOWN_DEPENDENCY_PLANNER_JSON),
            LLMResponse(content=LEGACY_PLANNER_JSON, finish_reason="stop"),
        ]

        payload = self.generator.generate(
            self.prompt,
            payload_contract=self.contract,
        )

        self.assertEqual(payload["name"], "Brand Health Workflow")
        self.assertEqual(self.llm_client.generate.call_count, 2)

    def test_cycle_allows_structured_output_retry(self):
        self.llm_client.generate.side_effect = [
            LLMResponse(content=CYCLE_TWO_NODE_PLANNER_JSON),
            LLMResponse(content=LEGACY_PLANNER_JSON, finish_reason="stop"),
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
                content=LEGACY_PLANNER_JSON,
            )

            with self.assertRaises(RuntimeError):
                self.generator.generate(
                    self.prompt,
                    payload_contract=broken_contract,
                )

        self.llm_client.generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
