from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from application.ports.report_ports import ReportRepository
from application.report.exceptions import DuplicateReportError
from domain.reports.report import Report

from infrastructure.persistence.postgresql.mappers.report_mapper import (
    report_from_model,
    report_to_model,
)
from infrastructure.persistence.postgresql.models.report_model import ReportModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLReportRepository(ReportRepository):
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, report: Report) -> int:
        with self._session_factory.session() as session:
            try:
                session.add(report_to_model(report, version=1))
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
