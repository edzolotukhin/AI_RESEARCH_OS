from domain.ai_task import AITask


class WorkflowPlan:

    def __init__(self):

        self._tasks: list[AITask] = []

    def add(self, task: AITask):

        self._tasks.append(task)

    def remove(self, task: AITask):

        self._tasks.remove(task)

    def clear(self):

        self._tasks.clear()

    @property
    def tasks(self):

        return self._tasks

    def __iter__(self):

        return iter(self._tasks)

    def __len__(self):

        return len(self._tasks)

    def __getitem__(self, index):

        return self._tasks[index]