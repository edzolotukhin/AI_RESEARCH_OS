from agents.base_agent import BaseAgent

from application.planner.contracts import PlannerService, WorkflowTemplateMapper
from application.planner.payload_contract import PlannerPayloadContract
from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.structured_output.generator import StructuredOutputGenerator

from runtime.workflow_context import WorkflowContext


class PlannerAgent(BaseAgent):
    """
    Агент планирования исследования.
    """

    def __init__(
        self,
        planner_service: PlannerService,
        workflow_mapper: WorkflowTemplateMapper,
        prompt_builder: PlannerPromptBuilder,
        structured_output_generator: StructuredOutputGenerator,
        payload_contract: PlannerPayloadContract,
    ) -> None:
        super().__init__("planner")

        self._planner_service = planner_service
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

        plan_data = self._structured_output_generator.generate(
            prompt,
            payload_contract=self._payload_contract,
        )

        research_plan = self._planner_service.create_plan(
            context.project,
            plan_data,
        )

        context.workflow_template = (
            self._workflow_mapper.from_research_plan(
                research_plan,
                context.project,
            )
        )

        context.execution_metadata["state"] = "completed"

        return context
