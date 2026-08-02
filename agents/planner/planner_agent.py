from agents.base_agent import BaseAgent

from application.planner.contracts import PlannerDesignService, ResearchDesignWorkflowMapperProtocol
from application.planner.research_design_payload_contract import (
    ResearchDesignPayloadContract,
)
from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.structured_output.generator import StructuredOutputGenerator

from runtime.workflow_context import WorkflowContext


class PlannerAgent(BaseAgent):
    """
    Single planning authority: transforms ResearchBrief into ResearchDesign
    and deterministically derives WorkflowTemplate.
    """

    def __init__(
        self,
        planner_design_service: PlannerDesignService,
        workflow_mapper: ResearchDesignWorkflowMapperProtocol,
        prompt_builder: PlannerPromptBuilder,
        structured_output_generator: StructuredOutputGenerator,
        payload_contract: ResearchDesignPayloadContract,
    ) -> None:
        super().__init__("planner")

        self._planner_design_service = planner_design_service
        self._workflow_mapper = workflow_mapper
        self._prompt_builder = prompt_builder
        self._structured_output_generator = structured_output_generator
        self._payload_contract = payload_contract

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        context.execution_metadata["agent"] = self.name
        context.execution_metadata["state"] = "running"

        prompt = self._prompt_builder.build(context)

        design_data = self._structured_output_generator.generate(
            prompt,
            payload_contract=self._payload_contract,
        )

        research_design = self._planner_design_service.create_design(
            context.project,
            design_data,
        )

        context.workflow_template = (
            self._workflow_mapper.from_research_design(
                research_design,
                context.project,
            )
        )

        context.execution_metadata["state"] = "completed"

        return context
