from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from application.quantitative.one_way_statistics import QuantitativeAnalysisError
from domain.quantitative.analysis import AnalyticalComparisonResult, StatisticalResult
from domain.quantitative.finding import (
    QuantitativeClaimType,
    QuantitativeFinding,
    QuantitativeSupportStatus,
)


SUPPORT_VALIDATION_VERSION = "qh-1"
ROUNDING_VERSION = "QH_DISPLAY_V1"


class QuantitativeFindingSupportValidator:
    """Fail-closed support gate over deterministic Quantitative authorities."""

    def __init__(self, *, digest_provider: DeterministicDigestProvider) -> None:
        self._digest = digest_provider

    def validate(
        self,
        finding: QuantitativeFinding,
        *,
        statistical_results: Mapping[str, StatisticalResult],
        comparison_results: Mapping[str, AnalyticalComparisonResult] | None = None,
    ) -> QuantitativeFinding:
        comparisons = comparison_results or {}
        self._validate_finding_shape(finding)
        results = self._resolve_results(finding, statistical_results)
        resolved_comparisons = self._resolve_comparisons(finding, comparisons)
        self._validate_common_context(finding, results)

        claim_type = finding.claim.claim_type
        if claim_type is QuantitativeClaimType.DESCRIPTIVE_VALUE:
            self._validate_single(finding, results, {
                "VALID_PERCENTAGE", "WEIGHTED_PERCENTAGE",
                "CROSS_TAB_COLUMN_PERCENTAGE",
            })
        elif claim_type is QuantitativeClaimType.NUMERIC_SUMMARY:
            self._validate_single(finding, results, {
                "NUMERIC_MEAN", "NUMERIC_WEIGHTED_MEAN", "NUMERIC_MEDIAN",
                "NUMERIC_MINIMUM", "NUMERIC_MAXIMUM",
            })
        elif claim_type is QuantitativeClaimType.KPI_VALUE:
            self._validate_single(finding, results, {"NPS", "CUSTOM_INDEX"})
        elif claim_type is QuantitativeClaimType.DESCRIPTIVE_COMPARISON:
            self._validate_direction(finding, results)
            if resolved_comparisons:
                raise QuantitativeAnalysisError("descriptive comparison must not claim significance authority")
        elif claim_type is QuantitativeClaimType.SIGNIFICANT_COMPARISON:
            self._validate_direction(finding, results)
            self._validate_significance(results, resolved_comparisons)
        else:  # pragma: no cover - enum prevents ordinary construction
            raise QuantitativeAnalysisError("unsupported Quantitative Finding claim type")

        context_payload = self._context_payload(finding, results)
        context_fingerprint = canonical_digest(context_payload, digest_provider=self._digest)
        support_payload = {
            "finding_id": finding.finding_id,
            "methodology": finding.methodology,
            "claim": self._claim_payload(finding),
            "statistical_results": tuple(
                (item.result_id, item.reproducibility_fingerprint) for item in results
            ),
            "comparison_results": tuple(
                (item.comparison_result_id, item.reproducibility_fingerprint)
                for item in resolved_comparisons
            ),
            "analytical_context_fingerprint": context_fingerprint,
            "rounding_version": finding.rounding_version,
            "validation_version": SUPPORT_VALIDATION_VERSION,
        }
        support_fingerprint = canonical_digest(support_payload, digest_provider=self._digest)
        return replace(
            finding,
            analytical_context_fingerprint=context_fingerprint,
            support_validation_status=QuantitativeSupportStatus.SUPPORTED,
            support_validation_fingerprint=support_fingerprint,
            support_validation_version=SUPPORT_VALIDATION_VERSION,
        )

    @staticmethod
    def display_value(value: Decimal, *, decimal_places: int) -> str:
        if decimal_places < 0 or decimal_places > 12 or not value.is_finite():
            raise QuantitativeAnalysisError("invalid display rounding input")
        quantum = Decimal(1).scaleb(-decimal_places)
        rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
        return format(rounded, f".{decimal_places}f")

    def _validate_finding_shape(self, finding: QuantitativeFinding) -> None:
        if finding.methodology != "QUANTITATIVE":
            raise QuantitativeAnalysisError("Quantitative support cannot validate Desk methodology")
        if not finding.finding_id or not finding.text.strip() or finding.pii_exposures:
            raise QuantitativeAnalysisError("Quantitative Finding contains missing identity or PII exposure")
        if finding.rounding_policy != "ROUND_HALF_UP" or finding.rounding_version != ROUNDING_VERSION:
            raise QuantitativeAnalysisError("unsupported display rounding contract")
        if finding.rounding_decimal_places < 0 or finding.rounding_decimal_places > 12:
            raise QuantitativeAnalysisError("invalid display rounding precision")

    @staticmethod
    def _resolve_results(finding, available):
        if not finding.statistical_result_refs:
            raise QuantitativeAnalysisError("missing referenced StatisticalResult")
        resolved = []
        seen = set()
        for reference in finding.statistical_result_refs:
            result = available.get(reference.result_id)
            if result is None:
                raise QuantitativeAnalysisError("missing referenced StatisticalResult")
            if result.reproducibility_fingerprint != reference.reproducibility_fingerprint:
                raise QuantitativeAnalysisError("stale or altered StatisticalResult fingerprint")
            if result.result_id in seen:
                raise QuantitativeAnalysisError("duplicate StatisticalResult reference")
            seen.add(result.result_id)
            resolved.append(result)
        return tuple(resolved)

    @staticmethod
    def _resolve_comparisons(finding, available):
        resolved = []
        for reference in finding.comparison_result_refs:
            result = available.get(reference.comparison_result_id)
            if result is None:
                raise QuantitativeAnalysisError("missing referenced ComparisonResult")
            if result.reproducibility_fingerprint != reference.reproducibility_fingerprint:
                raise QuantitativeAnalysisError("stale or altered ComparisonResult fingerprint")
            resolved.append(result)
        return tuple(resolved)

    @staticmethod
    def _validate_common_context(finding, results):
        first = results[0]
        keys = (
            "dataset_version_id", "dataset_fingerprint", "data_fingerprint",
            "filter_definition", "base_definition", "weighting_status",
            "weight_set_fingerprint",
        )
        for result in results:
            if any(getattr(result, key) != getattr(first, key) for key in keys):
                raise QuantitativeAnalysisError("incompatible StatisticalResult analytical contexts")
            if result.variable_id != finding.claim.variable_id:
                raise QuantitativeAnalysisError("mismatched Finding variable")
        claim = finding.claim
        if (
            claim.filter_definition != first.filter_definition
            or claim.base_definition != first.base_definition
            or claim.weighting_status != first.weighting_status
            or claim.weight_set_fingerprint != first.weight_set_fingerprint
        ):
            raise QuantitativeAnalysisError("Finding filter/base/weighting context is incompatible")

    def _validate_single(self, finding, results, permitted_types):
        if len(results) != 1 or finding.comparison_result_refs:
            raise QuantitativeAnalysisError("single-value Finding requires exactly one StatisticalResult")
        result = results[0]
        claim = finding.claim
        if result.statistic_type not in permitted_types or claim.statistic_type != result.statistic_type:
            raise QuantitativeAnalysisError("unsupported or mismatched statistic type")
        if claim.category_value != result.category_value:
            raise QuantitativeAnalysisError("mismatched Finding category")
        if claim.value is None or Decimal(str(result.value)) != claim.value:
            raise QuantitativeAnalysisError("unsupported numeric Finding value")
        expected_display = self.display_value(claim.value, decimal_places=finding.rounding_decimal_places)
        if claim.display_value != expected_display:
            raise QuantitativeAnalysisError("unsupported Finding display rounding")

    @staticmethod
    def _validate_direction(finding, results):
        if len(results) != 2:
            raise QuantitativeAnalysisError("comparison Finding requires two StatisticalResults")
        a, b = results
        if a.statistic_type != b.statistic_type or finding.claim.statistic_type != a.statistic_type:
            raise QuantitativeAnalysisError("comparison statistics are incompatible")
        if finding.claim.category_value is not None and any(
            item.row_category_value != finding.claim.category_value for item in results
        ):
            raise QuantitativeAnalysisError("comparison outcome category is incompatible")
        observed = Decimal(str(a.value)) - Decimal(str(b.value))
        expected = "HIGHER" if observed > 0 else "LOWER" if observed < 0 else "EQUAL"
        if finding.claim.direction != expected:
            raise QuantitativeAnalysisError("observed comparison direction is contradicted by results")
        if finding.claim.value is not None and finding.claim.value != observed:
            raise QuantitativeAnalysisError("unsupported comparison difference")

    @staticmethod
    def _validate_significance(results, comparisons):
        if len(comparisons) != 1:
            raise QuantitativeAnalysisError("significance wording requires one ComparisonResult")
        comparison = comparisons[0]
        a, b = results
        if not comparison.supports_significance_wording:
            raise QuantitativeAnalysisError("ComparisonResult does not support significance wording")
        if (
            comparison.dataset_version_id != a.dataset_version_id
            or comparison.dataset_fingerprint != a.dataset_fingerprint
            or comparison.data_fingerprint != a.data_fingerprint
            or comparison.group_a_result_id != a.result_id
            or comparison.group_a_result_fingerprint != a.reproducibility_fingerprint
            or comparison.group_b_result_id != b.result_id
            or comparison.group_b_result_fingerprint != b.reproducibility_fingerprint
        ):
            raise QuantitativeAnalysisError("ComparisonResult is incompatible with referenced results")

    @staticmethod
    def _context_payload(finding, results):
        first = results[0]
        return {
            "dataset_version_id": first.dataset_version_id,
            "dataset_fingerprint": first.dataset_fingerprint,
            "data_fingerprint": first.data_fingerprint,
            "codebook_fingerprint": first.codebook_fingerprint,
            "variable_id": finding.claim.variable_id,
            "filter_definition": first.filter_definition,
            "base_definition": first.base_definition,
            "weighting_status": first.weighting_status,
            "weight_set_fingerprint": first.weight_set_fingerprint,
            "missing_value_semantics": first.missing_value_semantics,
        }

    @staticmethod
    def _claim_payload(finding):
        claim = finding.claim
        return {
            "claim_type": claim.claim_type.value,
            "value": canonical_scalar(claim.value),
            "variable_id": claim.variable_id,
            "statistic_type": claim.statistic_type,
            "category_value": canonical_scalar(claim.category_value),
            "filter_definition": claim.filter_definition,
            "base_definition": claim.base_definition,
            "weighting_status": claim.weighting_status,
            "weight_set_fingerprint": claim.weight_set_fingerprint,
            "direction": claim.direction,
            "display_value": claim.display_value,
        }
