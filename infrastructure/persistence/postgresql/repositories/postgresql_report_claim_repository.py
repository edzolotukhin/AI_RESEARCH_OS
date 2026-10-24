from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from application.ports.report_claim_repository import ReportClaimConflictError, ReportClaimRepository
from domain.reports.report_claim import ReportClaim
from infrastructure.persistence.postgresql.mappers.report_claim_mapper import report_claim_from_model, report_claim_to_model
from infrastructure.persistence.postgresql.models.report_claim_model import ReportClaimModel
from infrastructure.persistence.postgresql.models.report_model import ReportModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLReportClaimRepository(ReportClaimRepository):
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, claim: ReportClaim, *, report_id: str, report_revision: int) -> None:
        self.create_many((claim,), report_id=report_id, report_revision=report_revision)

    def create_many(self, claims: tuple[ReportClaim, ...], *, report_id: str, report_revision: int) -> None:
        with self._session_factory.session() as session:
            report = session.get(ReportModel, report_id)
            if not claims:
                return
            if report is None or report.revision_number != report_revision or any(report.project_id != claim.project_id or report.workflow_run_id != claim.report_workflow_run_id or report.research_design_id != claim.design_id for claim in claims):
                raise ReportClaimConflictError("ReportClaim target revision ownership mismatch")
            try:
                session.add_all([report_claim_to_model(claim, report_id=report_id, report_revision=report_revision) for claim in claims])
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise ReportClaimConflictError("ReportClaim is immutable and already exists") from exc

    def get_by_id(self, claim_id: str) -> ReportClaim | None:
        with self._session_factory.session() as session:
            model = session.get(ReportClaimModel, claim_id)
            return report_claim_from_model(model) if model else None

    def list_for_report(self, report_id: str, report_revision: int) -> list[ReportClaim]:
        with self._session_factory.session() as session:
            models = session.scalars(select(ReportClaimModel).where(ReportClaimModel.report_id == report_id, ReportClaimModel.report_revision == report_revision).order_by(ReportClaimModel.id)).all()
            return [report_claim_from_model(item) for item in models]
