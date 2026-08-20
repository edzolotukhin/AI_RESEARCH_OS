from __future__ import annotations

import inspect
import unittest
from dataclasses import replace
from decimal import Decimal

from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from domain.findings.finding import Finding as DeskFinding
from domain.quantitative.analysis import AnalyticalComparisonResult, StatisticalResult
from domain.quantitative.finding import (
    QuantitativeClaim,
    QuantitativeClaimType,
    QuantitativeComparisonReference,
    QuantitativeFinding,
    QuantitativeResultReference,
    QuantitativeSupportStatus,
)
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


def result(
    result_id: str,
    value: str,
    *,
    statistic_type: str = "VALID_PERCENTAGE",
    category: str | None = "X",
    fingerprint: str | None = None,
    weighting: str = "UNWEIGHTED",
    weight_fingerprint: str | None = None,
    filter_definition: str = "ALL_ROWS",
    column: str | None = None,
) -> StatisticalResult:
    return StatisticalResult(
        result_id=result_id,
        dataset_version_id="dataset-v1",
        dataset_fingerprint="dataset-fp",
        data_fingerprint="data-fp",
        codebook_fingerprint="codebook-fp",
        variable_id="question",
        variable_fingerprint="variable-fp",
        analysis_specification_id="spec",
        analysis_specification_fingerprint="spec-fp",
        weighting_status=weighting,
        filter_definition=filter_definition,
        base_definition="VALID_RESPONSES",
        missing_value_semantics=({"kind": "DECLARED"},),
        statistic_type=statistic_type,
        value=Decimal(value),
        denominator=100,
        category_value=category,
        computation_method="deterministic",
        computation_version="v1",
        presentation_eligible=True,
        reproducibility_fingerprint=fingerprint or f"fp-{result_id}",
        weight_set_id="weights" if weight_fingerprint else None,
        weight_set_fingerprint=weight_fingerprint,
        analytical_view_id="view",
        analytical_view_fingerprint="view-fp",
        unweighted_n=42,
        weighted_base=Decimal("100") if weight_fingerprint else None,
        row_variable_id="question" if column else None,
        row_category_value=category if column else None,
        column_variable_id="group" if column else None,
        column_category_value=column,
    )


def finding(
    claim_type: QuantitativeClaimType,
    results: tuple[StatisticalResult, ...],
    *,
    value: str | None,
    statistic_type: str,
    category: str | None = None,
    direction: str | None = None,
    comparison: AnalyticalComparisonResult | None = None,
    display_value: str | None = None,
) -> QuantitativeFinding:
    first = results[0]
    return QuantitativeFinding(
        finding_id="finding-1",
        text="Structured quantitative claim.",
        claim=QuantitativeClaim(
            claim_type=claim_type,
            value=Decimal(value) if value is not None else None,
            variable_id=first.variable_id,
            statistic_type=statistic_type,
            category_value=category,
            filter_definition=first.filter_definition,
            base_definition=first.base_definition,
            weighting_status=first.weighting_status,
            weight_set_fingerprint=first.weight_set_fingerprint,
            direction=direction,
            display_value=display_value,
        ),
        statistical_result_refs=tuple(
            QuantitativeResultReference(item.result_id, item.reproducibility_fingerprint)
            for item in results
        ),
        comparison_result_refs=(
            (QuantitativeComparisonReference(
                comparison.comparison_result_id,
                comparison.reproducibility_fingerprint,
            ),)
            if comparison else ()
        ),
    )


def comparison(a: StatisticalResult, b: StatisticalResult, *, significant: bool = True) -> AnalyticalComparisonResult:
    return AnalyticalComparisonResult(
        comparison_result_id="comparison-1",
        dataset_version_id=a.dataset_version_id,
        dataset_fingerprint=a.dataset_fingerprint,
        data_fingerprint=a.data_fingerprint,
        specification_id="comparison-spec",
        specification_fingerprint="comparison-spec-fp",
        group_a_result_id=a.result_id,
        group_a_result_fingerprint=a.reproducibility_fingerprint,
        group_b_result_id=b.result_id,
        group_b_result_fingerprint=b.reproducibility_fingerprint,
        observed_difference=Decimal(str(a.value)) - Decimal(str(b.value)),
        test_statistic=Decimal("3.1"),
        p_value=Decimal("0.01") if significant else Decimal("0.4"),
        alpha=Decimal("0.05"),
        significant=significant,
        sidedness="TWO_SIDED",
        minimum_group_base=2,
        group_a_base=100,
        group_b_base=100,
        method="INDEPENDENT_TWO_PROPORTION_Z_TEST",
        method_version="qg-1",
        reproducibility_fingerprint="comparison-fp-significant" if significant else "comparison-fp-nonsignificant",
    )


