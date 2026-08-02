from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from application.evidence.exceptions import DuplicateEvidenceError
from application.ports.evidence_ports import EvidenceRepository
from domain.evidence.evidence import Evidence

from infrastructure.persistence.postgresql.mappers.evidence_mapper import (
    evidence_from_model,
    evidence_to_model,
)
from infrastructure.persistence.postgresql.models.evidence_model import EvidenceModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLEvidenceRepository(EvidenceRepository):
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, evidence: Evidence) -> int:
        with self._session_factory.session() as session:
            try:
                session.add(evidence_to_model(evidence, version=1))
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateEvidenceError(
                    f"Evidence already exists for run/key: "
                    f"{evidence.workflow_run_id}/{evidence.deduplication_key}",
                ) from exc
            evidence.version = 1
            return 1

    def get_by_id(self, evidence_id: str) -> Evidence | None:
        with self._session_factory.session() as session:
            model = session.get(EvidenceModel, evidence_id)
            if model is None:
                return None
            return evidence_from_model(model)

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Evidence | None:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = select(EvidenceModel).where(
                EvidenceModel.workflow_run_id == workflow_run_id,
                EvidenceModel.deduplication_key == deduplication_key,
            )
            model = session.scalars(statement).first()
            if model is None:
                return None
            return evidence_from_model(model)

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        information_need_id: str | None = None,
        source_id: str | None = None,
    ) -> list[Evidence]:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = (
                select(EvidenceModel)
                .where(EvidenceModel.project_id == project_id)
                .order_by(EvidenceModel.id)
            )
            if workflow_run_id is not None:
                statement = statement.where(
                    EvidenceModel.workflow_run_id == workflow_run_id,
                )
            if source_id is not None:
                statement = statement.where(EvidenceModel.source_id == source_id)
            models = session.scalars(statement).all()

        evidence_items = [evidence_from_model(model) for model in models]
        if research_question_id is not None:
            evidence_items = [
                item
                for item in evidence_items
                if research_question_id in item.research_question_refs
            ]
        if information_need_id is not None:
            evidence_items = [
                item
                for item in evidence_items
                if information_need_id in item.information_need_refs
            ]
        return evidence_items
