from domain.project import Project
from domain.workflow_plan import WorkflowPlan
from domain.task import Task

from runtime.execution_state import ExecutionState


class ResearchContext:
    """
    Контекст выполнения Workflow.
    Содержит текущее состояние исполнения,
    но не хранит бизнес-данные проекта.
    """

    def __init__(
        self,
        project: Project,
    ):
        self.project = project

        self.plan = WorkflowPlan()

        self.current_task: Task | None = None
        self.current_agent: str | None = None

        self.state = ExecutionState.CREATED

        self.variables: dict[str, object] = {}
        self.artifacts: dict[str, object] = {}
        self.logs: list[str] = []