from domain.workflow_template import WorkflowTemplate
from domain.workflow_run import WorkflowRun

from domain.factories.task_factory import TaskFactory


class WorkflowRunFactory:

    def __init__(self):
        self.task_factory = TaskFactory()

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
            task = self.task_factory.create(definition)
            run.tasks.append(task)

        return run