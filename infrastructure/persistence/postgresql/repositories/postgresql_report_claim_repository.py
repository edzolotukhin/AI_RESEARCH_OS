from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from application.ports.report_claim_repository import ReportClaimConflictError, ReportClaimRepository
from domain.reports.report_claim import ReportClaim
from domain.reports.report import Report
from infrastructure.persistence.postgresql.mappers.report_mapper import report_to_model
from infrastructure.persistence.postgresql.project_activity import record_activity
from infrastructure.persistence.postgresql.mappers.report_claim_mapper import report_claim_from_model, report_claim_to_model
from infrastructure.persistence.postgresql.models.report_claim_model import ReportClaimModel
from infrastructure.persistence.postgresql.models.report_claim_membership_model import ReportClaimMembershipModel
from infrastructure.persistence.postgresql.models.report_model import ReportModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLReportClaimRepository(ReportClaimRepository):
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, claim: ReportClaim, *, report_id: str, report_revision: int) -> None:
        self.create_many((claim,), report_id=report_id, report_revision=report_revision)

    def create_with_report(self, report: Report, claims: tuple[ReportClaim, ...]) -> int:
        self._validate_membership(report, claims)
        with self._session_factory.session() as session:
            try:
                session.add(report_to_model(report, version=1))
                # ReportClaimModel deliberately has no ORM relationship to
                # ReportModel.  Establish the FK target before flushing the
                # immutable claim rows while retaining one atomic transaction.
                session.flush()
                session.add_all([report_claim_to_model(claim, report_id=report.id, report_revision=report.revision_number) for claim in claims])
                record_activity(session, project_id=report.project_id, semantic_key=f"desk-report:{report.id}", event_type="DESK_REPORT_DRAFT_CREATED", source_kind="report", source_id=report.id, run_id=report.workflow_run_id, method="DESK", occurred_at=report.created_at)
                session.flush()
                membership_count = session.query(ReportClaimMembershipModel).filter_by(
                    report_id=report.id, report_revision=report.revision_number,
                ).count()
                if membership_count != len(claims):
                    raise ReportClaimConflictError("ReportClaim membership backfill failed")
            except IntegrityError as exc:
                session.rollback()
                raise ReportClaimConflictError("Atomic structured Report persistence failed") from exc
        report.version = 1
        return 1

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
            models = session.scalars(
                select(ReportClaimModel)
                .join(
                    ReportClaimMembershipModel,
                    ReportClaimMembershipModel.report_claim_id == ReportClaimModel.id,
                )
                .where(
                    ReportClaimMembershipModel.report_id == report_id,
                    ReportClaimMembershipModel.report_revision == report_revision,
                )
                .order_by(ReportClaimModel.id)
            ).all()
            return [report_claim_from_model(item) for item in models]

    def attach_claims_to_report_revision(self, report: Report, claims: tuple[ReportClaim, ...]) -> int:
        self._validate_membership(report, claims)
        expected = {claim.claim_id for claim in claims}
        with self._session_factory.session() as session:
            existing = set(session.scalars(
                select(ReportClaimMembershipModel.report_claim_id).where(
                    ReportClaimMembershipModel.report_id == report.id,
                    ReportClaimMembershipModel.report_revision == report.revision_number,
                )
            ).all())
            if existing and existing != expected:
                raise ReportClaimConflictError("ReportClaim membership is partial or incompatible")
            session.add_all([
                ReportClaimMembershipModel(
                    report_id=report.id, report_revision=report.revision_number,
                    report_claim_id=claim.claim_id,
                ) for claim in claims if claim.claim_id not in existing
            ])
            session.flush()
        return 1

    def _validate_membership(self, report: Report, claims: tuple[ReportClaim, ...]) -> None:
        if not claims:
            raise ReportClaimConflictError("ReportClaim membership must not be empty")
        if report.revision_number > 1 and not report.previous_report_id:
            raise ReportClaimConflictError("Report revision parent is missing")
        if report.metadata.get("structured_claim_contract") == "desk_h3_structural_claim_v1":
            if any(claim.contract_version != "desk_h3_structural_claim_v1" for claim in claims):
                raise ReportClaimConflictError("H3 ReportClaim contract mismatch")
            if report.previous_report_id:
                previous = self.list_for_report(report.previous_report_id, report.revision_number - 1)
                if {item.claim_id for item in previous} != {item.claim_id for item in claims}:
                    raise ReportClaimConflictError("H3 ReportClaim authority set mismatch")
        if any(
            claim.project_id != report.project_id
            or claim.design_id != report.research_design_id
            or claim.report_workflow_run_id != report.workflow_run_id
            for claim in claims
        ):
            raise ReportClaimConflictError("ReportClaim membership lineage mismatch")
