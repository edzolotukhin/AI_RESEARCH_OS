from __future__ import annotations

import copy

from domain.reports.report import Report

from application.report.exceptions import DuplicateReportError
from application.ports.report_ports import ReportRepository


class InMemoryReportRepository(ReportRepository):
    def __init__(self) -> None:
        self._reports: dict[str, Report] = {}
        self._dedup_index: dict[tuple[str, str], str] = {}
        self._project_index: dict[str, list[str]] = {}

    def create(self, report: Report) -> int:
        key = (report.workflow_run_id, report.deduplication_key)
        if key in self._dedup_index:
            raise DuplicateReportError(
                f"Report already exists for run/key: {report.workflow_run_id}/{report.deduplication_key}",
            )
        self._reports[report.id] = copy.deepcopy(report)
        self._dedup_index[key] = report.id
        project_items = self._project_index.setdefault(report.project_id, [])
        if report.id not in project_items:
            project_items.append(report.id)
        report.version = 1
        return 1

    def get_by_id(self, report_id: str) -> Report | None:
        report = self._reports.get(report_id)
        return copy.deepcopy(report) if report is not None else None

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Report | None:
        report_id = self._dedup_index.get((workflow_run_id, deduplication_key))
        if report_id is None:
            return None
        return self.get_by_id(report_id)

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
    ) -> list[Report]:
        report_ids = self._project_index.get(project_id, [])
        reports = [
            copy.deepcopy(self._reports[report_id])
            for report_id in report_ids
            if report_id in self._reports
        ]
        if workflow_run_id is not None:
            reports = [
                item for item in reports if item.workflow_run_id == workflow_run_id
            ]
        return reports
