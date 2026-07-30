from registry.base_registry import BaseRegistry


class HumanExecutorRegistry(BaseRegistry):
    """
    Registry human-in-the-loop executors.
    """

    def register(
        self,
        executor_id: str,
        executor,
    ) -> None:
        super().register(executor_id, executor)

    def get(
        self,
        executor_id: str,
    ):
        return super().get(executor_id)

    def exists(
        self,
        executor_id: str,
    ) -> bool:
        return super().exists(executor_id)
