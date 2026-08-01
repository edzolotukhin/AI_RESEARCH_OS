from __future__ import annotations

from typing import Protocol

from domain.project import Project


class ProjectRepository(Protocol):
    """
    Persistence port for the Project business aggregate.

    Aggregate-oriented operations only. Implementations must not expose
    filesystem, JSON, or directory concerns through this interface.

    Repositories persist aggregates; they never construct business objects.
    Project creation belongs to ProjectFactory (or equivalent domain factory).
    """

    def create(self, project: Project) -> None:
        """
        Persist a new project aggregate and its storage scaffold.

        Accepts only aggregates that do not yet exist in storage.
        Initializes persistence version to 0 and fully persists the adapter's
        supported aggregate representation.
        Raises DuplicateEntityError when project.id already exists.
        """
        ...

    def save(
        self,
        project: Project,
        *,
        expected_version: int | None = None,
    ) -> int:
        """
        Persist modifications to an existing project aggregate.

        Raises EntityNotFoundError when the aggregate was never created.
        Returns the new aggregate version. Raises ConcurrentModificationError
        when expected_version does not match the stored version.
        """
        ...

    def get_by_id(self, project_id: str) -> Project | None:
        """Load a project aggregate by identifier."""
        ...

    def list(
        self,
        *,
        offset: int = 0,
        limit: int | None = None,
        owner_principal_id: str | None = None,
    ) -> list[Project]:
        """List persisted projects in stable identifier order."""
        ...

    def delete(
        self,
        project_id: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        """
        Remove a project aggregate from storage.

        Verifies existence and, when expected_version is supplied, optimistic
        concurrency before deletion.
        """
        ...
