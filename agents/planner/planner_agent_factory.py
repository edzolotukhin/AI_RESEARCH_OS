from agents.planner.planner_agent import PlannerAgent

from application.planner.contracts import PlannerDesignService, ResearchDesignWorkflowMapperProtocol
from application.planner.research_design_payload_contract import (
    ResearchDesignPayloadContract,
)
from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.structured_output.generator import StructuredOutputGenerator


class PlannerAgentFactory:
    """Factory for PlannerAgent."""

    def __init__(
        self,
        planner_design_service: PlannerDesignService,
        workflow_mapper: ResearchDesignWorkflowMapperProtocol,
        prompt_builder: PlannerPromptBuilder,
        structured_output_generator: StructuredOutputGenerator,
        payload_contract: ResearchDesignPayloadContract,
    ) -> None:
        self._planner_design_service = planner_design_service
        self._workflow_mapper = workflow_mapper
        self._prompt_builder = prompt_builder
        self._structured_output_generator = structured_output_generator
        self._payload_contract = payload_contract

    def create(self) -> PlannerAgent:
        return PlannerAgent(
            planner_design_service=self._planner_design_service,
            workflow_mapper=self._workflow_mapper,
            prompt_builder=self._prompt_builder,
            structured_output_generator=self._structured_output_generator,
            payload_contract=self._payload_contract,
        )
