from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from application.analysis.exceptions import DuplicateFindingError
from application.ports.analysis_ports import FindingRepository
from domain.findings.finding import Finding

from infrastructure.persistence.postgresql.mappers.finding_mapper import (
    finding_from_model,
    finding_to_model,
)
from infrastructure.persistence.postgresql.models.finding_model import FindingModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLFindingRepository(FindingRepository):
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, finding: Finding) -> int:
        with self._session_factory.session() as session:
            try:
                session.add(finding_to_model(finding, version=1))
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateFindingError(
                    f"Finding already exists for run/key: "
                    f"{finding.workflow_run_id}/{finding.deduplication_key}",
                ) from exc
            finding.version = 1
            return 1

    def get_by_id(self, finding_id: str) -> Finding | None:
        with self._session_factory.session() as session:
            model = session.get(FindingModel, finding_id)
            if model is None:
                return None
            return finding_from_model(model)

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Finding | None:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = select(FindingModel).where(
                FindingModel.workflow_run_id == workflow_run_id,
                FindingModel.deduplication_key == deduplication_key,
            )
            model = session.scalars(statement).first()
            if model is None:
                return None
            return finding_from_model(model)

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        information_need_id: str | None = None,
        evidence_id: str | None = None,
    ) -> list[Finding]:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = (
                select(FindingModel)
                .where(FindingModel.project_id == project_id)
                .order_by(FindingModel.id)
            )
            if workflow_run_id is not None:
                statement = statement.where(
                    FindingModel.workflow_run_id == workflow_run_id,
                )
            models = session.scalars(statement).all()

        findings = [finding_from_model(model) for model in models]
        if research_question_id is not None:
            findings = [
                item
                for item in findings
                if research_question_id in item.research_question_refs
            ]
        if information_need_id is not None:
            findings = [
                item
                for item in findings
                if information_need_id in item.information_need_refs
            ]
        if evidence_id is not None:
            findings = [
                item for item in findings if evidence_id in item.evidence_refs
            ]
        return findings
