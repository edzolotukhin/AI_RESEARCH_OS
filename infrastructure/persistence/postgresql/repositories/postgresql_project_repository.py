from __future__ import annotations

from sqlalchemy import select

from application.persistence.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.ports.project_repository import ProjectRepository
from domain.project import Project
from infrastructure.persistence.postgresql.concurrency import (
    atomic_delete_version,
    atomic_update_version,
)
from infrastructure.persistence.postgresql.mappers.project_mapper import (
    project_from_model,
    project_to_model,
    project_to_update_values,
)
from infrastructure.persistence.postgresql.models.project_model import ProjectModel
from infrastructure.persistence.postgresql.project_activity import record_activity
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLProjectRepository:
    """PostgreSQL adapter for ProjectRepository."""

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, project: Project) -> None:
        with self._session_factory.session() as session:
            existing = session.get(ProjectModel, project.id)
            if existing is not None:
                raise DuplicateEntityError(
                    f"Project already exists: {project.id}"
                )

            session.add(project_to_model(project, version=0))
            # No ORM relationship orders the Activity insert after its project FK.
            session.flush()
            record_activity(
                session, project_id=project.id, semantic_key="project-created",
                event_type="PROJECT_CREATED", source_kind="project",
                source_id=project.id, occurred_at=project.created_at or None,
            )

    def save(
        self,
        project: Project,
        *,
        expected_version: int | None = None,
    ) -> int:
        with self._session_factory.session() as session:
            current = session.get(ProjectModel, project.id)
            old_id = (current.planning_design or {}).get("id") if current else None
            old_status = current.planning_design_status if current else None
            design_id = project.current_research_design.id if project.current_research_design else None
            version = atomic_update_version(
                session,
                ProjectModel,
                project.id,
                expected_version=expected_version,
                values=project_to_update_values(project),
            )
            if design_id and project.research_design_status == "APPROVED" and (
                old_id != design_id or old_status != "APPROVED"
            ):
                record_activity(
                    session, project_id=project.id,
                    semantic_key=f"design-approved:{design_id}",
                    event_type="DESIGN_APPROVED", source_kind="design",
                    source_id=design_id, actor_id=project.research_design_approved_by,
                    occurred_at=project.research_design_approved_at,
                )
            return version

    def get_by_id(self, project_id: str) -> Project | None:
        with self._session_factory.session() as session:
            model = session.get(ProjectModel, project_id)
            if model is None:
                return None
            return project_from_model(model)

    def list(
        self,
        *,
        offset: int = 0,
        limit: int | None = None,
        owner_principal_id: str | None = None,
    ) -> list[Project]:
        with self._session_factory.session() as session:
            statement = select(ProjectModel).order_by(ProjectModel.id)
            if owner_principal_id is not None:
                statement = statement.where(
                    ProjectModel.owner_principal_id == owner_principal_id,
                )
            if offset:
                statement = statement.offset(offset)
            if limit is not None:
                statement = statement.limit(limit)

            models = session.scalars(statement).all()
            return [project_from_model(model) for model in models]

    def delete(
        self,
        project_id: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        with self._session_factory.session() as session:
            atomic_delete_version(
                session,
                ProjectModel,
                project_id,
                expected_version=expected_version,
            )
