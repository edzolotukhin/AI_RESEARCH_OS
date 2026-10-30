from dataclasses import replace
import unittest

from application.ports.report_claim_repository import ReportClaimConflictError
from domain.reports.report import Report
from infrastructure.persistence.memory.in_memory_report_claim_repository import InMemoryReportClaimRepository
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository
from tests.application.report.test_report_claim_contract import ReportClaimContractTests


def _report(report_id: str, revision: int, previous: str | None = None) -> Report:
    return Report(
        id=report_id, project_id="project-1", workflow_run_id="source-run",
        research_design_id="design-1", title="R", language="uk", sections=(),
        executive_summary="", limitations=(), created_at="2026-01-01T00:00:00Z",
        generation_method="test", finding_refs=(), insight_refs=(), evidence_refs=(),
        citation_registry={}, deduplication_key=f"{report_id}-key",
        revision_number=revision, previous_report_id=previous,
    )


class ReportClaimMembershipTests(unittest.TestCase):
    def setUp(self):
        fixture = ReportClaimContractTests()
        fixture.setUp()
        self.claim = fixture.claim()
        self.reports = InMemoryReportRepository()
        self.claims = InMemoryReportClaimRepository(self.reports)

    def test_one_authority_claim_can_membership_two_report_revisions(self):
        r1, r2 = _report("r1", 1), _report("r2", 2, "r1")
        self.claims.create_with_report(r1, (self.claim,))
        self.reports.create(r2)
        self.claims.attach_claims_to_report_revision(r2, (self.claim,))

        self.assertEqual([self.claim], self.claims.list_for_report("r1", 1))
        self.assertEqual([self.claim], self.claims.list_for_report("r2", 2))
        self.assertEqual(self.claim, self.claims.get_by_id(self.claim.claim_id))

    def test_duplicate_membership_reuses_without_cloning_authority(self):
        r1 = _report("r1", 1)
        self.claims.create_with_report(r1, (self.claim,))
        self.assertEqual(1, self.claims.attach_claims_to_report_revision(r1, (self.claim,)))
        self.assertEqual([self.claim], self.claims.list_for_report("r1", 1))

    def test_different_payload_for_existing_claim_id_is_rejected(self):
        r1 = _report("r1", 1)
        self.claims.create_with_report(r1, (self.claim,))
        changed = replace(self.claim, proposition="changed")
        r2 = _report("r2", 2, "r1")
        self.reports.create(r2)
        with self.assertRaises(ReportClaimConflictError):
            self.claims.attach_claims_to_report_revision(r2, (changed,))

    def test_foreign_project_claim_is_rejected(self):
        r1 = _report("r1", 1)
        self.claims.create_with_report(r1, (self.claim,))
        r2 = replace(_report("r2", 2, "r1"), project_id="foreign")
        self.reports.create(r2)
        with self.assertRaises(ReportClaimConflictError):
            self.claims.attach_claims_to_report_revision(r2, (self.claim,))


if __name__ == "__main__":
    unittest.main()
