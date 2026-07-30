import unittest
from unittest.mock import Mock

from agents.planner.planner_agent import PlannerAgent

from application.factories.research_plan_factory import ResearchPlanFactory
from application.parsers.planner_response_parser import PlannerResponseParser
from application.planner.payload_contract import PlannerPayloadContract
from tests.helpers.executor_catalog import make_test_executor_catalog
from application.planner.service import PlannerServiceImpl
from application.planner.workflow_template_mapper import (
    ResearchPlanWorkflowTemplateMapper,
)
from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.structured_output.generator import StructuredOutputGenerator
from application.structured_output.parser import StructuredOutputParser

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from domain.planning.research_plan import ResearchPlan
from domain.project import Project
from domain.project_brief import ProjectBrief
from domain.workflow_run import WorkflowRun
from domain.workflow_template import WorkflowTemplate

from infrastructure.llm.llm_client import LLMClient

from runtime.workflow_context import WorkflowContext

from tests.fixtures.planner_responses import (
    MARKDOWN_PLANNER_JSON,
    TRUNCATED_PLANNER_JSON,
    VALID_PLANNER_JSON,
)


class PlannerAgentTests(unittest.TestCase):

    def setUp(self):
        self.planner_service = PlannerServiceImpl(
            response_parser=PlannerResponseParser(),
            plan_factory=ResearchPlanFactory(),
        )
        self.workflow_mapper = ResearchPlanWorkflowTemplateMapper()
        self.catalog = make_test_executor_catalog()
        self.payload_contract = PlannerPayloadContract(
            executor_catalog=self.catalog,
        )
        self.prompt_builder = Mock(spec=PlannerPromptBuilder)
        self.prompt_builder.build.return_value = Prompt(
            system="Planner system",
            user="Planner user",
        )
        self.llm_client = Mock(spec=LLMClient)
        self.structured_output_generator = StructuredOutputGenerator(
            llm_client=self.llm_client,
            parser=StructuredOutputParser(),
            executor_catalog=self.catalog,
        )

        self.agent = PlannerAgent(
            planner_service=self.planner_service,
            workflow_mapper=self.workflow_mapper,
            prompt_builder=self.prompt_builder,
            structured_output_generator=self.structured_output_generator,
            payload_contract=self.payload_contract,
        )

        self.project = Project(
            id="project-1",
            name="Brand Health 2026",
        )
        self.project.brief = ProjectBrief(
            client="Purina",
            project_title="Brand Health 2026",
            business_problem="Assess market position.",
            research_goal="Evaluate brand awareness.",
        )

        self.context = WorkflowContext(
            workflow_run=WorkflowRun(id="planning"),
            project=self.project,
        )

    def test_run_sets_workflow_template_from_mock_llm(self):
        self.llm_client.generate.return_value = LLMResponse(
            content=VALID_PLANNER_JSON,
        )

        result = self.agent.run(self.context)

        self.assertIsNotNone(result.workflow_template)
        self.assertEqual(
            result.workflow_template.name,
            "Brand Health Workflow",
        )
        self.assertEqual(
            len(result.workflow_template.task_definitions),
            2,
        )
        self.llm_client.generate.assert_called_once()

    def test_run_accepts_markdown_wrapped_llm_response(self):
        self.llm_client.generate.return_value = LLMResponse(
            content=MARKDOWN_PLANNER_JSON,
        )

        result = self.agent.run(self.context)

        self.assertEqual(
            result.workflow_template.name,
            "Brand Health Workflow",
        )

    def test_run_retries_after_truncated_first_response(self):
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

        result = self.agent.run(self.context)

        self.assertEqual(
            result.workflow_template.name,
            "Brand Health Workflow",
        )
        self.assertEqual(result.execution_metadata["state"], "completed")
        self.assertEqual(self.llm_client.generate.call_count, 2)

    def test_agent_accepts_planner_service_protocol(self):
        planner_service = Mock()
        planner_service.create_plan.return_value = ResearchPlan.create(
            name="Mock Plan",
            goal="Mock goal",
        )

        workflow_mapper = Mock()
        workflow_mapper.from_research_plan.return_value = WorkflowTemplate(
            id="template-1",
            name="Mock Plan",
        )

        agent = PlannerAgent(
            planner_service=planner_service,
            workflow_mapper=workflow_mapper,
            prompt_builder=self.prompt_builder,
            structured_output_generator=self.structured_output_generator,
            payload_contract=self.payload_contract,
        )

        self.llm_client.generate.return_value = LLMResponse(
            content=VALID_PLANNER_JSON,
        )

        agent.run(self.context)

        planner_service.create_plan.assert_called_once()
        workflow_mapper.from_research_plan.assert_called_once()

    def test_agent_passes_research_plan_to_workflow_mapper(self):
        planner_service = Mock()
        research_plan = ResearchPlan.create(
            name="Mock Plan",
            goal="Mock goal",
        )
        planner_service.create_plan.return_value = research_plan

        workflow_mapper = Mock()
        workflow_mapper.from_research_plan.return_value = WorkflowTemplate(
            id="template-1",
            name="Mock Plan",
        )

        agent = PlannerAgent(
            planner_service=planner_service,
            workflow_mapper=workflow_mapper,
            prompt_builder=self.prompt_builder,
            structured_output_generator=self.structured_output_generator,
            payload_contract=self.payload_contract,
        )

        self.llm_client.generate.return_value = LLMResponse(
            content='{"name":"x","goal":"y","methodology":"m","stages":[{"id":"s1","name":"S","description":"d","tasks":[{"id":"t1","title":"T","description":"d","executor_id":"planner","dependencies":[]},{"id":"t2","title":"T2","description":"d","executor_id":"search","dependencies":["t1"]}]}],"metadata":{}}',
        )

        agent.run(self.context)

        workflow_mapper.from_research_plan.assert_called_once_with(
            research_plan,
            self.project,
        )


if __name__ == "__main__":
    unittest.main()
