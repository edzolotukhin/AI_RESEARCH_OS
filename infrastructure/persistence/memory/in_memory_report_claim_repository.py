from __future__ import annotations

import copy

from application.ports.report_claim_repository import ReportClaimConflictError, ReportClaimRepository
from domain.reports.report_claim import ReportClaim
from domain.reports.report import Report
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository


class InMemoryReportClaimRepository(ReportClaimRepository):
    def __init__(self, report_repository: InMemoryReportRepository | None = None) -> None:
        self._claims: dict[str, tuple[str, int, ReportClaim]] = {}
        self._memberships: set[tuple[str, int, str]] = set()
        self._report_repository = report_repository

    def create_with_report(self, report: Report, claims: tuple[ReportClaim, ...]) -> int:
        if self._report_repository is None:
            raise ReportClaimConflictError("atomic Report repository is not configured")
        self._validate_membership(report, claims)
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
        if len(claim_ids) != len(set(claim_ids)):
            raise ReportClaimConflictError("ReportClaim is immutable and already exists")
        for claim in claims:
            existing = self._claims.get(claim.claim_id)
            if existing is not None and existing[2] != claim:
                raise ReportClaimConflictError("ReportClaim authority mutation or mismatch")
            if (report_id, report_revision, claim.claim_id) in self._memberships:
                raise ReportClaimConflictError("ReportClaim membership already exists")
        for claim in claims:
            existing = self._claims.get(claim.claim_id)
            if existing is None:
                self._claims[claim.claim_id] = copy.deepcopy((report_id, report_revision, claim))
            self._memberships.add((report_id, report_revision, claim.claim_id))

    def get_by_id(self, claim_id: str) -> ReportClaim | None:
        item = self._claims.get(claim_id)
        return copy.deepcopy(item[2]) if item else None

    def list_for_report(self, report_id: str, report_revision: int) -> list[ReportClaim]:
        claim_ids = sorted(
            claim_id for rid, revision, claim_id in self._memberships
            if rid == report_id and revision == report_revision
        )
        return [copy.deepcopy(self._claims[claim_id][2]) for claim_id in claim_ids]

    def attach_claims_to_report_revision(self, report: Report, claims: tuple[ReportClaim, ...]) -> int:
        self._validate_membership(report, claims)
        existing = {
            claim_id for rid, revision, claim_id in self._memberships
            if rid == report.id and revision == report.revision_number
        }
        expected = {claim.claim_id for claim in claims}
        if existing and existing != expected:
            raise ReportClaimConflictError("ReportClaim membership is partial or incompatible")
        if existing == expected:
            return 1
        self.create_many(claims, report_id=report.id, report_revision=report.revision_number)
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
