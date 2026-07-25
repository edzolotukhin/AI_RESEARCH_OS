from runtime.research_context import ResearchContext

from application.task_executor import TaskExecutor
from application.task_scheduler import TaskScheduler

from domain.workflow_status import WorkflowStatus


class WorkflowEngine:
    """
    Центральный оркестратор выполнения Workflow.
    """

    def __init__(
        self,
        scheduler: TaskScheduler,
        task_executor: TaskExecutor,
    ):
        self._scheduler = scheduler
        self._task_executor = task_executor

    def execute(
        self,
        context: ResearchContext,
    ) -> ResearchContext:

        workflow_run = context.workflow_run

        if workflow_run is None:
            raise ValueError("WorkflowRun is not initialized.")

        workflow_run.status = WorkflowStatus.RUNNING

        while True:

            task = self._scheduler.get_next_task(workflow_run)

            if task is None:
                break

            context.current_task = task

            context = self._task_executor.execute(
                task=task,
                context=context,
            )

        workflow_run.status = WorkflowStatus.COMPLETED

        return context