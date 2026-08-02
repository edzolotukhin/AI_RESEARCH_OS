from __future__ import annotations

import copy

from application.persistence.exceptions import ConcurrentModificationError
from application.persistence.records import ArtifactRecord
from application.report.exceptions import DuplicateArtifactError
from application.ports.artifact_repository import ArtifactRepository


class InMemoryArtifactRepository:
    """In-memory ArtifactRepository adapter."""

    def __init__(self) -> None:
        self._artifacts: dict[str, ArtifactRecord] = {}
        self._versions: dict[str, int] = {}
        self._project_index: dict[str, list[str]] = {}
        self._run_index: dict[str, list[str]] = {}
        self._dedup_index: dict[tuple[str, str], str] = {}

    def create(self, artifact: ArtifactRecord) -> int:
        if artifact.run_id is None:
            raise DuplicateArtifactError("Artifact run_id is required for create()")
        key = (artifact.run_id, artifact.deduplication_key)
        if key in self._dedup_index:
            raise DuplicateArtifactError(
                f"Artifact already exists for run/key: {artifact.run_id}/{artifact.deduplication_key}",
            )
        self._artifacts[artifact.id] = copy.deepcopy(artifact)
        self._dedup_index[key] = artifact.id
        project_items = self._project_index.setdefault(artifact.project_id, [])
        if artifact.id not in project_items:
            project_items.append(artifact.id)
        run_items = self._run_index.setdefault(artifact.run_id, [])
        if artifact.id not in run_items:
            run_items.append(artifact.id)
        artifact.version = 1
        self._versions[artifact.id] = 1
        return 1

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> ArtifactRecord | None:
        artifact_id = self._dedup_index.get((workflow_run_id, deduplication_key))
        if artifact_id is None:
            return None
        return self.get_by_id(artifact_id)

    def save(
        self,
        artifact: ArtifactRecord,
        *,
        expected_version: int | None = None,
    ) -> int:
        current_version = self._versions.get(artifact.id, 0)
        if (
            expected_version is not None
            and expected_version != current_version
        ):
            raise ConcurrentModificationError(
                f"Artifact {artifact.id} version mismatch: "
                f"expected {expected_version}, found {current_version}."
            )

        self._artifacts[artifact.id] = copy.deepcopy(artifact)
        project_items = self._project_index.setdefault(artifact.project_id, [])
        if artifact.id not in project_items:
            project_items.append(artifact.id)

        if artifact.run_id is not None:
            run_items = self._run_index.setdefault(artifact.run_id, [])
            if artifact.id not in run_items:
                run_items.append(artifact.id)

        new_version = current_version + 1
        self._versions[artifact.id] = new_version
        artifact.version = new_version
        return new_version

    def get_by_id(self, artifact_id: str) -> ArtifactRecord | None:
        artifact = self._artifacts.get(artifact_id)
        if artifact is None:
            return None
        return copy.deepcopy(artifact)

    def list_for_project(self, project_id: str) -> list[ArtifactRecord]:
        artifact_ids = self._project_index.get(project_id, [])
        return [
            copy.deepcopy(self._artifacts[artifact_id])
            for artifact_id in artifact_ids
            if artifact_id in self._artifacts
        ]

    def list_for_run(self, run_id: str) -> list[ArtifactRecord]:
        artifact_ids = self._run_index.get(run_id, [])
        return [
            copy.deepcopy(self._artifacts[artifact_id])
            for artifact_id in artifact_ids
            if artifact_id in self._artifacts
        ]
