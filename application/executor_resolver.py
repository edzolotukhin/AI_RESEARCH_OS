from application.contracts.base_executor import BaseExecutor


class ExecutorResolver:
    """
    Возвращает готовый Executor по executor_id.

    Изолирует Application Layer
    от конкретной реализации Registry.
    """

    def __init__(self, registry):
        self._registry = registry

    def resolve(
        self,
        executor_id: str,
    ) -> BaseExecutor:

        executor_cls = self._registry.agents.get(executor_id)

        if executor_cls is None:
            raise ValueError(
                f"Executor '{executor_id}' is not registered."
            )

        return executor_cls()