class PropertyQHQuantitativeFindingSupportContractTests(unittest.TestCase):
    def setUp(self):
        self.validator = QuantitativeFindingSupportValidator(
            digest_provider=Sha256DigestProvider(),
        )

    def validate(self, item, results, comparisons=()):
        return self.validator.validate(
            item,
            statistical_results={result.result_id: result for result in results},
            comparison_results={result.comparison_result_id: result for result in comparisons},
        )

    def test_supported_percentage_mean_and_nps_findings(self):
        cases = (
            (result("percentage", "42", category="X"), QuantitativeClaimType.DESCRIPTIVE_VALUE, "VALID_PERCENTAGE", "X"),
            (result("mean", "7.4", statistic_type="NUMERIC_MEAN", category=None), QuantitativeClaimType.NUMERIC_SUMMARY, "NUMERIC_MEAN", None),
            (result("nps", "36", statistic_type="NPS", category=None), QuantitativeClaimType.KPI_VALUE, "NPS", None),
        )
        for authority, claim_type, statistic_type, category in cases:
            item = finding(claim_type, (authority,), value=str(authority.value), statistic_type=statistic_type, category=category, display_value=f"{authority.value:.1f}")
            validated = self.validate(item, (authority,))
            self.assertEqual(validated.support_validation_status, QuantitativeSupportStatus.SUPPORTED)
            self.assertTrue(validated.analytical_context_fingerprint)
            self.assertTrue(validated.support_validation_fingerprint)

    def test_supported_descriptive_and_significant_comparisons(self):
        a = result("a", "70", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="WOMEN")
        b = result("b", "40", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="MEN")
        descriptive = finding(QuantitativeClaimType.DESCRIPTIVE_COMPARISON, (a, b), value="30", statistic_type=a.statistic_type, category="X", direction="HIGHER")
        self.assertEqual(self.validate(descriptive, (a, b)).support_validation_status, QuantitativeSupportStatus.SUPPORTED)
        qg = comparison(a, b)
        significant = finding(QuantitativeClaimType.SIGNIFICANT_COMPARISON, (a, b), value="30", statistic_type=a.statistic_type, category="X", direction="HIGHER", comparison=qg)
        self.assertEqual(self.validate(significant, (a, b), (qg,)).support_validation_status, QuantitativeSupportStatus.SUPPORTED)

    def test_significance_wording_fails_without_compatible_significant_result(self):
        a = result("a", "55", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="A")
        b = result("b", "50", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="B")
        no_reference = finding(QuantitativeClaimType.SIGNIFICANT_COMPARISON, (a, b), value="5", statistic_type=a.statistic_type, category="X", direction="HIGHER")
        with self.assertRaisesRegex(ValueError, "ComparisonResult"):
            self.validate(no_reference, (a, b))
        qg = comparison(a, b, significant=False)
        nonsignificant = finding(QuantitativeClaimType.SIGNIFICANT_COMPARISON, (a, b), value="5", statistic_type=a.statistic_type, category="X", direction="HIGHER", comparison=qg)
        with self.assertRaisesRegex(ValueError, "significance wording"):
            self.validate(nonsignificant, (a, b), (qg,))

    def test_wrong_weight_filter_category_and_numeric_value_fail_closed(self):
        authority = result("percentage", "42", category="X")
        baseline = finding(QuantitativeClaimType.DESCRIPTIVE_VALUE, (authority,), value="42", statistic_type=authority.statistic_type, category="X", display_value="42.0")
        bad_claims = (
            replace(baseline, claim=replace(baseline.claim, weighting_status="WEIGHTED", weight_set_fingerprint="other")),
            replace(baseline, claim=replace(baseline.claim, filter_definition="region=NORTH")),
            replace(baseline, claim=replace(baseline.claim, category_value="Y")),
            replace(baseline, claim=replace(baseline.claim, value=Decimal("43"), display_value="43.0")),
        )
        for item in bad_claims:
            with self.assertRaises(ValueError):
                self.validate(item, (authority,))

    def test_missing_and_stale_references_fail_closed(self):
        authority = result("percentage", "42", category="X")
        item = finding(QuantitativeClaimType.DESCRIPTIVE_VALUE, (authority,), value="42", statistic_type=authority.statistic_type, category="X", display_value="42.0")
        with self.assertRaisesRegex(ValueError, "missing"):
            self.validator.validate(item, statistical_results={})
        altered = replace(authority, reproducibility_fingerprint="altered")
        with self.assertRaisesRegex(ValueError, "stale|altered"):
            self.validate(item, (altered,))

    def test_direction_contradiction_and_comparison_mismatch_fail_closed(self):
        a = result("a", "40", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="A")
        b = result("b", "60", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="B")
        contradicted = finding(QuantitativeClaimType.DESCRIPTIVE_COMPARISON, (a, b), value="-20", statistic_type=a.statistic_type, category="X", direction="HIGHER")
        with self.assertRaisesRegex(ValueError, "direction"):
            self.validate(contradicted, (a, b))
        qg = replace(comparison(a, b), group_a_result_fingerprint="wrong")
        significant = finding(QuantitativeClaimType.SIGNIFICANT_COMPARISON, (a, b), value="-20", statistic_type=a.statistic_type, category="X", direction="LOWER", comparison=qg)
        with self.assertRaisesRegex(ValueError, "incompatible"):
            self.validate(significant, (a, b), (qg,))

    def test_rounding_is_deterministic_and_not_authority(self):
        authority = result("mean", "7.45", statistic_type="NUMERIC_MEAN", category=None)
        self.assertEqual(self.validator.display_value(Decimal("7.45"), decimal_places=1), "7.5")
        item = finding(QuantitativeClaimType.NUMERIC_SUMMARY, (authority,), value="7.45", statistic_type=authority.statistic_type, display_value="7.5")
        first = self.validate(item, (authority,)); second = self.validate(item, (authority,))
        self.assertEqual(first, second)
        with self.assertRaisesRegex(ValueError, "rounding"):
            self.validate(replace(item, claim=replace(item.claim, display_value="7.4")), (authority,))

    def test_changed_authority_changes_support_fingerprint(self):
        first_result = result("mean-a", "7.4", statistic_type="NUMERIC_MEAN", category=None)
        second_result = result("mean-b", "7.5", statistic_type="NUMERIC_MEAN", category=None)
        first = finding(QuantitativeClaimType.NUMERIC_SUMMARY, (first_result,), value="7.4", statistic_type="NUMERIC_MEAN", display_value="7.4")
        second = replace(finding(QuantitativeClaimType.NUMERIC_SUMMARY, (second_result,), value="7.5", statistic_type="NUMERIC_MEAN", display_value="7.5"), finding_id=first.finding_id)
        self.assertNotEqual(self.validate(first, (first_result,)).support_validation_fingerprint, self.validate(second, (second_result,)).support_validation_fingerprint)

    def test_pii_and_desk_evidence_support_are_rejected_or_absent(self):
        authority = result("percentage", "42", category="X")
        item = finding(QuantitativeClaimType.DESCRIPTIVE_VALUE, (authority,), value="42", statistic_type=authority.statistic_type, category="X", display_value="42.0")
        with self.assertRaisesRegex(ValueError, "PII"):
            self.validate(replace(item, pii_exposures=("telephone",)), (authority,))
        self.assertFalse(hasattr(item, "evidence_refs"))
        import application.quantitative.finding_support as module
        source = inspect.getsource(module)
        for forbidden in ("domain.findings", "domain.evidence", "InformationNeed", "llm_client", "openai", "tavily"):
            self.assertNotIn(forbidden, source)

    def test_existing_desk_finding_contract_is_unchanged(self):
        desk = DeskFinding("f", "p", "run", "design", "Desk claim", "why", ("evidence-1",), "now")
        self.assertEqual(desk.evidence_refs, ("evidence-1",))
        self.assertNotIn("statistical_result_refs", desk.to_dict())


if __name__ == "__main__":
    unittest.main()
