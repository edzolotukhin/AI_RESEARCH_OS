from domain.task import Task

from application.contracts.base_executor import BaseExecutor

from runtime.research_context import ResearchContext

from agents.planner.planner_agent import PlannerAgent


class PlannerExecutor(BaseExecutor):
    """
    Выполняет задачу построения Workflow.
    """

    def __init__(self):
        self._agent = PlannerAgent()

    def run(
        self,
        task: Task,
        context: ResearchContext,
    ) -> ResearchContext:

        return self._agent.run(context)