from dataclasses import dataclass, field
from uuid import uuid4
from typing import Any

from domain.task import Task
from domain.workflow_status import WorkflowStatus


@dataclass
class WorkflowRun:
    """
    Экземпляр выполнения WorkflowTemplate.

    На данном этапе является публичным фасадом над Runtime.
    Реальная логика выполнения будет перенесена сюда постепенно.
    """

    id: str = field(default_factory=lambda: str(uuid4()))

    workflow_template_id: str = ""

    tasks: list[Task] = field(default_factory=list)

    status: WorkflowStatus = WorkflowStatus.PENDING

    def execute(self) -> None:
        """
        Запустить выполнение Workflow.

        Пока не реализовано.
        """
        raise NotImplementedError("WorkflowRun.execute() is not implemented yet.")

    def pause(self) -> None:
        raise NotImplementedError("WorkflowRun.pause() is not implemented yet.")

    def resume(self) -> None:
        raise NotImplementedError("WorkflowRun.resume() is not implemented yet.")

    def cancel(self) -> None:
        raise NotImplementedError("WorkflowRun.cancel() is not implemented yet.")

    @property
    def progress(self) -> int:
        """
        Процент выполнения Workflow.
        """
        return 0

    @property
    def artifacts(self) -> list[Any]:
        """
        Артефакты, созданные данным WorkflowRun.

        Пока не реализовано.
        """
        return []