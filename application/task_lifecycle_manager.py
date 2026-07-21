from datetime import datetime, UTC

from domain.task import Task
from domain.value_objects.task_status import TaskStatus


class TaskLifecycleManager:
    """
    Управляет жизненным циклом Task.

    Отвечает только за изменение состояния задачи.
    """

    def start(self, task: Task) -> None:
        task.status = TaskStatus.RUNNING
        task.updated_at = datetime.now(UTC).isoformat()

    def complete(self, task: Task) -> None:
        task.status = TaskStatus.COMPLETED
        task.updated_at = datetime.now(UTC).isoformat()

    def fail(self, task: Task) -> None:
        task.status = TaskStatus.FAILED
        task.updated_at = datetime.now(UTC).isoformat()

    def cancel(self, task: Task) -> None:
        task.status = TaskStatus.CANCELLED
        task.updated_at = datetime.now(UTC).isoformat()