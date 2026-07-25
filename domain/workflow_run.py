from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from domain.task import Task
from domain.workflow_status import WorkflowStatus


@dataclass
class WorkflowRun:
    """
    Экземпляр выполнения WorkflowTemplate.

    Domain-модель состояния Workflow.
    Выполнение Workflow осуществляется Application-слоем.
    """

    id: str = field(default_factory=lambda: str(uuid4()))

    workflow_template_id: str = ""

    tasks: list[Task] = field(default_factory=list)

    status: WorkflowStatus = WorkflowStatus.PENDING

    def pause(self) -> None:
        self.status = WorkflowStatus.PAUSED

    def resume(self) -> None:
        self.status = WorkflowStatus.RUNNING

    def cancel(self) -> None:
        self.status = WorkflowStatus.CANCELLED

    @property
    def progress(self) -> int:
        """
        Процент выполнения Workflow.
        Пока заглушка.
        """
        return 0

    @property
    def artifacts(self) -> list[Any]:
        """
        Артефакты, созданные данным WorkflowRun.

        Пока заглушка.
        """
        return []