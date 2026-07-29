from registry.base_registry import BaseRegistry


class AgentRegistry(BaseRegistry):
    """
    Registry AI-агентов.
    """

    def __init__(self):
        self._executors = {}

    def register(
        self,
        executor_id: str,
        executor,
    ) -> None:

        self._executors[executor_id] = executor

    def get(
        self,
        executor_id: str,
    ):

        return self._executors.get(executor_id)

    def exists(
        self,
        executor_id: str,
    ) -> bool:

        return executor_id in self._executors

    def clear(self) -> None:

        self._executors.clear()