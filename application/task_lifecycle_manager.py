from datetime import UTC, datetime

from domain.task import Task
from domain.value_objects.task_status import TaskStatus


class TaskLifecycleManager:
    """
    Управляет жизненным циклом Task.

    Отвечает только за изменение состояния задачи.
    """

    def start(self, task: Task) -> None:
        self._update(task, TaskStatus.RUNNING)

    def complete(self, task: Task) -> None:
        self._update(task, TaskStatus.COMPLETED)

    def fail(self, task: Task) -> None:
        self._update(task, TaskStatus.FAILED)

    def cancel(self, task: Task) -> None:
        self._update(task, TaskStatus.CANCELLED)

    @staticmethod
    def _update(task: Task, status: TaskStatus) -> None:
        task.status = status
        task.updated_at = datetime.now(UTC).isoformat()