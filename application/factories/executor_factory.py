from application.contracts.base_executor import BaseExecutor


class ExecutorFactory:
    """
    Создает экземпляры исполнителей.
    """

    def create(
        self,
        executor_cls: type[BaseExecutor],
    ) -> BaseExecutor:

        if not issubclass(executor_cls, BaseExecutor):
            raise TypeError(
                f"{executor_cls.__name__} is not a BaseExecutor."
            )

        return executor_cls()