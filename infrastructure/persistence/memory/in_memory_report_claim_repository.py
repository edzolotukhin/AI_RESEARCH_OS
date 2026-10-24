from __future__ import annotations

import copy

from application.ports.report_claim_repository import ReportClaimConflictError, ReportClaimRepository
from domain.reports.report_claim import ReportClaim
from domain.reports.report import Report
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository


class InMemoryReportClaimRepository(ReportClaimRepository):
    def __init__(self, report_repository: InMemoryReportRepository | None = None) -> None:
        self._claims: dict[str, tuple[str, int, ReportClaim]] = {}
        self._report_repository = report_repository

    def create_with_report(self, report: Report, claims: tuple[ReportClaim, ...]) -> int:
        if self._report_repository is None:
            raise ReportClaimConflictError("atomic Report repository is not configured")
        claim_ids = [item.claim_id for item in claims]
        if len(claim_ids) != len(set(claim_ids)) or any(item in self._claims for item in claim_ids):
            raise ReportClaimConflictError("ReportClaim is immutable and already exists")
        if any(
            claim.project_id != report.project_id
            or claim.report_workflow_run_id != report.workflow_run_id
            or claim.design_id != report.research_design_id
            for claim in claims
        ):
            raise ReportClaimConflictError("ReportClaim target revision ownership mismatch")
        version = self._report_repository.create(report)
        self.create_many(claims, report_id=report.id, report_revision=report.revision_number)
        return version

    def create(self, claim: ReportClaim, *, report_id: str, report_revision: int) -> None:
        self.create_many((claim,), report_id=report_id, report_revision=report_revision)

    def create_many(self, claims: tuple[ReportClaim, ...], *, report_id: str, report_revision: int) -> None:
        claim_ids = [item.claim_id for item in claims]
        if len(claim_ids) != len(set(claim_ids)) or any(item in self._claims for item in claim_ids):
            raise ReportClaimConflictError("ReportClaim is immutable and already exists")
        for claim in claims:
            self._claims[claim.claim_id] = copy.deepcopy((report_id, report_revision, claim))

    def get_by_id(self, claim_id: str) -> ReportClaim | None:
        item = self._claims.get(claim_id)
        return copy.deepcopy(item[2]) if item else None

    def list_for_report(self, report_id: str, report_revision: int) -> list[ReportClaim]:
        return [copy.deepcopy(claim) for stored_report, revision, claim in self._claims.values() if stored_report == report_id and revision == report_revision]
