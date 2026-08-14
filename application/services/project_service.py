"""
Application persistence services.

Exception policy (PF-02.5): services propagate application.persistence
exceptions unchanged (DuplicateEntityError, EntityNotFoundError,
ConcurrentModificationError). Callers translate to transport errors at the
API boundary in PF-05.
"""

from __future__ import annotations

from application.persistence.exceptions import EntityNotFoundError
from application.ports.project_repository import ProjectRepository
from domain.factories.project_factory import ProjectFactory
from domain.project import Project


class ProjectService:
    """
    Coordinates Project persistence use cases.

    ProjectFactory constructs aggregates; ProjectRepository persists them.
    This service orchestrates create, load, save, list, and delete operations.
    """

    def __init__(
        self,
        *,
        project_factory: ProjectFactory,
        project_repository: ProjectRepository,
    ) -> None:
        self._project_factory = project_factory
        self._project_repository = project_repository

    def create_project(
        self,
        name: str,
        *,
        owner_principal_id: str | None = None,
        project_id: str | None = None,
    ) -> Project:
        if project_id is None:
            project = self._project_factory.create(name)
        else:
            project = self._project_factory.create(name, project_id=project_id)
        project.owner_principal_id = owner_principal_id
        self._project_repository.create(project)
        return project

    def get_project(self, project_id: str) -> Project:
        project = self._project_repository.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError(f"Project not found: {project_id}")
        return project

    def list_projects(
        self,
        *,
        offset: int = 0,
        limit: int | None = None,
        owner_principal_id: str | None = None,
    ) -> list[Project]:
        return self._project_repository.list(
            offset=offset,
            limit=limit,
            owner_principal_id=owner_principal_id,
        )

    def save_project(
        self,
        project: Project,
        *,
        expected_version: int | None = None,
    ) -> int:
        return self._project_repository.save(
            project,
            expected_version=expected_version,
        )

    def delete_project(
        self,
        project_id: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        self._project_repository.delete(
            project_id,
            expected_version=expected_version,
        )
