from __future__ import annotations

from typing import Protocol

from domain.reports.report_claim import ReportClaim
from domain.reports.report import Report


class ReportClaimConflictError(ValueError):
    pass


class ReportClaimRepository(Protocol):
    def create_with_report(self, report: Report, claims: tuple[ReportClaim, ...]) -> int: ...
    def create(self, claim: ReportClaim, *, report_id: str, report_revision: int) -> None: ...
    def create_many(self, claims: tuple[ReportClaim, ...], *, report_id: str, report_revision: int) -> None: ...
    def get_by_id(self, claim_id: str) -> ReportClaim | None: ...
    def list_for_report(self, report_id: str, report_revision: int) -> list[ReportClaim]: ...
    def attach_claims_to_report_revision(
        self, report: Report, claims: tuple[ReportClaim, ...],
    ) -> int: ...
