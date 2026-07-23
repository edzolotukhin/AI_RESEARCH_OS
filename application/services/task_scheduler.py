from domain.task import Task
from domain.workflow_run import WorkflowRun
from domain.value_objects.task_status import TaskStatus


class TaskScheduler:
    """
    Определяет задачи, готовые к выполнению.
    """

    def get_ready_tasks(self, workflow_run: WorkflowRun) -> list[Task]:
        ready_tasks: list[Task] = []

        task_index = {
            task.id: task
            for task in workflow_run.tasks
        }

        for task in workflow_run.tasks:

            if task.status != TaskStatus.PENDING:
                continue

            dependencies_completed = True

            for dependency_id in task.depends_on:
                dependency = task_index.get(dependency_id)

                if dependency is None:
                    dependencies_completed = False
                    break

                if dependency.status != TaskStatus.COMPLETED:
                    dependencies_completed = False
                    break

            if dependencies_completed:
                ready_tasks.append(task)

        return ready_tasks