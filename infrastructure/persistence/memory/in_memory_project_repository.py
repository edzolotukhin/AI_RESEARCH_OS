from __future__ import annotations

import copy

from application.persistence.exceptions import (
    ConcurrentModificationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.ports.project_repository import ProjectRepository
from domain.project import Project


class InMemoryProjectRepository:
    """In-memory ProjectRepository adapter for tests and contract validation."""

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._versions: dict[str, int] = {}

    def create(self, project: Project) -> None:
        if project.id in self._projects:
            raise DuplicateEntityError(
                f"Project already exists: {project.id}"
            )

        self._projects[project.id] = copy.deepcopy(project)
        self._versions[project.id] = 0

    def save(
        self,
        project: Project,
        *,
        expected_version: int | None = None,
    ) -> int:
        if project.id not in self._projects:
            raise EntityNotFoundError(
                f"Project not found: {project.id}"
            )

        current_version = self._versions[project.id]
        if (
            expected_version is not None
            and expected_version != current_version
        ):
            raise ConcurrentModificationError(
                f"Project {project.id} version mismatch: "
                f"expected {expected_version}, found {current_version}."
            )

        self._projects[project.id] = copy.deepcopy(project)
        new_version = current_version + 1
        self._versions[project.id] = new_version
        return new_version

    def get_by_id(self, project_id: str) -> Project | None:
        project = self._projects.get(project_id)
        if project is None:
            return None
        return copy.deepcopy(project)

    def list(
        self,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Project]:
        project_ids = sorted(self._projects)
        if offset:
            project_ids = project_ids[offset:]
        if limit is not None:
            project_ids = project_ids[:limit]

        return [
            copy.deepcopy(self._projects[project_id])
            for project_id in project_ids
        ]

    def delete(
        self,
        project_id: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        if project_id not in self._projects:
            raise EntityNotFoundError(f"Project not found: {project_id}")

        if expected_version is not None:
            current_version = self._versions[project_id]
            if expected_version != current_version:
                raise ConcurrentModificationError(
                    f"Project {project_id} version mismatch: "
                    f"expected {expected_version}, found {current_version}."
                )

        self._projects.pop(project_id, None)
        self._versions.pop(project_id, None)
