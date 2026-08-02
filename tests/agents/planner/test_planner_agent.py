import unittest
from unittest.mock import Mock

from agents.planner.planner_agent import PlannerAgent

from application.factories.research_design_factory import ResearchDesignFactory
from application.parsers.research_design_parser import ResearchDesignParser
from application.planner.design_service import PlannerDesignServiceImpl
from application.planner.research_design_payload_contract import (
    ResearchDesignPayloadContract,
)
from application.planner.research_design_workflow_mapper import (
    ResearchDesignWorkflowMapper,
)
from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.structured_output.generator import StructuredOutputGenerator
from application.structured_output.parser import StructuredOutputParser

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from domain.planning.research_design import ResearchDesign
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.workflow_run import WorkflowRun
from domain.workflow_template import WorkflowTemplate

from infrastructure.llm.llm_client import LLMClient

from runtime.workflow_context import WorkflowContext

from tests.fixtures.planner_responses import (
    MARKDOWN_PLANNER_JSON,
    TRUNCATED_PLANNER_JSON,
    VALID_RESEARCH_DESIGN_JSON,
)


class PlannerAgentTests(unittest.TestCase):

    def setUp(self):
        self.planner_design_service = PlannerDesignServiceImpl(
            response_parser=ResearchDesignParser(),
            design_factory=ResearchDesignFactory(),
        )
        self.workflow_mapper = ResearchDesignWorkflowMapper()
        self.payload_contract = ResearchDesignPayloadContract()
        self.prompt_builder = Mock(spec=PlannerPromptBuilder)
        self.prompt_builder.build.return_value = Prompt(
            system="Planner system",
            user="Planner user",
        )
        self.llm_client = Mock(spec=LLMClient)
        self.structured_output_generator = StructuredOutputGenerator(
            llm_client=self.llm_client,
            parser=StructuredOutputParser(),
        )

        self.agent = PlannerAgent(
            planner_design_service=self.planner_design_service,
            workflow_mapper=self.workflow_mapper,
            prompt_builder=self.prompt_builder,
            structured_output_generator=self.structured_output_generator,
            payload_contract=self.payload_contract,
        )

        self.project = Project(
            id="project-1",
            name="Brand Health 2026",
        )
        self.project.research_brief = ResearchBrief.from_dict(
            {
                "title": "Brand Health 2026",
                "business_question": "Assess market position.",
                "objectives": ["Evaluate brand awareness."],
            },
        )

        self.context = WorkflowContext(
            workflow_run=WorkflowRun(id="planning"),
            project=self.project,
        )

    def test_run_sets_workflow_template_from_mock_llm(self):
        self.llm_client.generate.return_value = LLMResponse(
            content=VALID_RESEARCH_DESIGN_JSON,
        )

        result = self.agent.run(self.context)

        self.assertIsNotNone(result.workflow_template)
        self.assertEqual(
            result.workflow_template.name,
            "Brand Health 2026",
        )
        self.assertEqual(
            len(result.workflow_template.task_definitions),
            3,
        )
        self.assertIsNotNone(result.workflow_template.research_design_snapshot)
        self.llm_client.generate.assert_called_once()

    def test_run_accepts_markdown_wrapped_llm_response(self):
        self.llm_client.generate.return_value = LLMResponse(
            content=MARKDOWN_PLANNER_JSON,
        )

        result = self.agent.run(self.context)

        self.assertEqual(
            result.workflow_template.name,
            "Brand Health 2026",
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
                content=VALID_RESEARCH_DESIGN_JSON,
                finish_reason="stop",
            ),
        ]

        result = self.agent.run(self.context)

        self.assertEqual(
            result.workflow_template.name,
            "Brand Health 2026",
        )
        self.assertEqual(result.execution_metadata["state"], "completed")
        self.assertEqual(self.llm_client.generate.call_count, 2)

    def test_agent_accepts_planner_design_service_protocol(self):
        planner_design_service = Mock()
        planner_design_service.create_design.return_value = ResearchDesign(
            id="design-1",
            research_questions=(),
            source_strategy=("official statistics",),
            analysis_plan=("competitor comparison",),
            deliverable_plan=("executive summary",),
        )

        workflow_mapper = Mock()
        workflow_mapper.from_research_design.return_value = WorkflowTemplate(
            id="template-1",
            name="Mock Plan",
        )

        agent = PlannerAgent(
            planner_design_service=planner_design_service,
            workflow_mapper=workflow_mapper,
            prompt_builder=self.prompt_builder,
            structured_output_generator=self.structured_output_generator,
            payload_contract=self.payload_contract,
        )

        self.llm_client.generate.return_value = LLMResponse(
            content=VALID_RESEARCH_DESIGN_JSON,
        )

        agent.run(self.context)

        planner_design_service.create_design.assert_called_once()
        workflow_mapper.from_research_design.assert_called_once()

    def test_agent_passes_research_design_to_workflow_mapper(self):
        planner_design_service = Mock()
        research_design = ResearchDesign(
            id="design-1",
            research_questions=(),
            source_strategy=("official statistics",),
            analysis_plan=("analysis",),
            deliverable_plan=("summary",),
        )
        planner_design_service.create_design.return_value = research_design

        workflow_mapper = Mock()
        workflow_mapper.from_research_design.return_value = WorkflowTemplate(
            id="template-1",
            name="Mock Plan",
        )

        agent = PlannerAgent(
            planner_design_service=planner_design_service,
            workflow_mapper=workflow_mapper,
            prompt_builder=self.prompt_builder,
            structured_output_generator=self.structured_output_generator,
            payload_contract=self.payload_contract,
        )

        self.llm_client.generate.return_value = LLMResponse(
            content=VALID_RESEARCH_DESIGN_JSON,
        )

        agent.run(self.context)

        workflow_mapper.from_research_design.assert_called_once_with(
            research_design,
            self.project,
        )


if __name__ == "__main__":
    unittest.main()
