from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from application.persistence.exceptions import ConcurrentModificationError
from application.persistence.records import ArtifactRecord
from application.report.exceptions import DuplicateArtifactError
from infrastructure.persistence.postgresql.concurrency import atomic_update_version
from infrastructure.persistence.postgresql.mappers.artifact_mapper import (
    artifact_from_model,
    artifact_to_model,
    artifact_to_update_values,
)
from infrastructure.persistence.postgresql.models.artifact_model import ArtifactModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLArtifactRepository:
    """PostgreSQL adapter for artifact metadata persistence."""

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, artifact: ArtifactRecord) -> int:
        with self._session_factory.session() as session:
            try:
                session.add(artifact_to_model(artifact, version=1))
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateArtifactError(
                    f"Artifact already exists for run/key: "
                    f"{artifact.run_id}/{artifact.deduplication_key}",
                ) from exc
            artifact.version = 1
            return 1

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> ArtifactRecord | None:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = select(ArtifactModel).where(
                ArtifactModel.run_id == workflow_run_id,
                ArtifactModel.deduplication_key == deduplication_key,
            )
            model = session.scalars(statement).first()
            if model is None:
                return None
            return artifact_from_model(model)

    def save(
        self,
        artifact: ArtifactRecord,
        *,
        expected_version: int | None = None,
    ) -> int:
        with self._session_factory.session() as session:
            existing = session.get(ArtifactModel, artifact.id)
            if existing is None:
                session.add(artifact_to_model(artifact, version=1))
                artifact.version = 1
                return 1

            new_version = atomic_update_version(
                session,
                ArtifactModel,
                artifact.id,
                expected_version=expected_version,
                values=artifact_to_update_values(artifact),
            )
            artifact.version = new_version
            return new_version

    def get_by_id(self, artifact_id: str) -> ArtifactRecord | None:
        with self._session_factory.session() as session:
            model = session.get(ArtifactModel, artifact_id)
            if model is None:
                return None
            return artifact_from_model(model)

    def list_for_project(self, project_id: str) -> list[ArtifactRecord]:
        with self._session_factory.session() as session:
            statement = (
                select(ArtifactModel)
                .where(ArtifactModel.project_id == project_id)
                .order_by(ArtifactModel.id)
            )
            return [
                artifact_from_model(model)
                for model in session.scalars(statement).all()
            ]

    def list_for_run(self, run_id: str) -> list[ArtifactRecord]:
        with self._session_factory.session() as session:
            statement = (
                select(ArtifactModel)
                .where(ArtifactModel.run_id == run_id)
                .order_by(ArtifactModel.id)
            )
            return [
                artifact_from_model(model)
                for model in session.scalars(statement).all()
            ]
