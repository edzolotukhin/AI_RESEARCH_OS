from domain.ai_task import AITask
from domain.task_definition import TaskDefinition


class AITaskFactory:

    def create(self, definition: TaskDefinition) -> AITask:
        raise NotImplementedError("AITaskFactory will be implemented in the next step.")