from agents.base_agent import BaseAgent

from application.services.planner_service import PlannerService
from runtime.execution_state import ExecutionState
from runtime.research_context import ResearchContext


class PlannerAgent(BaseAgent):
    """
    Агент планирования исследования.
    """

    def __init__(self):
        super().__init__("planner")
        self.planner = PlannerService()

    def run(
        self,
        context: ResearchContext,
    ) -> ResearchContext:

        context.state = ExecutionState.RUNNING

        print(f"PlannerAgent started: {context.project.name}")

        context.plan = self.planner.build_plan(context.project)

        print(f"Plan contains {len(context.plan)} task(s)")

        return context