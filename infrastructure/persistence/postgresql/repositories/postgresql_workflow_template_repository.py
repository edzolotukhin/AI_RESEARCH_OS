from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from application.persistence.exceptions import DuplicateEntityError
from application.ports.workflow_template_repository import (
    WorkflowTemplateRepository,
)
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.postgresql.mappers.workflow_template_mapper import (
    workflow_template_from_model,
    workflow_template_to_model,
)
from infrastructure.persistence.postgresql.models.workflow_template_model import (
    WorkflowTemplateModel,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLWorkflowTemplateRepository:
    """PostgreSQL adapter for immutable WorkflowTemplate snapshots."""

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def save_snapshot(
        self,
        template: WorkflowTemplate,
        *,
        project_id: str,
    ) -> None:
        with self._session_factory.session() as session:
            existing = session.get(WorkflowTemplateModel, template.id)
            if existing is not None:
                raise DuplicateEntityError(
                    f"WorkflowTemplate already exists: {template.id}"
                )

            session.add(
                workflow_template_to_model(
                    template,
                    project_id=project_id,
                    created_at=datetime.now(timezone.utc),
                )
            )

    def get_by_id(self, template_id: str) -> WorkflowTemplate | None:
        with self._session_factory.session() as session:
            model = session.get(WorkflowTemplateModel, template_id)
            if model is None:
                return None
            return workflow_template_from_model(model)

    def list_for_project(self, project_id: str) -> list[WorkflowTemplate]:
        with self._session_factory.session() as session:
            statement = (
                select(WorkflowTemplateModel)
                .where(WorkflowTemplateModel.project_id == project_id)
                .order_by(WorkflowTemplateModel.id)
            )
            models = session.scalars(statement).all()
            return [workflow_template_from_model(model) for model in models]
