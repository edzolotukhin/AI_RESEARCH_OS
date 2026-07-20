from dataclasses import dataclass, field

from domain.task_definition import TaskDefinition


@dataclass
class WorkflowTemplate:
    """
    Неизменяемое описание процесса.
    """

    id: str

    name: str

    tasks: list[TaskDefinition] = field(default_factory=list)