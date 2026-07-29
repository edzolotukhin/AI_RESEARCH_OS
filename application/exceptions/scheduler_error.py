class UnknownDependencyError(Exception):
    """
    Raised when a task depends on a task definition
    that is not present in the workflow run.
    """

    def __init__(
        self,
        task_definition_id: str,
        dependency_id: str,
    ) -> None:
        self.task_definition_id = task_definition_id
        self.dependency_id = dependency_id
        super().__init__(
            "Task "
            f"'{task_definition_id}' depends on unknown task "
            f"'{dependency_id}'."
        )


class SchedulerStuckError(Exception):
    """
    Raised when pending tasks remain but none can progress.
    """

    def __init__(
        self,
        message: str = "Workflow has pending tasks that cannot progress.",
    ) -> None:
        super().__init__(message)
