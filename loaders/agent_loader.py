from agents.planner.planner_executor import PlannerExecutor

from loaders.base_loader import BaseLoader


class AgentLoader(BaseLoader):
    """
    Регистрирует встроенных Executor'ов.
    """

    def __init__(self, registry):
        self.registry = registry

    def load(self):
        """
        Регистрация встроенных Executor'ов.
        """

        self.registry.agents.register(
            "planner",
            PlannerExecutor,
        )