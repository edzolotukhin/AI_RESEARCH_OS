from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from application.ports.report_ports import ReportRepository
from application.ports.report_claim_repository import ReportClaimConflictError
from application.report.exceptions import DuplicateReportError
from domain.reports.report import Report

from infrastructure.persistence.postgresql.mappers.report_mapper import (
    report_from_model,
    report_to_model,
)
from infrastructure.persistence.postgresql.models.report_model import ReportModel
from infrastructure.persistence.postgresql.project_activity import record_activity
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLReportRepository(ReportRepository):
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, report: Report) -> int:
        with self._session_factory.session() as session:
            try:
                session.add(report_to_model(report, version=1))
                record_activity(
                    session, project_id=report.project_id,
                    semantic_key=f"desk-report:{report.id}",
                    event_type="DESK_REPORT_DRAFT_CREATED", source_kind="report",
                    source_id=report.id, run_id=report.workflow_run_id, method="DESK",
                    occurred_at=report.created_at,
                )
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateReportError(
                    f"Report already exists for run/key: "
                    f"{report.workflow_run_id}/{report.deduplication_key}",
                ) from exc
            report.version = 1
            return 1

    def get_by_id(self, report_id: str) -> Report | None:
        with self._session_factory.session() as session:
            model = session.get(ReportModel, report_id)
            if model is None:
                return None
            return report_from_model(model)

    def lock_revision(self, report_id: str, *, expected_revision: int) -> Report:
        """Lock and validate a parent revision inside an owned write transaction.

        This serializes only callers that use the same parent-lock protocol; it
        is not a database-enforced successor uniqueness guarantee.
        """
        from sqlalchemy import select

        session = self._session_factory.require_write_transaction()
        model = session.execute(
            select(ReportModel)
            .where(ReportModel.id == report_id)
            .with_for_update()
        ).scalar_one_or_none()
        if model is None or model.revision_number != expected_revision:
            raise ReportClaimConflictError("Report revision is stale or unavailable")
        return report_from_model(model)

    def allocate_successor(
        self,
        parent_report_id: str,
        *,
        expected_revision: int,
        successor: Report,
    ) -> Report:
        """Reserve an immediate successor slot after locking its parent.

        The returned parent remains locked until the caller-owned transaction
        ends. The caller must persist ``successor`` before leaving that same
        transaction. Writers bypassing this protocol are outside the guarantee.
        """
        from sqlalchemy import select

        parent = self.lock_revision(
            parent_report_id,
            expected_revision=expected_revision,
        )
        if (
            successor.previous_report_id != parent.id
            or successor.project_id != parent.project_id
            or successor.revision_number != parent.revision_number + 1
        ):
            raise ReportClaimConflictError("Report successor identity mismatch")
        session = self._session_factory.require_write_transaction()
        existing = session.execute(
            select(ReportModel.id)
            .where(
                ReportModel.previous_report_id == parent.id,
                ReportModel.revision_number == successor.revision_number,
            )
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            raise ReportClaimConflictError("Report successor already exists")
        return parent

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Report | None:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = select(ReportModel).where(
                ReportModel.workflow_run_id == workflow_run_id,
                ReportModel.deduplication_key == deduplication_key,
            )
            model = session.scalars(statement).first()
            if model is None:
                return None
            return report_from_model(model)

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
    ) -> list[Report]:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = (
                select(ReportModel)
                .where(ReportModel.project_id == project_id)
                .order_by(ReportModel.id)
            )
            if workflow_run_id is not None:
                statement = statement.where(
                    ReportModel.workflow_run_id == workflow_run_id,
                )
            models = session.scalars(statement).all()
        return [report_from_model(model) for model in models]
