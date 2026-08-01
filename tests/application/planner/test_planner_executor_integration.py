import unittest
from unittest.mock import Mock

from application.exceptions.executor_error import ExecutorNotFoundError
from application.exceptions.structured_output_error import StructuredOutputError
from application.planner.payload_contract import PlannerPayloadContract
from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.prompts.file_template_loader import FileTemplateLoader
from application.prompts.python_format_prompt_renderer import (
    PythonFormatPromptRenderer,
)
from application.structured_output.correction_prompt import (
    PLANNER_PAYLOAD_SCHEMA,
    StructuredOutputCorrectionPromptBuilder,
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


class PlannerExecutorIntegrationTests(unittest.TestCase):

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

    def test_valid_executor_id_is_accepted(self):
        self.assertTrue(
            self.contract.accepts(
                StructuredOutputParser().parse(VALID_PLANNER_JSON),
            )
        )

    def test_unknown_executor_id_is_rejected(self):
        payload = StructuredOutputParser().parse(
            UNKNOWN_EXECUTOR_PLANNER_JSON,
        )

        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("ResearchLead", self.contract.last_validation_error)
        self.assertIn("Allowed executor IDs", self.contract.last_validation_error)

    def test_unknown_executor_id_triggers_correction_retry(self):
        self.llm_client.generate.side_effect = [
            LLMResponse(content=UNKNOWN_EXECUTOR_PLANNER_JSON),
            LLMResponse(content=VALID_PLANNER_JSON, finish_reason="stop"),
        ]

        payload = self.generator.generate(
            self.prompt,
            payload_contract=self.contract,
        )

        self.assertEqual(payload["stages"][0]["tasks"][0]["executor_id"], "planner")
        self.assertEqual(self.llm_client.generate.call_count, 2)

    def test_three_unknown_executor_attempts_raise_structured_output_error(self):
        self.llm_client.generate.side_effect = [
            LLMResponse(content=UNKNOWN_EXECUTOR_PLANNER_JSON),
            LLMResponse(content=UNKNOWN_EXECUTOR_PLANNER_JSON),
            LLMResponse(content=UNKNOWN_EXECUTOR_PLANNER_JSON),
        ]

        with self.assertRaises(StructuredOutputError) as ctx:
            self.generator.generate(
                self.prompt,
                payload_contract=self.contract,
            )

        self.assertEqual(ctx.exception.attempts, 3)
        self.assertEqual(ctx.exception.stage, "contract")

    def test_correction_prompt_contains_allowed_executor_ids(self):
        builder = StructuredOutputCorrectionPromptBuilder()
        error = StructuredOutputError(
            "No JSON candidate satisfies the payload contract.",
            stage="contract",
            candidate_count=1,
            syntax_valid_count=1,
            contract_valid_count=0,
        )

        correction = builder.build(
            original_prompt=self.prompt,
            invalid_response=LLMResponse(content=UNKNOWN_EXECUTOR_PLANNER_JSON),
            error=error,
            payload_schema=PLANNER_PAYLOAD_SCHEMA,
            truncated=False,
            allowed_executor_ids=self.catalog.executor_ids,
            contract_validation_message="Unknown executor_id 'ResearchLead'",
        )

        self.assertIn("ALLOWED EXECUTOR IDS", correction.user)
        self.assertIn("planner", correction.user)
        self.assertIn("search", correction.user)
        self.assertIn("Unknown executor_id 'ResearchLead'", correction.user)


class PlannerPromptExecutorTests(unittest.TestCase):

    def test_prompt_contains_available_executor_ids(self):
        catalog = make_test_executor_catalog()
        builder = PlannerPromptBuilder(
            template_loader=FileTemplateLoader(),
            prompt_renderer=PythonFormatPromptRenderer(),
            executor_catalog=catalog,
        )

        from domain.project import Project
        from domain.workflow_run import WorkflowRun
        from runtime.workflow_context import WorkflowContext
        from tests.fixtures.research_brief import sample_research_brief

        project = Project(id="1", name="Test")
        project.research_brief = sample_research_brief()
        context = WorkflowContext(
            workflow_run=WorkflowRun(id="planning"),
            project=project,
        )

        prompt = builder.build(context)

        self.assertIn("Available executors:", prompt.system)
        self.assertIn("- planner:", prompt.system)
        self.assertIn("- search:", prompt.system)
        self.assertIn("executor_id must exactly match", prompt.system)
        self.assertIn("Do not create new executor IDs", prompt.user)
        self.assertIn("executor_id", prompt.user)
        self.assertNotIn("suggested_agent", prompt.system)
        self.assertNotIn("suggested_agent", prompt.user)


class ExecutorResolverStrictnessTests(unittest.TestCase):

    def test_unknown_executor_id_includes_available_ids(self):
        from application.executor_resolver import ExecutorResolver
        from domain.value_objects.executor_type import ExecutorType
        from registry.agent_registry import AgentRegistry
        from registry.api_executor_registry import APIExecutorRegistry
        from registry.human_executor_registry import HumanExecutorRegistry
        from registry.tool_registry import ToolRegistry
        from tests.helpers.workflow_run_builder import make_task

        agent_registry = AgentRegistry()
        agent_registry.register("planner", Mock())

        resolver = ExecutorResolver(
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            human_registry=HumanExecutorRegistry(),
            api_registry=APIExecutorRegistry(),
        )

        task = make_task(
            "task-1",
            executor_id="ResearchLead",
            executor_type=ExecutorType.AGENT,
        )

        with self.assertRaises(ExecutorNotFoundError) as ctx:
            resolver.resolve(task)

        self.assertEqual(ctx.exception.executor_id, "ResearchLead")
        self.assertEqual(ctx.exception.task_id, "task-1")
        self.assertEqual(ctx.exception.available_executor_ids, ("planner",))


if __name__ == "__main__":
    unittest.main()
