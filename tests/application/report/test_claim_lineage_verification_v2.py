from __future__ import annotations

from types import SimpleNamespace
import unittest

from application.report.claim_lineage_verification_v2 import (
    ClaimLineageVerificationV2Error,
    verify_persisted_claim_v2,
)
import tests.application.report.test_report_claim_contract as v1_fixtures
import tests.application.report.test_report_claim_v2_contract as v2_fixtures


class ClaimLineageVerificationV2UnitTests(unittest.TestCase):
    def test_v1_is_rejected_without_repository_access(self) -> None:
        fixture = v1_fixtures.ReportClaimContractTests(); fixture.setUp()
        with self.assertRaisesRegex(ClaimLineageVerificationV2Error, "exact ReportClaim v2"):
            verify_persisted_claim_v2(
                claim=fixture.claim(), report=SimpleNamespace(),
                finding_repository=None, insight_repository=None, evidence_repository=None,
                source_repository=None, workflow_run_repository=None,
                workflow_template_repository=None,
            )

    def test_v2_report_context_mismatch_is_rejected_before_authority_load(self) -> None:
        fixture = v2_fixtures.ReportClaimV2ContractTests()
        claim = fixture.claim()
        report = SimpleNamespace(
            project_id="foreign", workflow_run_id=claim.report_workflow_run_id,
            research_design_id=claim.design_id,
        )
        with self.assertRaisesRegex(ClaimLineageVerificationV2Error, "Report context mismatch"):
            verify_persisted_claim_v2(
                claim=claim, report=report,
                finding_repository=None, insight_repository=None, evidence_repository=None,
                source_repository=None, workflow_run_repository=None,
                workflow_template_repository=None,
            )


if __name__ == "__main__":
    unittest.main()
