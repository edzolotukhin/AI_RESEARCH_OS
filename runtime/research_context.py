from domain.project import Project
from domain.task import Task
from domain.workflow_template import WorkflowTemplate
from domain.workflow_run import WorkflowRun

from runtime.execution_state import ExecutionState


class ResearchContext:
    """
    Runtime-контекст выполнения Workflow.

    Содержит временное состояние исполнения.
    """

    def __init__(
        self,
        project: Project,
    ):
        self.project = project

        self.workflow_template: WorkflowTemplate | None = None
        self.workflow_run: WorkflowRun | None = None

        self.current_task: Task | None = None
        self.current_agent: str | None = None

        self.state = ExecutionState.CREATED

        self.variables: dict[str, object] = {}
        self.artifacts: dict[str, object] = {}
        self.logs: list[str] = []