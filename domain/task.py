from dataclasses import dataclass, field

from domain.value_objects.task_status import TaskStatus


@dataclass
class Task:
    """
    Экземпляр задачи в рамках WorkflowRun.
    Создается на основе TaskDefinition.
    """

    id: str

    definition_id: str

    name: str

    description: str = ""

    executor_id: str = ""

    depends_on: list[str] = field(default_factory=list)

    status: TaskStatus = TaskStatus.PENDING

    created_at: str = ""

    updated_at: str = ""