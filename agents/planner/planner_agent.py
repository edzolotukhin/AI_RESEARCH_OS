from agents.base_agent import BaseAgent

from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.services.planner_service import PlannerService

from infrastructure.llm.llm_client import LLMClient

from runtime.execution_state import ExecutionState
from runtime.research_context import ResearchContext


class PlannerAgent(BaseAgent):
    """
    Агент планирования исследования.
    """

    def __init__(
        self,
        planner_service: PlannerService,
        prompt_builder: PlannerPromptBuilder,
        llm_client: LLMClient,
    ):
        super().__init__("planner")

        self._planner_service = planner_service
        self._prompt_builder = prompt_builder
        self._llm_client = llm_client

    def run(
        self,
        context: ResearchContext,
    ) -> ResearchContext:

        context.state = ExecutionState.RUNNING

        prompt = self._prompt_builder.build(context)

        response = self._llm_client.generate(prompt)

        context.workflow_template = (
            self._planner_service.build_workflow(
                context.project,
                response,
            )
        )

        return context