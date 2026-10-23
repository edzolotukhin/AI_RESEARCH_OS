from __future__ import annotations

import unittest

from application.report.claim_scope_validation import (
    validate_claim_scope,
    validate_claim_scope_with_diagnostics,
)
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from application.research_scope.authoritative_scope import SCOPE_KEY, SCOPE_VERSION
from application.research_scope.authoritative_scope import sanitize_scope


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

    def _check_with_scope(self, content: str, claim_scope: dict) -> tuple[str, ...]:
        return validate_claim_scope(
            content,
            finding_ids=("f1",),
            findings_by_id={"f1": self.finding},
            insights_by_id={},
            evidence_by_id={"e1": self.evidence},
            claim_scope=claim_scope,
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
        self.finding.metadata[SCOPE_KEY] = {
            "version": SCOPE_VERSION,
            "geography": ["Kyiv"],
            "geography_anchors": [{"value": "Kyiv", "level": "subnational"}],
            "numeric_facts": [{
                "value": "45000", "unit": "грн", "periods": ["2026"],
                "geography": ["Kyiv"],
            }],
        }
        errors = self._check_with_scope(
            "Regional wage was 45000 грн in 2026.",
            {
                "version": SCOPE_VERSION,
                "geography": ["Luhansk"],
                "geography_anchors": [
                    {"value": "Luhansk", "level": "subnational"},
                ],
                "numeric_facts": [{
                    "value": "45000", "unit": "грн", "periods": ["2026"],
                    "geography": ["Luhansk"],
                }],
            },
        )
        self.assertIn("Report claim uses unsupported geography scope", errors)
        self.assertTrue(any("geography" in error for error in errors))

    def test_numeric_value_keeps_supported_geography_binding(self) -> None:
        self.finding.metadata[SCOPE_KEY] = {
            "version": SCOPE_VERSION,
            "geography": ["Kyiv"],
            "geography_anchors": [{"value": "Kyiv", "level": "subnational"}],
            "numeric_facts": [{
                "value": "45000", "unit": "грн", "periods": ["2026"],
                "geography": ["Kyiv"],
            }],
        }
        self.assertEqual(self._check_with_scope(
            "Regional wage was 45000 грн in 2026.",
            {
                "version": SCOPE_VERSION,
                "geography": ["Kyiv"],
                "numeric_facts": [{
                    "value": "45000", "unit": "грн", "periods": ["2026"],
                    "geography": ["Kyiv"],
                }],
            },
        ), ())

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

    def test_structured_supported_geography_passes(self) -> None:
        self.finding.metadata[SCOPE_KEY] = {
            "version": SCOPE_VERSION, "geography": ["Kyiv"], "periods": ["2026"],
            "metrics": ["wages"], "population_dimensions": ["employees"],
            "numeric_facts": [{"value": "45000", "unit": "грн", "periods": ["2026"]}],
        }
        self.finding.statement = "Wages were supported by the cited record."
        self.evidence.statement = "Kyiv wages were 45000 грн in 2026."
        self.evidence.source_excerpt = self.evidence.statement
        self.assertEqual(self._check_with_scope(
            "Kyiv wages were 45000 грн in 2026.",
            {"version": SCOPE_VERSION, "geography": ["Kyiv"]},
        ), ())

    def test_structured_unsupported_geography_fails_independently(self) -> None:
        self.finding.metadata[SCOPE_KEY] = {
            "version": SCOPE_VERSION, "geography": ["Kyiv"], "periods": ["2026"],
            "metrics": ["wages"], "population_dimensions": [],
            "numeric_facts": [{"value": "45000", "unit": "грн", "periods": ["2026"]}],
        }
        errors, mismatch = validate_claim_scope_with_diagnostics(
            "Luhansk wages were 45000 грн in 2026.",
            finding_ids=("f1",), findings_by_id={"f1": self.finding},
            insights_by_id={}, evidence_by_id={"e1": self.evidence},
            claim_scope={"version": SCOPE_VERSION, "geography": ["Luhansk"]},
        )
        self.assertIn("Report claim uses unsupported geography scope", errors)
        self.assertEqual(mismatch["dimension"], "geography")

    def test_generic_capitalized_ukrainian_words_are_not_geography(self) -> None:
        self.finding.metadata[SCOPE_KEY] = {
            "version": SCOPE_VERSION,
            "geography": ["Україна"],
            "geography_anchors": [{"value": "Україна", "level": "country"}],
            "numeric_facts": [{"value": "45000", "unit": "грн"}],
        }
        self.assertEqual(
            self._check_with_scope(
                "Додатково Мінімальна Номінальна кількість становила 45000 грн.",
                {"version": SCOPE_VERSION, "geography": ["Україна"]},
            ),
            (),
        )

    def test_structured_country_and_named_regions_are_independent(self) -> None:
        self.finding.metadata[SCOPE_KEY] = {
            "version": SCOPE_VERSION,
            "geography": ["Ukraine", "Kyiv", "Lviv"],
            "geography_anchors": [
                {"value": "Ukraine", "level": "country"},
                {"value": "Kyiv", "level": "subnational"},
                {"value": "Lviv", "level": "subnational"},
            ],
            "numeric_facts": [],
        }
        self.assertEqual(self._check_with_scope(
            "Supported geography.",
            {"version": SCOPE_VERSION, "geography": ["Ukraine", "Kyiv"]},
        ), ())
        self.assertTrue(self._check_with_scope(
            "Unsupported geography.",
            {"version": SCOPE_VERSION, "geography": ["Odesa"]},
        ))

    def test_geography_anchor_levels_are_bounded_and_backward_compatible(self) -> None:
        current = sanitize_scope({
            "version": SCOPE_VERSION,
            "geography": ["Ukraine", "Kyiv"],
            "geography_anchors": [
                {"value": "Ukraine", "level": "country"},
                {"value": "Kyiv", "level": "subnational"},
            ],
        })
        historical = sanitize_scope({
            "version": SCOPE_VERSION,
            "geography": ["Ukraine"],
            "numeric_facts": [{"value": "10", "unit": "%"}],
        })
        self.assertEqual(
            current["geography_anchors"],
            [
                {"value": "ukraine", "level": "country"},
                {"value": "kyiv", "level": "subnational"},
            ],
        )
        self.assertEqual(
            historical["geography_anchors"],
            [{"value": "ukraine", "level": "unspecified"}],
        )
        self.assertEqual(historical["numeric_facts"][0]["geography"], [])

    def test_multiple_scope_errors_keep_correlated_diagnostics(self) -> None:
        self.finding.metadata[SCOPE_KEY] = {
            "version": SCOPE_VERSION,
            "geography": ["Ukraine"],
            "numeric_facts": [{"value": "45000", "unit": "грн"}],
        }
        errors, mismatch = validate_claim_scope_with_diagnostics(
            "Foreign value was 99000 usd.",
            finding_ids=("f1",), findings_by_id={"f1": self.finding},
            insights_by_id={}, evidence_by_id={"e1": self.evidence},
            claim_scope={"version": SCOPE_VERSION, "geography": ["Poland"]},
        )
        self.assertGreaterEqual(len(errors), 2)
        rejections = mismatch["rejections"]
        self.assertEqual(rejections[0]["dimension"], "geography")
        self.assertEqual(rejections[0]["rule"], "broadening_scope")
        self.assertTrue(any(
            item["rule"] == "unsupported_numeric_value"
            and item["dimension"] == "numeric_value"
            for item in rejections
        ))

    def test_historical_finding_derives_only_from_authoritative_evidence(self) -> None:
        self.finding.metadata = {}
        self.evidence.metadata = {
            "observation_period": "2026",
            "semantic_assignment": {
                "contract_version": "desk_evidence_candidate_v2",
                "validation_version": "desk_semantic_assignment_v1",
                "geography_applicability": ["Kyiv"],
            },
        }
        self.evidence.statement = "Kyiv wages were 45000 грн in 2026."
        self.evidence.source_excerpt = self.evidence.statement
        self.assertEqual(self._check("Kyiv wages were 45000 грн in 2026."), ())
        self.assertTrue(self._check("Kyiv wages were 45000 грн in 2025."))

    def test_structured_metric_and_population_dimensions_are_independent(self) -> None:
        self.finding.metadata[SCOPE_KEY] = {
            "version": SCOPE_VERSION, "geography": ["Ukraine"],
            "periods": ["2026"], "metrics": ["real wages"],
            "population_dimensions": ["employees"], "numeric_facts": [],
        }
        common = dict(
            finding_ids=("f1",), findings_by_id={"f1": self.finding},
            insights_by_id={}, evidence_by_id={"e1": self.evidence},
        )
        self.assertEqual(validate_claim_scope(
            "Supported result.", claim_scope={
                "version": SCOPE_VERSION, "metrics": ["real wages"],
                "population_dimensions": ["employees"],
            }, **common,
        ), ())
        metric_errors = validate_claim_scope(
            "Unsupported metric.", claim_scope={
                "version": SCOPE_VERSION, "metrics": ["consumer prices"],
            }, **common,
        )
        population_errors = validate_claim_scope(
            "Unsupported population.", claim_scope={
                "version": SCOPE_VERSION,
                "population_dimensions": ["all households"],
            }, **common,
        )
        self.assertIn("Report claim uses unsupported metric scope", metric_errors)
        self.assertIn(
            "Report claim uses unsupported population_dimension scope",
            population_errors,
        )
