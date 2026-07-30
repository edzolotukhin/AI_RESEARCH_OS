from application.contracts.base_executor import BaseExecutor

from loaders.base_loader import BaseLoader


class AgentLoader(BaseLoader):
    """
    Registers agent executors into the agent registry.
    """

    def __init__(
        self,
        registry,
        executors: dict[str, BaseExecutor],
    ) -> None:
        self.registry = registry
        self._executors = executors

    def load(self) -> None:
        for executor_id, executor in self._executors.items():
            self.registry.agents.register(
                executor_id,
                executor,
            )
