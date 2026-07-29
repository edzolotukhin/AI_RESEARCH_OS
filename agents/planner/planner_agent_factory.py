from agents.planner.planner_agent import PlannerAgent

from application.planner.contracts import PlannerService, WorkflowTemplateMapper
from application.planner.payload_contract import PlannerPayloadContract
from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.structured_output.parser import StructuredOutputParser

from infrastructure.llm.llm_client import LLMClient


class PlannerAgentFactory:
    """
    Factory создания PlannerAgent.
    """

    def __init__(
        self,
        planner_service: PlannerService,
        workflow_mapper: WorkflowTemplateMapper,
        prompt_builder: PlannerPromptBuilder,
        llm_client: LLMClient,
        structured_output_parser: StructuredOutputParser,
        payload_contract: PlannerPayloadContract,
    ) -> None:
        self._planner_service = planner_service
        self._workflow_mapper = workflow_mapper
        self._prompt_builder = prompt_builder
        self._llm_client = llm_client
        self._structured_output_parser = structured_output_parser
        self._payload_contract = payload_contract

    def create(self) -> PlannerAgent:

        return PlannerAgent(
            planner_service=self._planner_service,
            workflow_mapper=self._workflow_mapper,
            prompt_builder=self._prompt_builder,
            llm_client=self._llm_client,
            structured_output_parser=self._structured_output_parser,
            payload_contract=self._payload_contract,
        )
