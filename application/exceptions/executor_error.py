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
    ) -> None:
        self.executor_type = executor_type
        self.executor_id = executor_id
        super().__init__(
            "Executor "
            f"'{executor_id}' of type '{executor_type}' is not registered."
        )


class InvalidExecutorConfigurationError(Exception):
    """
    Raised when a task has incomplete executor configuration.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
