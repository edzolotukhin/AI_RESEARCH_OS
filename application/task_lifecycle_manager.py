from datetime import UTC, datetime

from domain.task import Task


class TaskLifecycleManager:
    """
    Управляет жизненным циклом Task.

    Отвечает только за изменение состояния задачи.
    """

    def start(self, task: Task) -> None:
        task.start()
        self._touch(task)

    def complete(self, task: Task) -> None:
        task.complete()
        self._touch(task)

    def fail(self, task: Task) -> None:
        task.fail()
        self._touch(task)

    def cancel(self, task: Task) -> None:
        task.cancel()
        self._touch(task)

    def skip(self, task: Task) -> None:
        task.skip()
        self._touch(task)

    @staticmethod
    def _touch(task: Task) -> None:
        task.updated_at = datetime.now(UTC).isoformat()
