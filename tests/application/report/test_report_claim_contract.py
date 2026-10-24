from __future__ import annotations

import unittest
from dataclasses import replace

from application.ports.report_claim_repository import ReportClaimConflictError
from application.report.claim_authority import ClaimAuthorityError, derive_claim_authority
from application.report.claim_contract import report_claim_compatibility
from application.report.claim_validation import validate_report_claim
from application.research_scope.authoritative_scope import SCOPE_KEY, SCOPE_VERSION
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.reports.report_claim import REPORT_CLAIM_VERSION, ClaimScope, NumericFact, ReportClaim, ReportClaimContractError
from domain.reports.report_section import ReportSection
from infrastructure.persistence.memory.in_memory_report_claim_repository import InMemoryReportClaimRepository


class ReportClaimContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.design = ResearchDesign(id="design-1", research_questions=(ResearchQuestion(id="rq-1", question="Q"),), information_needs=(InformationNeed(id="in-1", research_question_id="rq-1", description="N"),))
        scope = {"version": SCOPE_VERSION, "geography": ["ukraine", "kyiv"], "geography_anchors": [{"value": "ukraine", "level": "country"}, {"value": "kyiv", "level": "subnational"}], "periods": ["2026", "2026 Q1"], "metrics": ["income"], "population_dimensions": ["households"], "numeric_facts": [{"value": "10", "unit": "%", "scale": "absolute", "geography": ["ukraine"], "periods": ["2026"], "metrics": ["income"], "population_dimensions": ["households"]}], "source": "validated_evidence_metadata"}
        self.evidence = Evidence(id="ev-1", project_id="project-1", source_id="source-1", source_content_checksum="checksum", workflow_run_id="source-run", research_design_id="design-1", statement="S", source_excerpt="E", created_at="2026-01-01T00:00:00Z", research_question_refs=("rq-1",), information_need_refs=("in-1",), metadata={SCOPE_KEY: scope})
        self.finding = Finding(id="finding-1", project_id="project-1", workflow_run_id="source-run", research_design_id="design-1", statement="F", rationale="R", evidence_refs=("ev-1",), created_at="2026-01-01T00:00:00Z", research_question_refs=("rq-1",), information_need_refs=("in-1",), metadata={SCOPE_KEY: scope})

    def authority(self, report_run: str = "source-run"):
        return derive_claim_authority(project_id="project-1", source_workflow_run_id="source-run", report_workflow_run_id=report_run, design=self.design, findings=(self.finding,), evidence_by_id={"ev-1": self.evidence})

    def claim(self, report_run: str = "source-run") -> ReportClaim:
        authority = self.authority(report_run)
        return ReportClaim(claim_id="claim-1", project_id="project-1", source_workflow_run_id="source-run", report_workflow_run_id=report_run, design_id="design-1", research_question_ids=("rq-1",), information_need_ids=("in-1",), finding_ids=("finding-1",), insight_ids=(), evidence_ids=("ev-1",), kind="observation", proposition="P", certainty="direct", direction="not_applicable", scope=authority.scope, support_evidence_ids=("ev-1",), source_ids=("source-1",), citation_ids=(), finding_content_digests=authority.finding_content_digests, evidence_content_digests=authority.evidence_content_digests, status="validated", contract_version=REPORT_CLAIM_VERSION, authority_digest=authority.authority_digest, validated_at="2026-01-01T00:00:00Z")

    def assert_rejected(self, claim: ReportClaim, authority=None) -> None:
        with self.assertRaises(ClaimAuthorityError):
            validate_report_claim(claim, authority or self.authority(claim.report_workflow_run_id))

    def test_valid_national_regional_period_metric_population_numeric_claim(self) -> None:
        self.assertEqual(validate_report_claim(self.claim(), self.authority()), self.claim())

    def test_independent_scope_dimensions_fail_closed(self) -> None:
        claim = self.claim(); scope = claim.scope
        mutations = [
            replace(scope, geography_country=("poland",)),
            replace(scope, periods=("2025",)),
            replace(scope, metrics=("wealth",)),
            replace(scope, population_dimensions=("employees",)),
        ]
        for changed in mutations:
            with self.subTest(scope=changed): self.assert_rejected(replace(claim, scope=changed))
        empty_authority = replace(self.authority(), scope=replace(scope, metrics=()))
        self.assert_rejected(claim, empty_authority)

    def test_numeric_value_unit_and_each_binding_fail_closed(self) -> None:
        claim = self.claim(); fact = claim.scope.numeric_facts[0]
        changes = [replace(fact, value="11"), replace(fact, unit="uah"), replace(fact, scale="million"), replace(fact, geography=("kyiv",)), replace(fact, periods=("2025",)), replace(fact, metrics=("wealth",)), replace(fact, population_dimensions=("employees",))]
        for changed in changes:
            with self.subTest(fact=changed): self.assert_rejected(replace(claim, scope=replace(claim.scope, numeric_facts=(changed,))))

    def test_empty_scope_arrays_mean_no_authority_and_missing_scope_rejected(self) -> None:
        empty = ClaimScope((), (), (), (), (), ())
        self.assert_rejected(replace(self.claim(), scope=replace(self.claim().scope, periods=("2026",))), replace(self.authority(), scope=empty))
        payload = self.claim().to_dict(); payload.pop("scope")
        with self.assertRaises(ReportClaimContractError): ReportClaim.from_dict(payload)

    def test_normal_replay_and_foreign_lineage(self) -> None:
        validate_report_claim(self.claim(), self.authority())
        replay_claim = self.claim("replay-run")
        validate_report_claim(replay_claim, self.authority("replay-run"))
        self.assertEqual(replay_claim.source_workflow_run_id, "source-run")
        self.assertEqual(replay_claim.report_workflow_run_id, "replay-run")
        self.assert_rejected(replace(replay_claim, source_workflow_run_id="third-run"), self.authority("replay-run"))
        foreign_finding = replace(self.finding, workflow_run_id="third-run")
        with self.assertRaises(ClaimAuthorityError): derive_claim_authority(project_id="project-1", source_workflow_run_id="source-run", report_workflow_run_id="replay-run", design=self.design, findings=(foreign_finding,), evidence_by_id={"ev-1": self.evidence})

    def test_authority_digest_is_deterministic_and_change_sensitive(self) -> None:
        self.assertEqual(self.authority().authority_digest, self.authority().authority_digest)
        changed = replace(self.evidence, statement="changed")
        digest = derive_claim_authority(project_id="project-1", source_workflow_run_id="source-run", report_workflow_run_id="source-run", design=self.design, findings=(self.finding,), evidence_by_id={"ev-1": changed}).authority_digest
        self.assertNotEqual(digest, self.authority().authority_digest)

    def test_strict_unknown_null_and_wildcard_contract(self) -> None:
        payload = self.claim().to_dict(); payload["unknown"] = True
        with self.assertRaises(ReportClaimContractError): ReportClaim.from_dict(payload)
        payload = self.claim().to_dict(); payload["scope"]["periods"] = None
        with self.assertRaises(ReportClaimContractError): ReportClaim.from_dict(payload)
        payload = self.claim().to_dict(); payload["scope"]["periods"] = ["*"]
        with self.assertRaises(ReportClaimContractError): ReportClaim.from_dict(payload)

    def test_memory_repository_round_trip_revision_and_immutability(self) -> None:
        repository = InMemoryReportClaimRepository(); claim = self.claim()
        repository.create(claim, report_id="report-1", report_revision=2)
        self.assertEqual(repository.get_by_id(claim.claim_id), claim)
        self.assertEqual(repository.list_for_report("report-1", 2), [claim])
        self.assertEqual(repository.list_for_report("report-1", 1), [])
        with self.assertRaises(ReportClaimConflictError): repository.create(claim, report_id="report-1", report_revision=2)

    def test_atomic_batch_and_historical_compatibility(self) -> None:
        repository = InMemoryReportClaimRepository(); first = self.claim(); second = replace(first, claim_id="claim-2")
        repository.create_many((first, second), report_id="report-1", report_revision=1)
        self.assertEqual(repository.list_for_report("report-1", 1), [first, second])
        with self.assertRaises(ReportClaimConflictError): repository.create_many((replace(first, claim_id="claim-3"), first), report_id="report-1", report_revision=1)
        self.assertIsNone(repository.get_by_id("claim-3"))
        self.assertEqual(report_claim_compatibility(()), "legacy_unstructured")
        self.assertEqual(report_claim_compatibility((first,)), REPORT_CLAIM_VERSION)

    def test_report_section_legacy_compatibility(self) -> None:
        legacy = ReportSection.from_dict({"id": "s", "title": "T", "content": "C"})
        self.assertEqual(legacy.claim_refs, ())
        self.assertEqual(replace(legacy, claim_refs=("claim-1",)).to_dict()["claim_refs"], ["claim-1"])


if __name__ == "__main__":
    unittest.main()
