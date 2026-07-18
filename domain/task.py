from dataclasses import dataclass

from domain.value_objects.task_status import TaskStatus


@dataclass
class Task:
    """
    Единица работы AI Research OS.
    """

    id: str

    name: str

    description: str = ""

    assigned_agent: str = ""

    status: TaskStatus = TaskStatus.PENDING

    created_at: str = ""

    updated_at: str = ""