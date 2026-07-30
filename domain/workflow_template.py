from dataclasses import dataclass, field

from domain.task_definition import TaskDefinition


@dataclass
class WorkflowTemplate:
    """
    Неизменяемый шаблон процесса.
    Содержит определения задач (TaskDefinition),
    из которых создаются Task при запуске WorkflowRun.
    """

    id: str

    name: str

    task_definitions: list[TaskDefinition] = field(default_factory=list)