from __future__ import annotations

import copy

from application.persistence.exceptions import DuplicateEntityError
from application.ports.workflow_template_repository import (
    WorkflowTemplateRepository,
)
from domain.workflow_template import WorkflowTemplate


class InMemoryWorkflowTemplateRepository:
    """In-memory WorkflowTemplateRepository adapter."""

    def __init__(self) -> None:
        self._templates: dict[str, WorkflowTemplate] = {}
        self._project_index: dict[str, list[str]] = {}

    def save_snapshot(
        self,
        template: WorkflowTemplate,
        *,
        project_id: str,
    ) -> None:
        if template.id in self._templates:
            raise DuplicateEntityError(
                f"WorkflowTemplate already exists: {template.id}"
            )

        self._templates[template.id] = copy.deepcopy(template)
        project_templates = self._project_index.setdefault(project_id, [])
        if template.id not in project_templates:
            project_templates.append(template.id)

    def get_by_id(self, template_id: str) -> WorkflowTemplate | None:
        template = self._templates.get(template_id)
        if template is None:
            return None
        return copy.deepcopy(template)

    def list_for_project(self, project_id: str) -> list[WorkflowTemplate]:
        template_ids = self._project_index.get(project_id, [])
        return [
            copy.deepcopy(self._templates[template_id])
            for template_id in template_ids
            if template_id in self._templates
        ]
