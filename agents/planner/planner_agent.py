from agents.base_agent import BaseAgent

from runtime.execution_state import ExecutionState


class PlannerAgent(BaseAgent):
    """
    Агент планирования исследования.
    """

    def __init__(self):
        super().__init__("planner")

    def run(self, context):
        context.state = ExecutionState.RUNNING

        print(f"PlannerAgent started: {context.project.name}")

        return context