from domain.project import Project
from domain.task import Task

from runtime.execution_state import ExecutionState


class ResearchContext:
    """
    Контекст выполнения исследования.
    """

    def __init__(
        self,
        project: Project,
        task: Task | None = None,
    ):
        self.project = project
        self.task = task
        self.state = ExecutionState.CREATED