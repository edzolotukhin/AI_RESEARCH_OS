from __future__ import annotations

import unittest

from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight


class FindingModelTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        finding = Finding(
            id="f1",
            project_id="p1",
            workflow_run_id="run1",
            research_design_id="design1",
            statement="Company X is growing faster than peers.",
            rationale="Multiple evidence items show above-benchmark growth.",
            evidence_refs=("ev1", "ev2"),
            created_at="2026-01-01T00:00:00+00:00",
            finding_type=FindingType.SYNTHESIS,
            confidence=0.8,
            analysis_method="deterministic",
            deduplication_key="dedup1",
            metadata={"deterministic": "true"},
            version=1,
        )
        restored = Finding.from_dict(finding.to_dict())
        self.assertEqual(restored.statement, finding.statement)
        self.assertEqual(restored.evidence_refs, finding.evidence_refs)


class InsightModelTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        insight = Insight(
            id="i1",
            project_id="p1",
            workflow_run_id="run1",
            research_design_id="design1",
            statement="Company X may be gaining momentum.",
            implication="Prioritize monitoring Company X.",
            finding_refs=("f1",),
            created_at="2026-01-01T00:00:00+00:00",
            confidence=0.7,
            deduplication_key="dedup1",
            metadata={"deterministic": "true"},
            version=1,
        )
        restored = Insight.from_dict(insight.to_dict())
        self.assertEqual(restored.finding_refs, insight.finding_refs)


if __name__ == "__main__":
    unittest.main()
