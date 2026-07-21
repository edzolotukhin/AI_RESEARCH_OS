from runtime.research_context import ResearchContext

from domain.workflow_run import WorkflowRun
from domain.value_objects.task_status import TaskStatus

from application.task_executor import TaskExecutor


class WorkflowEngine:
    """
    Оркестрирует выполнение WorkflowRun.

    WorkflowEngine отвечает только за алгоритм выполнения.
    Он не знает ничего о Planner, Tool, API или Human.
    """

    def __init__(
        self,
        task_executor: TaskExecutor,
    ):
        self._task_executor = task_executor

    def run(
        self,
        workflow_run: WorkflowRun,
        context: ResearchContext,
    ) -> ResearchContext:

        while self._has_ready_tasks(workflow_run):

            task = self._select_next_task(workflow_run)

            context = self._task_executor.execute(
                task=task,
                context=context,
            )

        self._update_workflow(workflow_run)

        return context

    def _has_ready_tasks(
        self,
        workflow_run: WorkflowRun,
    ) -> bool:

        return any(
            task.status == TaskStatus.PENDING
            for task in workflow_run.tasks
        )

    def _select_next_task(
        self,
        workflow_run: WorkflowRun,
    ):

        for task in workflow_run.tasks:

            if task.status == TaskStatus.PENDING:
                return task

        raise RuntimeError("No pending task found.")

    def _update_workflow(
        self,
        workflow_run: WorkflowRun,
    ):

        if all(
            task.status == TaskStatus.COMPLETED
            for task in workflow_run.tasks
        ):
            workflow_run.status = "completed"