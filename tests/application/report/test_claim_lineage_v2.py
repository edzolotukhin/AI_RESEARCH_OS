from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import unittest

from application.analysis.numeric_integrity import NumericQualificationResult, ValidatedNumericObservation
from application.report.claim_lineage_v2 import ClaimLineageV2Error, build_claim_lineage_v2
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import EvidenceCoverageContract, InformationNeed, ResearchDesign, ResearchQuestion
from domain.reports.report_claim import ClaimScope, NumericFact
from domain.sources.source import Source


PROJECT, RUN, REPORT_RUN, DESIGN = "project-1", "source-run", "report-run", "design-1"
NEED, RQ = "need-1", "rq-1"


class ClaimLineageV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        need = InformationNeed(
            NEED, RQ, "Population", geography="Ukraine",
            evidence_expectation=EvidenceExpectation(EvidenceNature.QUANTITATIVE, requires_quantitative_evidence=True),
            evidence_coverage=EvidenceCoverageContract(
                required_metric="Population", required_unit="persons",
                required_periods=("2024",), geography="Ukraine",
            ),
        )
        self.design = ResearchDesign(DESIGN, (ResearchQuestion(RQ, "Population"),), (need,))
        self.source = Source(
            id="source-1", project_id=PROJECT, url="https://example.invalid/data.xlsx",
            canonical_url="https://example.invalid/data.xlsx", title="Dataset",
            retrieved_at="2026-01-01T00:00:00Z", content_text="rows",
            content_checksum="c" * 64, terminal_resource_key="t" * 64,
            raw_content_checksum="r" * 64, raw_checksum_kind="sha256-bytes",
            content_revision=2, extraction_revision="xlsx-v2",
            workflow_run_refs=(RUN,), research_design_refs=(DESIGN,),
        )
        self.evidence = Evidence(
            id="ev-1", project_id=PROJECT, source_id=self.source.id,
            source_content_checksum=self.source.content_checksum, workflow_run_id=RUN,
            research_design_id=DESIGN, statement="Population was 10.", source_excerpt="10",
            created_at="2026-01-01T00:00:00Z", research_question_refs=(RQ,),
            information_need_refs=(NEED,), source_locator={"cell": "B2"},
        )
        self.finding = Finding(
            id="finding-1", project_id=PROJECT, workflow_run_id=RUN,
            research_design_id=DESIGN, statement="Population was 10.", rationale="Observed",
            evidence_refs=(self.evidence.id,), created_at="2026-01-01T00:00:00Z",
            research_question_refs=(RQ,), information_need_refs=(NEED,),
            finding_type=FindingType.SYNTHESIS, analysis_method="deterministic",
        )
        self.insight = Insight(
            id="insight-1", project_id=PROJECT, workflow_run_id=RUN,
            research_design_id=DESIGN, statement="Population is measured.", implication="Comparable baseline.",
            finding_refs=(self.finding.id,), created_at="2026-01-01T00:00:00Z",
            research_question_refs=(RQ,),
        )
        self.observation = ValidatedNumericObservation(
            evidence_id=self.evidence.id, source_id=self.source.id, information_need_id=NEED,
            subject_id="subject-1", subject_fingerprint="fingerprint-1", metric="Population",
            unit="persons", geography="Ukraine", period="2024", value=Decimal("10"),
            source_content_checksum=self.source.content_checksum,
            raw_content_checksum=self.source.raw_content_checksum,
            raw_checksum_kind=self.source.raw_checksum_kind,
            terminal_resource_key=self.source.terminal_resource_key,
            extraction_revision=self.source.extraction_revision,
            content_revision=self.source.content_revision, cell="B2", lineage={"dataset": "primary-1"},
        )
        self.qualification = NumericQualificationResult(
            information_need_id=NEED, available=True, accepted_evidence=(self.evidence,),
            observations=(self.observation,), rejections=(), rejection_reason_counts={},
            qualified_periods=("2024",), missing_periods=(), compatible_duplicate_periods=(),
            conflicting_periods=(), established_lineage_ids=("primary-1",), unknown_lineage_count=0,
        )
        self.scope = ClaimScope(
            ("ukraine",), (), ("2024",), ("population",), (),
            (NumericFact("10", "persons", "absolute", ("ukraine",), ("2024",), ("population",), ()),),
        )

    def build(self, **changes):
        values = dict(
            project_id=PROJECT, source_workflow_run_id=RUN, report_workflow_run_id=REPORT_RUN,
            design=self.design, scope=self.scope, findings=(self.finding,), insights=(self.insight,),
            evidence_by_id={self.evidence.id: self.evidence}, source_by_id={self.source.id: self.source},
            temporal_decisions={(self.evidence.id, NEED): "applicable_satisfied"},
            allowed_workflow_run_ids=(RUN,), numeric_qualifications={NEED: self.qualification},
        )
        values.update(changes)
        return build_claim_lineage_v2(**values)

    def test_valid_complete_lineage_is_immutable_and_complete(self) -> None:
        result = self.build()
        self.assertEqual(result.finding_ids, (self.finding.id,))
        self.assertEqual(result.insight_finding_refs, {self.insight.id: (self.finding.id,)})
        self.assertEqual(set(result.numeric_observation_proof_digests), {self.evidence.id})
        with self.assertRaises(TypeError):
            result.source_revision_digests[self.source.id] = "changed"

    def test_missing_or_foreign_finding_and_insight_are_rejected(self) -> None:
        cases = (
            dict(findings=()),
            dict(findings=(replace(self.finding, project_id="foreign"),)),
            dict(insights=(replace(self.insight, workflow_run_id="foreign-run"),)),
            dict(insights=(replace(self.insight, finding_refs=("missing",)),)),
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ClaimLineageV2Error):
                self.build(**changes)

    def test_missing_or_foreign_evidence_and_source_are_rejected(self) -> None:
        cases = (
            dict(evidence_by_id={}),
            dict(evidence_by_id={self.evidence.id: replace(self.evidence, project_id="foreign")}),
            dict(source_by_id={}),
            dict(source_by_id={self.source.id: replace(self.source, project_id="foreign")}),
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ClaimLineageV2Error):
                self.build(**changes)

    def test_source_checksum_and_revision_mismatches_are_rejected(self) -> None:
        cases = (
            dict(evidence_by_id={self.evidence.id: replace(self.evidence, source_content_checksum="x" * 64)}),
            dict(numeric_qualifications={NEED: replace(
                self.qualification,
                observations=(replace(self.observation, content_revision=99),),
            )}),
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ClaimLineageV2Error):
                self.build(**changes)

    def test_rejected_or_missing_temporal_authority_is_rejected(self) -> None:
        for decision in ("applicable_failed", "applicable_unresolved", None):
            decisions = {} if decision is None else {(self.evidence.id, NEED): decision}
            with self.subTest(decision=decision), self.assertRaises(ClaimLineageV2Error):
                self.build(temporal_decisions=decisions)

    def test_rejected_numeric_evidence_cannot_produce_proof(self) -> None:
        rejected = replace(
            self.qualification, accepted_evidence=(), observations=(),
            rejections=((self.evidence.id, "numeric_source_revision_mismatch"),),
        )
        with self.assertRaises(ClaimLineageV2Error):
            self.build(numeric_qualifications={NEED: rejected})

    def test_mixed_workflow_runs_are_rejected(self) -> None:
        mixed = replace(self.evidence, workflow_run_id="other-run")
        with self.assertRaises(ClaimLineageV2Error):
            self.build(
                evidence_by_id={mixed.id: mixed},
                allowed_workflow_run_ids=(RUN, "other-run"),
            )

    def test_digest_is_deterministic_under_input_ordering(self) -> None:
        second = replace(self.insight, id="insight-2")
        first = self.build(insights=(self.insight, second))
        reordered = self.build(
            insights=(second, self.insight),
            evidence_by_id=dict(reversed(tuple({self.evidence.id: self.evidence}.items()))),
            source_by_id=dict(reversed(tuple({self.source.id: self.source}.items()))),
        )
        self.assertEqual(first.authority_digest, reordered.authority_digest)
        self.assertEqual(dict(first.insight_content_digests), dict(reordered.insight_content_digests))

    def test_missing_numeric_qualification_fails_closed(self) -> None:
        with self.assertRaises(ClaimLineageV2Error):
            self.build(numeric_qualifications={})


if __name__ == "__main__":
    unittest.main()
