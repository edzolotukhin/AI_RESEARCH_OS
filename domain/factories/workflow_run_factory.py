from domain.workflow_template import WorkflowTemplate
from domain.workflow_run import WorkflowRun

from domain.factories.ai_task_factory import AITaskFactory


class WorkflowRunFactory:

    def __init__(self):
        self.ai_task_factory = AITaskFactory()

    def create(
        self,
        template: WorkflowTemplate,
        run_id: str,
    ) -> WorkflowRun:

        run = WorkflowRun(
            id=run_id,
            template_id=template.id,
        )

        # Следующим шагом здесь появится создание AITask
        for definition in template.tasks:
            # Пока ничего не делаем
            pass

        return run