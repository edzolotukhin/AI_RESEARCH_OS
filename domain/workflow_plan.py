from domain.task_definition import TaskDefinition


class WorkflowPlan:
    """
    План Workflow.

    Содержит описание шагов процесса
    в виде TaskDefinition.
    """

    def __init__(self):
        self._tasks: list[TaskDefinition] = []

    def add(
        self,
        task: TaskDefinition,
    ) -> None:

        self._tasks.append(task)

    def remove(
        self,
        task: TaskDefinition,
    ) -> None:

        self._tasks.remove(task)

    def clear(self) -> None:

        self._tasks.clear()

    @property
    def tasks(self) -> list[TaskDefinition]:

        return self._tasks

    def __iter__(self):

        return iter(self._tasks)

    def __len__(self):

        return len(self._tasks)

    def __getitem__(
        self,
        index: int,
    ) -> TaskDefinition:

        return self._tasks[index]