from enum import Enum


class TaskStatus(str, Enum):
    """
    Статус выполнения задачи.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"