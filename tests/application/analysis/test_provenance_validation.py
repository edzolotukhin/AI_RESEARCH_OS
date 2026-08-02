from __future__ import annotations

import unittest

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.findings.finding import Finding
from domain.planning.research_design import ResearchDesign, ResearchQuestion

from application.analysis.deduplication import (
    compute_finding_deduplication_key,
    compute_insight_deduplication_key,
)
from application.analysis.exceptions import InvalidAnalysisProvenanceError
from application.analysis.provenance_validation import (
    validate_finding_candidate,
    validate_insight_candidate,
)
from application.ports.analysis_ports import FindingCandidate, InsightCandidate


def _design() -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(
                id="rq-1",
                question="How is the market growing?",
                objective_refs=("obj-1",),
                priority=1,
                rationale="Primary question",
            ),
        ),
        information_needs=(),
        source_strategy=("web",),
        analysis_plan=("compare growth rates",),
        deliverable_plan=("summary",),
        assumptions=(),
        limitations=(),
        language="en",
    )


class ProvenanceValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = Evidence(
            id="ev-1",
            project_id="project-1",
            source_id="source-1",
            source_content_checksum="abc",
            workflow_run_id="run-a",
            research_design_id="design-1",
            statement="Company X reported 23% growth.",
            source_excerpt="23% growth",
            created_at="2026-01-01T00:00:00+00:00",
            research_question_refs=("rq-1",),
            evidence_type=EvidenceType.DIRECT_EXCERPT,
        )
        self.finding = Finding(
            id="finding-1",
            project_id="project-1",
            workflow_run_id="run-a",
            research_design_id="design-1",
            statement="Company X is growing faster than peers.",
            rationale="Based on reported growth.",
            evidence_refs=("ev-1",),
            created_at="2026-01-01T00:00:00+00:00",
            research_question_refs=("rq-1",),
        )

    def test_rejects_empty_evidence_refs(self) -> None:
        candidate = FindingCandidate(
            statement="Conclusion",
            rationale="Because",
            evidence_refs=(),
        )
        with self.assertRaises(InvalidAnalysisProvenanceError):
            validate_finding_candidate(
                candidate,
                evidence_by_id={"ev-1": self.evidence},
                project_id="project-1",
                workflow_run_id="run-a",
                research_design_id="design-1",
                design=_design(),
            )

    def test_rejects_cross_run_evidence(self) -> None:
        candidate = FindingCandidate(
            statement="Conclusion",
            rationale="Because",
            evidence_refs=("ev-1",),
        )
        with self.assertRaises(InvalidAnalysisProvenanceError):
            validate_finding_candidate(
                candidate,
                evidence_by_id={"ev-1": self.evidence},
                project_id="project-1",
                workflow_run_id="run-b",
                research_design_id="design-1",
                design=_design(),
            )

    def test_rejects_cross_run_finding_for_insight(self) -> None:
        candidate = InsightCandidate(
            statement="Insight",
            implication="Monitor",
            finding_refs=("finding-1",),
        )
        with self.assertRaises(InvalidAnalysisProvenanceError):
            validate_insight_candidate(
                candidate,
                findings_by_id={"finding-1": self.finding},
                project_id="project-1",
                workflow_run_id="run-b",
                research_design_id="design-1",
                design=_design(),
            )

    def test_rejects_invalid_confidence(self) -> None:
        candidate = FindingCandidate(
            statement="Conclusion",
            rationale="Because",
            evidence_refs=("ev-1",),
            confidence=1.5,
        )
        with self.assertRaises(InvalidAnalysisProvenanceError):
            validate_finding_candidate(
                candidate,
                evidence_by_id={"ev-1": self.evidence},
                project_id="project-1",
                workflow_run_id="run-a",
                research_design_id="design-1",
                design=_design(),
            )


class DeduplicationTests(unittest.TestCase):
    def test_finding_dedup_is_stable(self) -> None:
        key_a = compute_finding_deduplication_key(
            workflow_run_id="run-a",
            statement="Company X is growing.",
            evidence_refs=("ev-2", "ev-1"),
        )
        key_b = compute_finding_deduplication_key(
            workflow_run_id="run-a",
            statement="  Company   X is growing. ",
            evidence_refs=("ev-1", "ev-2"),
        )
        self.assertEqual(key_a, key_b)

    def test_insight_dedup_differs_by_finding_refs(self) -> None:
        key_a = compute_insight_deduplication_key(
            workflow_run_id="run-a",
            statement="Momentum insight",
            finding_refs=("f1",),
        )
        key_b = compute_insight_deduplication_key(
            workflow_run_id="run-a",
            statement="Momentum insight",
            finding_refs=("f2",),
        )
        self.assertNotEqual(key_a, key_b)


if __name__ == "__main__":
    unittest.main()
