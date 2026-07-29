from enum import Enum


class TaskStatus(str, Enum):
    """
    Runtime status of a Task within a WorkflowRun.
    """

    CREATED = "created"
    WAITING = "waiting"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
