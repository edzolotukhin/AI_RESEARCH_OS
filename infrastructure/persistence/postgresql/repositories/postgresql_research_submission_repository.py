from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from application.persistence.records import (
    ResearchSubmissionRecord,
    ResearchSubmissionStatus,
)
from application.ports.research_submission_repository import ResearchSubmissionRepository
from infrastructure.persistence.postgresql.models.research_submission_model import (
    ResearchSubmissionModel,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


def _to_record(model: ResearchSubmissionModel) -> ResearchSubmissionRecord:
    return ResearchSubmissionRecord(
        project_id=model.project_id,
        idempotency_key=model.idempotency_key,
        request_fingerprint=model.request_fingerprint,
        run_id=model.run_id,
        correlation_id=model.correlation_id,
        source=model.source,
        created_at=model.created_at,
        status=model.status,
    )


class PostgreSQLResearchSubmissionRepository(ResearchSubmissionRepository):
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def try_register(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        run_id: str,
        correlation_id: str | None,
        source: str | None,
    ) -> tuple[bool, ResearchSubmissionRecord]:
        now = datetime.now(timezone.utc)
        with self._session_factory.session() as session:
            inserted = session.execute(
                insert(ResearchSubmissionModel)
                .values(
                    project_id=project_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    run_id=run_id,
                    correlation_id=correlation_id,
                    source=source,
                    status=ResearchSubmissionStatus.PENDING,
                    created_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["project_id", "idempotency_key"],
                )
                .returning(ResearchSubmissionModel)
            ).scalar_one_or_none()
            if inserted is not None:
                return True, _to_record(inserted)

            existing = session.execute(
                select(ResearchSubmissionModel).where(
                    ResearchSubmissionModel.project_id == project_id,
                    ResearchSubmissionModel.idempotency_key == idempotency_key,
                )
            ).scalar_one()
            return False, _to_record(existing)

    def delete_by_key(self, *, project_id: str, idempotency_key: str) -> None:
        with self._session_factory.session() as session:
            session.execute(
                delete(ResearchSubmissionModel).where(
                    ResearchSubmissionModel.project_id == project_id,
                    ResearchSubmissionModel.idempotency_key == idempotency_key,
                )
            )

    def mark_completed(self, *, project_id: str, idempotency_key: str) -> None:
        with self._session_factory.session() as session:
            model = session.execute(
                select(ResearchSubmissionModel).where(
                    ResearchSubmissionModel.project_id == project_id,
                    ResearchSubmissionModel.idempotency_key == idempotency_key,
                )
            ).scalar_one_or_none()
            if model is None:
                return
            model.status = ResearchSubmissionStatus.COMPLETED

    def get_by_key(
        self,
        *,
        project_id: str,
        idempotency_key: str,
    ) -> ResearchSubmissionRecord | None:
        with self._session_factory.session() as session:
            model = session.execute(
                select(ResearchSubmissionModel).where(
                    ResearchSubmissionModel.project_id == project_id,
                    ResearchSubmissionModel.idempotency_key == idempotency_key,
                )
            ).scalar_one_or_none()
            if model is None:
                return None
            return _to_record(model)

    def get_by_run_id(self, run_id: str) -> ResearchSubmissionRecord | None:
        with self._session_factory.session() as session:
            model = session.execute(
                select(ResearchSubmissionModel).where(
                    ResearchSubmissionModel.run_id == run_id,
                )
            ).scalar_one_or_none()
            if model is None:
                return None
            return _to_record(model)
