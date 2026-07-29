from dataclasses import dataclass, field
from typing import Any

from domain.project import Project
from domain.task import Task
from domain.workflow_template import WorkflowTemplate
from domain.workflow_run import WorkflowRun


@dataclass
class WorkflowContext:
    """
    Central runtime context for workflow execution.

    All executors, agents and tools exchange data through this object.
    """

    workflow_run: WorkflowRun
    project: Project

    workflow_template: WorkflowTemplate | None = None
    current_task: Task | None = None

    shared_state: dict[str, Any] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    intermediate_results: dict[str, Any] = field(default_factory=dict)
    execution_metadata: dict[str, Any] = field(default_factory=dict)
    services: dict[str, Any] = field(default_factory=dict)

    def read_shared(self, key: str) -> Any:
        return self.shared_state.get(key)

    def write_shared(self, key: str, value: Any) -> None:
        self.shared_state[key] = value
