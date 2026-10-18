from __future__ import annotations

import unittest

from application.report.claim_scope_validation import validate_claim_scope
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight


class ClaimScopeValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.finding = Finding(
            id="f1", project_id="p", workflow_run_id="r", research_design_id="d",
            statement="Kyiv and Lviv had wages below the national average.",
            rationale="Observed in the supplied regional records.", evidence_refs=("e1",),
            created_at="2026-01-01", research_question_refs=("rq1",),
        )
        self.evidence = Evidence(
            id="e1", project_id="p", source_id="s1", source_content_checksum="x",
            workflow_run_id="r", research_design_id="d",
            statement="Kyiv and Lviv had wages below the national average.",
            source_excerpt="Kyiv and Lviv had wages below the national average.",
            created_at="2026-01-01",
        )

    def _check(self, content: str) -> tuple[str, ...]:
        return validate_claim_scope(
            content,
            finding_ids=("f1",),
            findings_by_id={"f1": self.finding},
            insights_by_id={},
            evidence_by_id={"e1": self.evidence},
        )

    def test_geographic_and_prevalence_broadening_is_rejected(self) -> None:
        self.assertTrue(self._check("Southern and western regions are mostly below average."))

    def test_population_broadening_is_rejected(self) -> None:
        self.assertTrue(self._check("All people in Ukraine have lower wages."))

    def test_causal_broadening_is_rejected(self) -> None:
        self.assertTrue(self._check("The war caused lower wages across Ukraine."))

    def test_valid_paraphrase_is_retained(self) -> None:
        self.assertEqual(self._check("Kyiv and Lviv recorded wages under the national average."), ())

    def test_supported_multi_finding_synthesis_is_retained(self) -> None:
        second = Finding(
            id="f2", project_id="p", workflow_run_id="r", research_design_id="d",
            statement="Odesa had wages above the national average.", rationale="Observed.",
            evidence_refs=("e1",), created_at="2026-01-01", research_question_refs=("rq1",),
        )
        self.assertEqual(
            validate_claim_scope(
                "Kyiv, Lviv and Odesa were observed at different wage levels.",
                finding_ids=("f1", "f2"), findings_by_id={"f1": self.finding, "f2": second},
                insights_by_id={}, evidence_by_id={"e1": self.evidence},
            ),
            (),
        )
