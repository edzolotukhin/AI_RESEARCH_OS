from __future__ import annotations

import unittest

from application.report.claim_scope_validation import (
    validate_claim_scope,
    validate_claim_scope_with_diagnostics,
)
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

    def _diagnose(self, content: str):
        return validate_claim_scope_with_diagnostics(
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

    def test_unsupported_rate_is_rejected(self) -> None:
        self.assertTrue(self._check("Each hour costs about $45m."))

    def test_numeric_substitution_is_rejected(self) -> None:
        self.assertTrue(self._check("Kyiv recorded wages of 32000 грн."))

    def test_supported_numeric_statement_is_retained(self) -> None:
        self.evidence.statement = "Kyiv had wages of 45000 грн."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        self.assertEqual(self._check("Kyiv recorded wages of 45000 грн."), ())

    def test_unit_change_is_rejected(self) -> None:
        self.evidence.statement = "The increase was 10 percent."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        self.assertTrue(self._check("The increase was 10 percentage points."))

    def test_supported_quantifier_is_retained(self) -> None:
        self.evidence.statement = "All surveyed regions had wages below the average."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        self.assertEqual(self._check("All surveyed regions had wages below average."), ())

    def test_numeric_geography_binding_is_rejected(self) -> None:
        self.evidence.statement = "Kyiv had wages of 45000 грн."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        self.assertTrue(self._check("Luhansk had wages of 45000 грн."))

    def test_numeric_period_binding_is_rejected(self) -> None:
        self.evidence.statement = "In 2025 wages were 45000 грн."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        self.assertTrue(self._check("In 2026 wages were 45000 грн."))

    def test_same_supported_period_passes(self) -> None:
        self.evidence.statement = "In 2026 wages were 45000 грн."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        self.assertEqual(self._check("During 2026 wages were 45000 грн."), ())

    def test_candidate_year_subset_of_supported_years_passes(self) -> None:
        self.evidence.statement = "In 2026 and 2028 wages were 45000 грн."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        self.assertEqual(self._check("During 2026 wages were 45000 грн."), ())

    def test_unsupported_year_still_fails(self) -> None:
        self.evidence.statement = "In 2026 wages were 45000 грн."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        self.assertIn("unsupported numeric scope", self._check("During 2025 wages were 45000 грн.")[0])

    def test_lexical_period_context_does_not_create_scope_failure(self) -> None:
        self.evidence.statement = "За 2026 рік wages were 45000 грн."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        self.assertEqual(self._check("На 2026 року wages were 45000 грн."), ())

    def test_non_temporal_numbers_are_not_period_anchors(self) -> None:
        self.evidence.statement = "Kyiv had an index of 6 and wages of 45000 грн."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        self.assertFalse(any("unsupported numeric scope" in error for error in self._check(
            "Kyiv had an index of 8 and wages of 45000 грн."
        )))

    def test_percentages_are_not_period_anchors(self) -> None:
        self.evidence.statement = "Kyiv recorded 6.5% growth and wages of 45000 грн."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        self.assertFalse(any("unsupported numeric scope" in error for error in self._check(
            "Kyiv recorded 8% growth and wages of 45000 грн."
        )))

    def test_broadening_diagnostics_are_bounded_and_non_prose(self) -> None:
        errors, mismatch = self._diagnose("All people in Ukraine have lower wages.")
        self.assertTrue(errors)
        self.assertEqual(mismatch["rule"], "broadening_scope")
        self.assertLessEqual(len(mismatch["rejected_tokens"]), 8)

    def test_numeric_value_diagnostics_are_bounded(self) -> None:
        self.evidence.statement = "Kyiv had wages of 45000 грн."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        errors, mismatch = self._diagnose("Kyiv recorded wages of 32000 грн.")
        self.assertTrue(errors)
        self.assertEqual(mismatch["rule"], "unsupported_numeric_value")
        self.assertEqual(mismatch["candidate_value"], "32000")
        self.assertLessEqual(len(mismatch["supported_values"]), 8)

    def test_numeric_unit_diagnostics_are_bounded(self) -> None:
        self.evidence.statement = "The increase was 10%."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        errors, mismatch = self._diagnose("The increase was 10 percentage points.")
        self.assertTrue(errors)
        self.assertEqual(mismatch["rule"], "unsupported_numeric_unit")
        self.assertLessEqual(len(mismatch["supported_units"]), 8)

    def test_numeric_scope_diagnostics_expose_anchor_category(self) -> None:
        self.evidence.statement = "In 2025 wages were 45000 грн."
        self.evidence.source_excerpt = self.evidence.statement
        self.finding.statement = self.evidence.statement
        errors, mismatch = self._diagnose("In 2026 wages were 45000 грн.")
        self.assertTrue(errors)
        self.assertEqual(mismatch["rule"], "unsupported_numeric_scope")
        self.assertEqual(mismatch["anchor_category"], "period")
        self.assertLessEqual(len(mismatch["candidate_anchors"]), 8)

    def test_diagnostics_do_not_contain_support_or_claim_prose(self) -> None:
        _, mismatch = self._diagnose("In 2026 wages were 45000 грн.")
        serialized = repr(mismatch)
        self.assertNotIn("Kyiv had wages", serialized)
        self.assertNotIn("In 2026 wages", serialized)
