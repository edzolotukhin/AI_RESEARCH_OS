from __future__ import annotations

import unittest
from hashlib import sha256

from application.analysis.analysis_coverage_service import (
    ANALYSIS_COVERAGE_DIAGNOSTIC_VERSION,
    assess_analysis_coverage,
)
from application.evidence.grounding import verify_grounding
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.source import Source
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository


class AnalysisCoverageServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.design = ResearchDesign(
            "design-1",
            (ResearchQuestion("rq-1", "Q1"), ResearchQuestion("rq-2", "Q2")),
            (
                InformationNeed("in-1", "rq-1", "N1"),
                InformationNeed("in-2", "rq-2", "N2"),
            ),
            language="uk",
        )
        self.sources = InMemorySourceRepository()
        self.evidence = [self._evidence(1, "rq-1", "in-1"), self._evidence(2, "rq-2", "in-2")]

    def _evidence(self, index: int, rq: str, need: str) -> Evidence:
        content = f"Grounded observation {index}."
        checksum = sha256(content.encode("utf-8")).hexdigest()
        source = Source(
            id=f"source-{index}", project_id="project-1",
            url=f"https://example.test/{index}", canonical_url=f"https://example.test/{index}",
            title=f"Source {index}", retrieved_at="2026-01-01T00:00:00Z",
            content_text=content, content_checksum=checksum,
        )
        self.sources.create(source)
        locator = verify_grounding(source_text=content, excerpt=content).to_dict()
        return Evidence(
            id=f"evidence-{index}", project_id="project-1", source_id=source.id,
            source_content_checksum=checksum, workflow_run_id="run-1",
            research_design_id=self.design.id, statement=content, source_excerpt=content,
            source_locator=locator, created_at="2026-01-01T00:00:00Z",
            research_question_refs=(rq,), information_need_refs=(need,),
        )

    @staticmethod
    def _finding(index: int, need: str, evidence_id: str) -> Finding:
        return Finding(
            id=f"finding-{index}", project_id="project-1", workflow_run_id="run-1",
            research_design_id="design-1", statement=f"Finding {index}", rationale="Supported",
            evidence_refs=(evidence_id,), created_at="2026-01-01T00:00:00Z",
            research_question_refs=(f"rq-{index}",), information_need_refs=(need,),
        )

    def assess(self, findings, evidence=None):
        return assess_analysis_coverage(
            design=self.design, findings=findings,
            evidence=self.evidence if evidence is None else evidence,
            brief=None, source_repository=self.sources,
        )

    def test_complete_coverage_is_exact_and_deterministic(self) -> None:
        result = self.assess((
            self._finding(2, "in-2", "evidence-2"),
            self._finding(1, "in-1", "evidence-1"),
        ))

        self.assertTrue(result.fully_covered)
        self.assertEqual(result.required_information_need_ids, ("in-1", "in-2"))
        self.assertEqual(result.covered_information_need_ids, ("in-1", "in-2"))
        self.assertEqual(result.missing_information_need_ids, ())
        self.assertEqual(result.evidence_without_finding, ())
        self.assertEqual(result.diagnostic_version, ANALYSIS_COVERAGE_DIAGNOSTIC_VERSION)

    def test_evidence_without_finding_is_reported_for_missing_need(self) -> None:
        result = self.assess((self._finding(1, "in-1", "evidence-1"),))

        self.assertFalse(result.fully_covered)
        self.assertEqual(result.covered_information_need_ids, ("in-1",))
        self.assertEqual(result.missing_information_need_ids, ("in-2",))
        self.assertEqual(result.evidence_without_finding, ("evidence-2",))

    def test_no_findings_reports_all_required_needs_and_evidence(self) -> None:
        result = self.assess(())

        self.assertEqual(result.missing_information_need_ids, ("in-1", "in-2"))
        self.assertEqual(result.evidence_without_finding, ("evidence-1", "evidence-2"))

    def test_unresolved_evidence_reference_cannot_cover_need(self) -> None:
        result = self.assess((self._finding(1, "in-1", "missing-evidence"),))

        self.assertEqual(result.covered_information_need_ids, ())
        self.assertEqual(result.missing_information_need_ids, ("in-1", "in-2"))

    def test_finding_reference_requires_same_need_on_qualifying_evidence(self) -> None:
        finding = self._finding(1, "in-2", "evidence-1")

        result = self.assess((finding, self._finding(1, "in-1", "evidence-1")))

        self.assertEqual(result.covered_information_need_ids, ("in-1",))
        self.assertEqual(result.missing_information_need_ids, ("in-2",))

    def test_invalid_citation_is_not_qualifying_evidence(self) -> None:
        invalid = self.evidence[1]
        invalid.source_content_checksum = "not-the-source-checksum"

        result = self.assess((self._finding(2, "in-2", invalid.id),))

        self.assertNotIn("in-2", result.covered_information_need_ids)
        self.assertNotIn(invalid.id, result.evidence_without_finding)


if __name__ == "__main__":
    unittest.main()
