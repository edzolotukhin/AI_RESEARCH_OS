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

    def save(
        self,
        project: Project,
        *,
        expected_version: int | None = None,
    ) -> int:
        with self._session_factory.session() as session:
            return atomic_update_version(
                session,
                ProjectModel,
                project.id,
                expected_version=expected_version,
                values=project_to_update_values(project),
            )

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
    ) -> list[Project]:
        with self._session_factory.session() as session:
            statement = select(ProjectModel).order_by(ProjectModel.id)
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
