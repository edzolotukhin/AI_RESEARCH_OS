from __future__ import annotations

import unittest
from dataclasses import replace

from application.report.claim_authority import ClaimAuthorityError, derive_claim_authority
from application.report.claim_generation import generate_validated_claims
from tests.application.analysis.test_ir4_canonical_authority_projection import setup_pipeline
from tests.application.report.test_report_claim_contract import ReportClaimContractTests


class IR5CanonicalReportAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ReportClaimContractTests()
        self.fixture.setUp()

    def test_claim_authority_can_require_persisted_canonical_finding(self) -> None:
        with self.assertRaises(ClaimAuthorityError):
            derive_claim_authority(
                project_id="project-1",
                source_workflow_run_id="source-run",
                report_workflow_run_id="report-run",
                design=self.fixture.design,
                findings=(self.fixture.finding,),
                evidence_by_id={"ev-1": self.fixture.evidence},
                require_validated_findings=True,
            )

        validated = replace(
            self.fixture.finding,
            metadata={**self.fixture.finding.metadata, "validation_status": "validated"},
        )
        authority = derive_claim_authority(
            project_id="project-1",
            source_workflow_run_id="source-run",
            report_workflow_run_id="report-run",
            design=self.fixture.design,
            findings=(validated,),
            evidence_by_id={"ev-1": self.fixture.evidence},
            require_validated_findings=True,
        )
        self.assertEqual(authority.finding_ids, (validated.id,))

    def test_claim_generation_fails_before_claim_for_unvalidated_finding(self) -> None:
        with self.assertRaises(ClaimAuthorityError):
            generate_validated_claims(
                project_id="project-1",
                source_workflow_run_id="source-run",
                report_workflow_run_id="report-run",
                design=self.fixture.design,
                findings=(self.fixture.finding,),
                insights=(),
                evidence_by_id={"ev-1": self.fixture.evidence},
                citation_id_by_source={"source-1": "S1"},
                require_validated_findings=True,
            )

    def test_legacy_authority_helper_remains_compatible(self) -> None:
        authority = derive_claim_authority(
            project_id="project-1",
            source_workflow_run_id="source-run",
            report_workflow_run_id="report-run",
            design=self.fixture.design,
            findings=(self.fixture.finding,),
            evidence_by_id={"ev-1": self.fixture.evidence},
        )
        self.assertEqual(authority.finding_ids, ("finding-1",))

    def _derived_fixture(self):
        context, readiness, analysis, evidence, findings, insights, sources, _ = setup_pipeline()
        readiness.assess_and_apply(context)
        analysis.analyze_for_context(context)
        all_findings = tuple(findings.list_for_project("project"))
        derived = next(item for item in all_findings if item.information_need_refs == ("change",))
        evidence_by_id = {item.id: item for item in evidence.list_for_project("project")}
        return context, all_findings, derived, evidence_by_id, sources

    def test_validated_derived_finding_uses_canonical_prerequisite_authority(self) -> None:
        context, all_findings, derived, evidence_by_id, sources = self._derived_fixture()
        authority = derive_claim_authority(
            project_id="project", source_workflow_run_id="run",
            report_workflow_run_id="report-run",
            design=context.workflow_template.research_design_snapshot,
            findings=(derived,), evidence_by_id=evidence_by_id,
            require_validated_findings=True, authority_findings=all_findings,
            brief=context.workflow_template.research_brief_snapshot,
            source_repository=sources,
        )
        self.assertEqual(authority.evidence_ids, tuple(sorted(derived.evidence_refs)))

    def test_derived_authority_rejects_tampered_or_incomplete_lineage(self) -> None:
        context, all_findings, derived, evidence_by_id, sources = self._derived_fixture()
        design = context.workflow_template.research_design_snapshot
        good = dict(
            project_id="project", source_workflow_run_id="run",
            report_workflow_run_id="report-run", design=design,
            findings=(derived,), evidence_by_id=evidence_by_id,
            require_validated_findings=True, authority_findings=all_findings,
            brief=context.workflow_template.research_brief_snapshot,
            source_repository=sources,
        )
        cases = (
            replace(derived, metadata={**derived.metadata, "derivation": {}}),
            replace(derived, evidence_refs=("foreign-evidence",)),
            tuple(item for item in all_findings if item.id != next(
                ref for ref in derived.metadata["derivation"]["dependency_finding_ids"]
            )),
            replace(derived, metadata={**derived.metadata, "validation_status": "pending"}),
        )
        with self.assertRaises(ClaimAuthorityError):
            derive_claim_authority(**{**good, "findings": (cases[0],)})
        with self.assertRaises(ClaimAuthorityError):
            derive_claim_authority(**{**good, "findings": (cases[1],)})
        with self.assertRaises(ClaimAuthorityError):
            derive_claim_authority(**{**good, "authority_findings": cases[2]})
        with self.assertRaises(ClaimAuthorityError):
            derive_claim_authority(**{**good, "findings": (cases[3],)})


if __name__ == "__main__":
    unittest.main()
