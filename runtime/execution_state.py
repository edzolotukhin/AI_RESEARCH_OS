from enum import Enum


class ExecutionState(Enum):
    """
    Состояние выполнения исследования.
    """

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"