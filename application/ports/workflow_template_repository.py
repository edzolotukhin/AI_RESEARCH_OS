from __future__ import annotations

from typing import Protocol

from domain.workflow_template import WorkflowTemplate


class WorkflowTemplateRepository(Protocol):
    """
    Persistence port for immutable WorkflowTemplate definition snapshots.

    TaskDefinition entities are persisted only as part of the template aggregate.
    """

    def save_snapshot(
        self,
        template: WorkflowTemplate,
        *,
        project_id: str,
    ) -> None:
        """Store an immutable template snapshot for a project."""
        ...

    def get_by_id(self, template_id: str) -> WorkflowTemplate | None:
        """Load a template snapshot by identifier."""
        ...

    def list_for_project(self, project_id: str) -> list[WorkflowTemplate]:
        """List template snapshots belonging to a project."""
        ...
