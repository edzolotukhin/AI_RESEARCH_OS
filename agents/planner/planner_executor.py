from application.executors.agent_executor import AgentExecutor

from agents.planner.planner_agent import PlannerAgent


class PlannerExecutor(AgentExecutor):
    """
    Reference AI executor implementation.

    Thin wrapper around AgentExecutor for PlannerAgent registration.
    """

    def __init__(
        self,
        agent: PlannerAgent,
    ) -> None:
        super().__init__(agent)
