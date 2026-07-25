from domain.task import Task
from domain.workflow_run import WorkflowRun
from domain.value_objects.task_status import TaskStatus


class TaskScheduler:
    """
    Определяет следующую задачу,
    готовую к выполнению.
    """

    def get_next_task(
        self,
        workflow_run: WorkflowRun,
    ) -> Task | None:

        for task in workflow_run.tasks:
            if task.status == TaskStatus.PENDING:
                return task

        return None