from agents.planner.planner_agent import PlannerAgent

from loaders.base_loader import BaseLoader


class AgentLoader(BaseLoader):
    """
    Регистрирует встроенных AI-агентов.
    """

    def __init__(self, registry):
        self.registry = registry

    def load(self):
        """
        Регистрация встроенных AI-агентов.
        """

        self.registry.agents.register(
            "planner",
            PlannerAgent
        )