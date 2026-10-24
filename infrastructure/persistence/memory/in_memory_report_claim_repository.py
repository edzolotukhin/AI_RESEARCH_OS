from __future__ import annotations

import copy

from application.ports.report_claim_repository import ReportClaimConflictError, ReportClaimRepository
from domain.reports.report_claim import ReportClaim


class InMemoryReportClaimRepository(ReportClaimRepository):
    def __init__(self) -> None:
        self._claims: dict[str, tuple[str, int, ReportClaim]] = {}

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
