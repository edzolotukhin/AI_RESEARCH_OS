from __future__ import annotations

from domain.common.exceptions import DomainError


class WorkflowRunFactoryError(DomainError):
    """Base class for WorkflowRun factory errors."""


class DuplicateTaskDefinitionIdError(WorkflowRunFactoryError):
    """Raised when a workflow template contains duplicate definition ids."""

    def __init__(
        self,
        *,
        workflow_template_id: str,
        definition_id: str,
    ) -> None:
        self.workflow_template_id = workflow_template_id
        self.definition_id = definition_id
        super().__init__(
            "Workflow template "
            f"'{workflow_template_id}' contains duplicate task definition "
            f"'{definition_id}'."
        )


class UnknownTaskDefinitionDependencyError(WorkflowRunFactoryError):
    """Raised when a task definition depends on an unknown definition id."""

    def __init__(
        self,
        *,
        workflow_template_id: str,
        task_definition_id: str,
        dependency_definition_id: str,
    ) -> None:
        self.workflow_template_id = workflow_template_id
        self.task_definition_id = task_definition_id
        self.dependency_definition_id = dependency_definition_id
        super().__init__(
            "Task definition "
            f"'{task_definition_id}' in workflow template "
            f"'{workflow_template_id}' depends on unknown task definition "
            f"'{dependency_definition_id}'."
        )


class WorkflowRunDependencyGraphBuildError(WorkflowRunFactoryError):
    """Raised when runtime dependency graph cannot be built from a template."""

    def __init__(
        self,
        *,
        workflow_template_id: str,
        task_definition_id: str,
        message: str,
    ) -> None:
        self.workflow_template_id = workflow_template_id
        self.task_definition_id = task_definition_id
        super().__init__(message)
