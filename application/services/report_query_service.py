from __future__ import annotations

from application.persistence.exceptions import EntityNotFoundError
from application.ports.report_ports import ReportRepository
from domain.reports.report import Report


class ReportQueryService:
    """Application service for durable research report access."""

    def __init__(self, *, report_repository: ReportRepository) -> None:
        self._report_repository = report_repository

    def get_report(self, report_id: str) -> Report:
        report = self._report_repository.get_by_id(report_id)
        if report is None:
            raise EntityNotFoundError(f"Report not found: {report_id}")
        return report

    def list_reports_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
    ) -> list[Report]:
        return self._report_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )

    def count_for_run(self, project_id: str, workflow_run_id: str) -> int:
        return len(
            self.list_reports_for_project(
                project_id,
                workflow_run_id=workflow_run_id,
            ),
        )

    def run_has_reports(self, project_id: str, workflow_run_id: str) -> bool:
        return self.count_for_run(project_id, workflow_run_id) > 0
