from __future__ import annotations

from typing import Protocol

from application.persistence.records import ArtifactRecord


class ArtifactRepository(Protocol):
    """Persistence port for generated artifact metadata."""

    def save(
        self,
        artifact: ArtifactRecord,
        *,
        expected_version: int | None = None,
    ) -> int:
        """Persist artifact metadata. Returns the new record version."""
        ...

    def get_by_id(self, artifact_id: str) -> ArtifactRecord | None:
        """Load artifact metadata by identifier."""
        ...

    def list_for_project(self, project_id: str) -> list[ArtifactRecord]:
        """List artifacts scoped to a project."""
        ...

    def list_for_run(self, run_id: str) -> list[ArtifactRecord]:
        """List artifacts linked to a workflow run."""
        ...
