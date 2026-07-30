from agents.planner.planner_agent import PlannerAgent

from application.planner.contracts import PlannerService, WorkflowTemplateMapper
from application.planner.payload_contract import PlannerPayloadContract
from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.structured_output.generator import StructuredOutputGenerator


class PlannerAgentFactory:
    """
    Factory создания PlannerAgent.
    """

    def __init__(
        self,
        planner_service: PlannerService,
        workflow_mapper: WorkflowTemplateMapper,
        prompt_builder: PlannerPromptBuilder,
        structured_output_generator: StructuredOutputGenerator,
        payload_contract: PlannerPayloadContract,
    ) -> None:
        self._planner_service = planner_service
        self._workflow_mapper = workflow_mapper
        self._prompt_builder = prompt_builder
        self._structured_output_generator = structured_output_generator
        self._payload_contract = payload_contract

    def create(self) -> PlannerAgent:

        return PlannerAgent(
            planner_service=self._planner_service,
            workflow_mapper=self._workflow_mapper,
            prompt_builder=self._prompt_builder,
            structured_output_generator=self._structured_output_generator,
            payload_contract=self._payload_contract,
        )
