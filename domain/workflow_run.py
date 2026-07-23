from dataclasses import dataclass, field
from uuid import uuid4

from domain.task import Task
from domain.workflow_status import WorkflowStatus


@dataclass
class WorkflowRun:
    """
    Экземпляр выполнения WorkflowTemplate.
    """

    id: str = field(default_factory=lambda: str(uuid4()))

    workflow_template_id: str = ""

    tasks: list[Task] = field(default_factory=list)

    status: WorkflowStatus = WorkflowStatus.PENDING