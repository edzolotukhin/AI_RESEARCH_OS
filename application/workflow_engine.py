from runtime.research_context import ResearchContext

from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus

from application.services.task_scheduler import TaskScheduler
from application.task_executor import TaskExecutor


class WorkflowEngine:
    """
    Оркестрирует выполнение WorkflowRun.

    WorkflowEngine отвечает только за алгоритм выполнения.
    Он не знает ничего о DAG, Executor или конкретных агентах.
    """

    def __init__(
        self,
        scheduler: TaskScheduler,
        task_executor: TaskExecutor,
    ):
        self._scheduler = scheduler
        self._task_executor = task_executor

    def run(
        self,
        workflow_run: WorkflowRun,
        context: ResearchContext,
    ) -> ResearchContext:

        while True:

            ready_tasks = self._scheduler.get_ready_tasks(workflow_run)

            if not ready_tasks:
                break

            for task in ready_tasks:

                context = self._task_executor.execute(
                    task=task,
                    context=context,
                )

        self._update_workflow_status(workflow_run)

        return context

    def _update_workflow_status(
        self,
        workflow_run: WorkflowRun,
    ):

        if all(task.status.is_completed() for task in workflow_run.tasks):
            workflow_run.status = WorkflowStatus.COMPLETED