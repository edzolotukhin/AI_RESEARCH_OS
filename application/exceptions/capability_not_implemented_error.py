class CapabilityNotImplementedError(Exception):
    """
    Raised when a desk-research stage has no production implementation yet.

    DR-03 Search, DR-05 Analysis, and DR-06 Report are not implemented in DR-02.
    """

    def __init__(
        self,
        *,
        capability: str,
        stage: str,
        task_id: str | None = None,
    ) -> None:
        self.capability = capability
        self.stage = stage
        self.task_id = task_id
        message = (
            f"Capability '{capability}' (stage '{stage}') is not implemented yet."
        )
        if task_id:
            message += f" task_id={task_id}"
        super().__init__(message)
