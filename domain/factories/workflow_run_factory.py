from domain.workflow_template import WorkflowTemplate
from domain.workflow_run import WorkflowRun

from domain.factories.task_factory import TaskFactory


class WorkflowRunFactory:

    def __init__(
        self,
        task_factory: TaskFactory,
    ):
        self.task_factory = task_factory

    def create(
        self,
        template: WorkflowTemplate,
        run_id: str,
    ) -> WorkflowRun:

        run = WorkflowRun(
            id=run_id,
            workflow_template_id=template.id,
        )

        for definition in template.task_definitions:
            run.tasks.append(
                self.task_factory.create(definition)
            )

        return run