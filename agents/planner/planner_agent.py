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

        context.workflow_template = self.planner.build_workflow(
            context.project,
        )

        print(
            f"Workflow contains "
            f"{len(context.workflow_template.task_definitions)} task(s)"
        )

        return context