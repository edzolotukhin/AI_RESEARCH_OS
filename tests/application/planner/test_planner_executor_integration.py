import unittest
from unittest.mock import Mock

from application.exceptions.structured_output_error import StructuredOutputError
from application.planner.research_design_payload_contract import (
    ResearchDesignPayloadContract,
)
from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.prompts.file_template_loader import FileTemplateLoader
from application.prompts.python_format_prompt_renderer import (
    PythonFormatPromptRenderer,
)
from application.structured_output.correction_prompt import (
    RESEARCH_DESIGN_PAYLOAD_SCHEMA,
    StructuredOutputCorrectionPromptBuilder,
)
from application.structured_output.generator import StructuredOutputGenerator
from application.structured_output.parser import StructuredOutputParser

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt

from tests.fixtures.planner_responses import (
    INVALID_DUPLICATE_QUESTION_JSON,
    UNKNOWN_EXECUTOR_PLANNER_JSON,
    VALID_RESEARCH_DESIGN_JSON,
)
from tests.helpers.executor_catalog import make_test_executor_catalog


class PlannerExecutorIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.contract = ResearchDesignPayloadContract()
        self.llm_client = Mock()
        self.generator = StructuredOutputGenerator(
            llm_client=self.llm_client,
            parser=StructuredOutputParser(),
        )
        self.prompt = Prompt(system="System", user="User")

    def test_valid_design_is_accepted(self):
        self.assertTrue(
            self.contract.accepts(
                StructuredOutputParser().parse(VALID_RESEARCH_DESIGN_JSON),
            )
        )

    def test_empty_questions_is_rejected(self):
        payload = StructuredOutputParser().parse(UNKNOWN_EXECUTOR_PLANNER_JSON)

        self.assertFalse(self.contract.accepts(payload))
        self.assertIn("research_questions", self.contract.last_validation_error)

    def test_invalid_design_triggers_correction_retry(self):
        self.llm_client.generate.side_effect = [
            LLMResponse(content=UNKNOWN_EXECUTOR_PLANNER_JSON),
            LLMResponse(content=VALID_RESEARCH_DESIGN_JSON, finish_reason="stop"),
        ]

        payload = self.generator.generate(
            self.prompt,
            payload_contract=self.contract,
        )

        self.assertEqual(len(payload["research_questions"]), 2)
        self.assertEqual(self.llm_client.generate.call_count, 2)

    def test_three_invalid_attempts_raise_structured_output_error(self):
        self.llm_client.generate.side_effect = [
            LLMResponse(content=UNKNOWN_EXECUTOR_PLANNER_JSON),
            LLMResponse(content=UNKNOWN_EXECUTOR_PLANNER_JSON),
            LLMResponse(content=UNKNOWN_EXECUTOR_PLANNER_JSON),
        ]

        with self.assertRaises(StructuredOutputError):
            self.generator.generate(
                self.prompt,
                payload_contract=self.contract,
            )


class PlannerPromptExecutorTests(unittest.TestCase):

    def test_prompt_contains_research_design_schema(self):
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

        self.assertIn("research_questions", prompt.system)
        self.assertIn("source_strategy", prompt.system)
        self.assertIn("Evaluate brand awareness.", prompt.user)


class PlannerCorrectionPromptTests(unittest.TestCase):

    def test_correction_prompt_contains_design_schema(self):
        builder = StructuredOutputCorrectionPromptBuilder()
        correction = builder.build(
            original_prompt=Prompt(system="System", user="User"),
            invalid_response=LLMResponse(content="{}"),
            error=StructuredOutputError("invalid"),
            payload_schema=RESEARCH_DESIGN_PAYLOAD_SCHEMA,
            truncated=False,
        )

        self.assertIn("research_questions", correction.user)


if __name__ == "__main__":
    unittest.main()
