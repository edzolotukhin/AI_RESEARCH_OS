from application.contracts.base_executor import BaseExecutor


class ExecutorResolver:
    """
    Находит класс исполнителя по executor_id.

    Resolver изолирует Application Layer
    от конкретной реализации Registry.
    """

    def __init__(self, registry):
        self._registry = registry

    def resolve(
        self,
        executor_id: str,
    ) -> type[BaseExecutor]:
        return self._registry.agents.get(executor_id)