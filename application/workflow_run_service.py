from uuid import uuid4

from domain.project import Project
from domain.workflow_run import WorkflowRun
from domain.workflow_template import WorkflowTemplate

from domain.factories.workflow_run_factory import WorkflowRunFactory


class WorkflowRunService:
    """
    Application Service.

    Создает WorkflowRun
    и добавляет его в Project.
    """

    def __init__(
        self,
        workflow_run_factory: WorkflowRunFactory,
    ):
        self._workflow_run_factory = workflow_run_factory

    def create_run(
        self,
        project: Project,
        workflow_template: WorkflowTemplate,
    ) -> WorkflowRun:

        run = self._workflow_run_factory.create(
            template=workflow_template,
            run_id=str(uuid4()),
        )

        project.runs.append(run)

        return run