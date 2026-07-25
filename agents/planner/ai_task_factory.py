from domain.ai_task import AITask

from domain.client_qualification_task import ClientQualificationTask
from domain.project_brief_task import ProjectBriefTask


class AITaskFactory:
    """
    Создает AI-задачу по идентификатору TaskDefinition.
    """

    def create(
        self,
        task_id: str,
    ) -> AITask:

        if task_id == "client_qualification":
            return ClientQualificationTask()

        if task_id == "project_brief":
            return ProjectBriefTask()

        raise ValueError(
            f"Unknown AI task '{task_id}'."
        )