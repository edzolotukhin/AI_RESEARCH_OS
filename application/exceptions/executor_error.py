class UnsupportedExecutorTypeError(Exception):
    """
    Raised when a task references an unsupported executor type.
    """

    def __init__(self, executor_type) -> None:
        self.executor_type = executor_type
        super().__init__(
            f"Unsupported executor type: '{executor_type}'."
        )


class ExecutorNotFoundError(Exception):
    """
    Raised when no executor is registered for the given type and id.
    """

    def __init__(
        self,
        executor_type,
        executor_id: str,
        *,
        task_id: str | None = None,
        workflow_run_id: str | None = None,
        available_executor_ids: tuple[str, ...] | None = None,
    ) -> None:
        self.executor_type = executor_type
        self.executor_id = executor_id
        self.task_id = task_id
        self.workflow_run_id = workflow_run_id
        self.available_executor_ids = available_executor_ids or tuple()

        details = [
            f"Executor '{executor_id}' of type '{executor_type}' is not registered.",
        ]

        if task_id:
            details.append(f"task_id={task_id}")

        if workflow_run_id:
            details.append(f"workflow_run_id={workflow_run_id}")

        if self.available_executor_ids:
            details.append(
                "available_executor_ids="
                f"{', '.join(self.available_executor_ids)}"
            )

        super().__init__(" ".join(details))


class InvalidExecutorConfigurationError(Exception):
    """
    Raised when a task has incomplete executor configuration.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
