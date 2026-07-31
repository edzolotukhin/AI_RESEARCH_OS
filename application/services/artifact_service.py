"""
Artifact metadata persistence service.

ArtifactRecord is a persistence-boundary type, not a completed domain aggregate.
The domain Artifact model lacks identity and project/run linkage; full artifact
lifecycle belongs to a future domain ADR. This service coordinates metadata
persistence only — no blob storage.
"""

from __future__ import annotations

from application.persistence.exceptions import EntityNotFoundError
from application.persistence.records import ArtifactRecord
from application.ports.artifact_repository import ArtifactRepository


class ArtifactService:
    """Coordinates artifact metadata persistence use cases."""

    def __init__(self, *, artifact_repository: ArtifactRepository) -> None:
        self._artifact_repository = artifact_repository

    def save_artifact(
        self,
        artifact: ArtifactRecord,
        *,
        expected_version: int | None = None,
    ) -> int:
        return self._artifact_repository.save(
            artifact,
            expected_version=expected_version,
        )

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        artifact = self._artifact_repository.get_by_id(artifact_id)
        if artifact is None:
            raise EntityNotFoundError(f"Artifact not found: {artifact_id}")
        return artifact

    def list_artifacts_for_project(
        self,
        project_id: str,
    ) -> list[ArtifactRecord]:
        return self._artifact_repository.list_for_project(project_id)

    def list_artifacts_for_run(self, run_id: str) -> list[ArtifactRecord]:
        return self._artifact_repository.list_for_run(run_id)
