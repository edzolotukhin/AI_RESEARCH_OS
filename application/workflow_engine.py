from domain.project import Project

from domain.workflow_template import WorkflowTemplate

from domain.workflow_run import WorkflowRun



from runtime.workflow_context import WorkflowContext



from application.exceptions.scheduler_error import SchedulerStuckError

from application.task_executor import TaskExecutor

from application.task_scheduler import TaskScheduler



from domain.workflow_status import WorkflowStatus

from domain.value_objects.task_status import TaskStatus





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

        project: Project,

        workflow_template: WorkflowTemplate,

        workflow_run: WorkflowRun,

    ) -> WorkflowContext:

        context = WorkflowContext(

            project=project,

            workflow_template=workflow_template,

            workflow_run=workflow_run,

        )



        if workflow_run.status == WorkflowStatus.CREATED:

            workflow_run.ready()



        workflow_run.start()



        while True:

            self._scheduler.schedule(workflow_run)

            task = self._scheduler.find_ready_task(workflow_run)



            if task is not None:

                context.current_task = task



                context = self._task_executor.execute(context)



                continue



            if not self._scheduler.has_pending_tasks(workflow_run):

                break



            if self._scheduler.has_waiting_on_incomplete_tasks(

                workflow_run,

            ):

                raise SchedulerStuckError(

                    "Workflow has pending tasks waiting on incomplete "

                    "dependencies."

                )



            break



        self._apply_workflow_status(

            workflow_run,

            self._resolve_workflow_status(workflow_run),

        )



        return context



    @staticmethod

    def _apply_workflow_status(

        workflow_run: WorkflowRun,

        target: WorkflowStatus,

    ) -> None:

        if workflow_run.status == target:

            return



        if target == WorkflowStatus.COMPLETED:

            workflow_run.complete()

            return



        if target == WorkflowStatus.FAILED:

            workflow_run.fail()

            return



        if target == WorkflowStatus.CANCELLED:

            workflow_run.cancel()

            return



    @staticmethod

    def _resolve_workflow_status(

        workflow_run: WorkflowRun,

    ) -> WorkflowStatus:

        statuses = {

            task.status

            for task in workflow_run.tasks

        }



        if statuses == {TaskStatus.COMPLETED}:

            return WorkflowStatus.COMPLETED



        if TaskStatus.FAILED in statuses:

            return WorkflowStatus.FAILED



        if TaskStatus.SKIPPED in statuses:

            return WorkflowStatus.FAILED



        if TaskStatus.CANCELLED in statuses:

            return WorkflowStatus.CANCELLED



        return WorkflowStatus.COMPLETED

