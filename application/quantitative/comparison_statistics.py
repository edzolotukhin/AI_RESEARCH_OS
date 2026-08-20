from __future__ import annotations

import math
from dataclasses import replace
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.ports.quantitative_dataset_ports import DatasetStorage
from application.quantitative.cross_tab_statistics import CrossTabStatisticsService
from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from application.quantitative.one_way_statistics import QuantitativeAnalysisError, _is_missing
from domain.quantitative.analysis import AnalyticalComparisonResult, ComparisonSpecification, StatisticalResult
from domain.quantitative.dataset import CodebookVersion, DatasetVersion, PiiClassification, VariableRole, VariableType
from domain.quantitative.weighting import AnalyticalDatasetView, WeightingMode


PROPORTION_METHOD = "INDEPENDENT_TWO_PROPORTION_Z_TEST"
MEAN_METHOD = "INDEPENDENT_WELCH_T_TEST"
COMPUTATION_VERSION = "qg-1"


class ComparisonStatisticsService:
    def __init__(self, *, storage: DatasetStorage, digest_provider: DeterministicDigestProvider) -> None:
        self._storage = storage
        self._digest = digest_provider

    def compare_proportions(self, *, dataset: DatasetVersion, codebook: CodebookVersion, specification: ComparisonSpecification, group_a_result: StatisticalResult, group_b_result: StatisticalResult, view: AnalyticalDatasetView) -> AnalyticalComparisonResult:
        self._validate_common(dataset, codebook, specification, group_a_result, group_b_result, view, PROPORTION_METHOD)
        if group_a_result.statistic_type != "CROSS_TAB_COLUMN_PERCENTAGE" or group_b_result.statistic_type != "CROSS_TAB_COLUMN_PERCENTAGE":
            raise QuantitativeAnalysisError("proportion comparison requires cross-tab column percentage results")
        if group_a_result.row_variable_id != specification.variable_id or group_b_result.row_variable_id != specification.variable_id or group_a_result.column_variable_id != specification.group_variable_id or group_b_result.column_variable_id != specification.group_variable_id or group_a_result.row_category_value != specification.outcome_category or group_b_result.row_category_value != specification.outcome_category or group_a_result.column_category_value != specification.group_a_category or group_b_result.column_category_value != specification.group_b_category:
            raise QuantitativeAnalysisError("compared proportion results do not match group definitions")
        n_a, n_b = self._integer_base(group_a_result.denominator), self._integer_base(group_b_result.denominator)
        x_a, x_b = group_a_result.unweighted_n, group_b_result.unweighted_n
        if x_a is None or x_b is None or not (0 <= x_a <= n_a and 0 <= x_b <= n_b):
            raise QuantitativeAnalysisError("invalid proportion result bases")
        self._minimum_bases(specification, n_a, n_b)
        p_a, p_b = x_a / n_a, x_b / n_b
        if not math.isclose(float(group_a_result.value), p_a * 100, rel_tol=1e-12, abs_tol=1e-12) or not math.isclose(float(group_b_result.value), p_b * 100, rel_tol=1e-12, abs_tol=1e-12):
            raise QuantitativeAnalysisError("stale or mismatched proportion StatisticalResult")
        pooled = (x_a + x_b) / (n_a + n_b)
        standard_error = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
        if standard_error == 0:
            raise QuantitativeAnalysisError("proportion comparison has zero standard error")
        statistic = (p_a - p_b) / standard_error
        p_value = math.erfc(abs(statistic) / math.sqrt(2))
        return self._result(dataset, specification, group_a_result, group_b_result, Decimal(str((p_a - p_b) * 100)), statistic, p_value, n_a, n_b, PROPORTION_METHOD)

    def compare_means(self, *, dataset: DatasetVersion, codebook: CodebookVersion, specification: ComparisonSpecification, group_a_result: StatisticalResult, group_b_result: StatisticalResult, view_a: AnalyticalDatasetView, view_b: AnalyticalDatasetView) -> AnalyticalComparisonResult:
        self._validate_common(dataset, codebook, specification, group_a_result, group_b_result, view_a, MEAN_METHOD)
        if view_b.weighting_mode is not WeightingMode.UNWEIGHTED or view_b.dataset_version_id != dataset.version_id or group_b_result.analytical_view_fingerprint != view_b.fingerprint:
            raise QuantitativeAnalysisError("incompatible group B analytical view")
        if group_a_result.statistic_type != "NUMERIC_MEAN" or group_b_result.statistic_type != "NUMERIC_MEAN" or group_a_result.variable_id != specification.variable_id or group_b_result.variable_id != specification.variable_id:
            raise QuantitativeAnalysisError("mean comparison requires compatible numeric mean results")
        expected_a = CrossTabStatisticsService.filter_definition(specification.group_variable_id, specification.group_a_category)
        expected_b = CrossTabStatisticsService.filter_definition(specification.group_variable_id, specification.group_b_category)
        if group_a_result.filter_definition != expected_a or group_b_result.filter_definition != expected_b:
            raise QuantitativeAnalysisError("mean result filters do not match group definitions")
        values_a, values_b = self._numeric_groups(dataset, codebook, specification)
        n_a, n_b = len(values_a), len(values_b)
        self._minimum_bases(specification, n_a, n_b)
        mean_a, mean_b = self._mean(values_a), self._mean(values_b)
        if Decimal(str(group_a_result.value)) != mean_a or Decimal(str(group_b_result.value)) != mean_b:
            raise QuantitativeAnalysisError("stale or mismatched mean StatisticalResult")
        variance_a, variance_b = self._variance(values_a, mean_a), self._variance(values_b, mean_b)
        term_a, term_b = float(variance_a) / n_a, float(variance_b) / n_b
        standard_error = math.sqrt(term_a + term_b)
        if standard_error == 0:
            raise QuantitativeAnalysisError("Welch comparison has zero standard error")
        statistic = float(mean_a - mean_b) / standard_error
        denominator = (term_a * term_a) / (n_a - 1) + (term_b * term_b) / (n_b - 1)
        degrees_freedom = ((term_a + term_b) ** 2) / denominator
        p_value = self._two_sided_student_t_p(statistic, degrees_freedom)
        return self._result(dataset, specification, group_a_result, group_b_result, mean_a - mean_b, statistic, p_value, n_a, n_b, MEAN_METHOD)

    def _validate_common(self, dataset, codebook, specification, result_a, result_b, view, method):
        if specification.method != method or specification.method_version != "QG_1" or specification.sidedness != "TWO_SIDED" or not specification.alpha.is_finite() or not Decimal(0) < specification.alpha < Decimal(1) or specification.minimum_group_base < 2 or specification.group_a_category == specification.group_b_category or specification.filter_definition != "ALL_ROWS":
            raise QuantitativeAnalysisError("invalid comparison specification")
        if not codebook.approved or codebook.fingerprint != dataset.codebook_fingerprint:
            raise QuantitativeAnalysisError("approved codebook must match dataset")
        outcome = codebook.variable_by_id(specification.variable_id); group = codebook.variable_by_id(specification.group_variable_id)
        for variable in (outcome, group):
            if not variable.analytically_eligible or variable.role in {VariableRole.TECHNICAL_ID, VariableRole.PII, VariableRole.WEIGHT} or variable.pii_classification is not PiiClassification.NONE:
                raise QuantitativeAnalysisError("comparison variable is not analytically eligible")
        if group.variable_type not in {VariableType.CATEGORICAL, VariableType.ORDINAL_SCALE, VariableType.DEMOGRAPHIC}:
            raise QuantitativeAnalysisError("comparison group variable must be categorical")
        if method == PROPORTION_METHOD and outcome.variable_type not in {VariableType.CATEGORICAL, VariableType.ORDINAL_SCALE, VariableType.DEMOGRAPHIC}:
            raise QuantitativeAnalysisError("proportion outcome must be categorical")
        if method == MEAN_METHOD and outcome.variable_type is not VariableType.NUMERIC:
            raise QuantitativeAnalysisError("mean outcome must be numeric")
        if view.weighting_mode is not WeightingMode.UNWEIGHTED or result_a.weighting_status != "UNWEIGHTED" or result_b.weighting_status != "UNWEIGHTED" or result_a.weight_set_id is not None or result_b.weight_set_id is not None:
            raise QuantitativeAnalysisError("QG comparisons are strictly unweighted")
        for result in (result_a, result_b):
            if result.dataset_version_id != dataset.version_id or result.dataset_fingerprint != dataset.dataset_fingerprint or result.data_fingerprint != dataset.data_fingerprint or result.codebook_fingerprint != dataset.codebook_fingerprint:
                raise QuantitativeAnalysisError("stale or incompatible StatisticalResult")
        if result_a.result_id == result_b.result_id or result_a.reproducibility_fingerprint == result_b.reproducibility_fingerprint or result_a.analytical_view_fingerprint != view.fingerprint:
            raise QuantitativeAnalysisError("comparison groups must be distinct and view-compatible")

    def _numeric_groups(self, dataset, codebook, specification):
        rows = self._storage.get_parsed_rows(dataset.version_id); outcome = codebook.variable_by_id(specification.variable_id); group = codebook.variable_by_id(specification.group_variable_id)
        oi = next(i for i, item in enumerate(codebook.variables) if item.variable_id == outcome.variable_id); gi = next(i for i, item in enumerate(codebook.variables) if item.variable_id == group.variable_id)
        groups = {canonical_scalar(specification.group_a_category)["value"]: [], canonical_scalar(specification.group_b_category)["value"]: []}
        for row in rows:
            if _is_missing(row[gi], group.missing_rules) or _is_missing(row[oi], outcome.missing_rules): continue
            key = canonical_scalar(row[gi])["value"]
            if key in groups: groups[key].append(self._decimal(row[oi]))
        return groups[canonical_scalar(specification.group_a_category)["value"]], groups[canonical_scalar(specification.group_b_category)["value"]]

    @staticmethod
    def _decimal(value):
        try: result = Decimal(str(value))
        except (InvalidOperation, ValueError): raise QuantitativeAnalysisError("non-finite comparison input") from None
        if not result.is_finite(): raise QuantitativeAnalysisError("non-finite comparison input")
        return result
    @staticmethod
    def _integer_base(value):
        if isinstance(value, bool) or value is None or int(value) != value or int(value) <= 0: raise QuantitativeAnalysisError("invalid comparison base")
        return int(value)
    @staticmethod
    def _minimum_bases(spec, a, b):
        if a < spec.minimum_group_base or b < spec.minimum_group_base: raise QuantitativeAnalysisError("comparison group is below minimum base")
    @staticmethod
    def _mean(values): return sum(values, Decimal(0)) / Decimal(len(values))
    @staticmethod
    def _variance(values, mean): return sum(((item - mean) ** 2 for item in values), Decimal(0)) / Decimal(len(values) - 1)

    def _result(self, dataset, specification, a, b, difference, statistic, p_value, n_a, n_b, method):
        spec_payload = {"comparison_id": specification.comparison_id, "method": method, "variable_id": specification.variable_id, "group_variable_id": specification.group_variable_id, "group_a": canonical_scalar(specification.group_a_category), "group_b": canonical_scalar(specification.group_b_category), "outcome_category": canonical_scalar(specification.outcome_category), "alpha": canonical_scalar(specification.alpha), "sidedness": specification.sidedness, "minimum_group_base": specification.minimum_group_base, "filter": specification.filter_definition, "base": specification.base_definition, "method_version": specification.method_version}
        spec_fp = canonical_digest(spec_payload, digest_provider=self._digest); resolved = replace(specification, fingerprint=spec_fp)
        outputs = {"difference": canonical_scalar(difference), "statistic": canonical_scalar(Decimal(str(statistic))), "p_value": canonical_scalar(Decimal(str(p_value)))}
        fingerprint = canonical_digest({"dataset": dataset.dataset_fingerprint, "data": dataset.data_fingerprint, "specification": spec_fp, "result_a": (a.result_id, a.reproducibility_fingerprint), "result_b": (b.result_id, b.reproducibility_fingerprint), "bases": (n_a, n_b), "outputs": outputs}, digest_provider=self._digest)
        return AnalyticalComparisonResult(str(uuid5(NAMESPACE_URL, f"qg-comparison:{fingerprint}")), dataset.version_id, dataset.dataset_fingerprint, dataset.data_fingerprint, resolved.comparison_id, spec_fp, a.result_id, a.reproducibility_fingerprint, b.result_id, b.reproducibility_fingerprint, Decimal(str(difference)), Decimal(str(statistic)), Decimal(str(p_value)), resolved.alpha, Decimal(str(p_value)) < resolved.alpha, resolved.sidedness, resolved.minimum_group_base, n_a, n_b, method, COMPUTATION_VERSION, fingerprint)

    @staticmethod
    def _two_sided_student_t_p(t, df):
        x = df / (df + t * t)
        return ComparisonStatisticsService._regularized_beta(x, df / 2.0, 0.5)
    @staticmethod
    def _regularized_beta(x, a, b):
        if x <= 0: return 0.0
        if x >= 1: return 1.0
        front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
        if x < (a + 1) / (a + b + 2): return front * ComparisonStatisticsService._beta_fraction(x, a, b) / a
        return 1 - front * ComparisonStatisticsService._beta_fraction(1 - x, b, a) / b
    @staticmethod
    def _beta_fraction(x, a, b):
        qab, qap, qam = a + b, a + 1, a - 1; c = 1.0; d = 1.0 - qab * x / qap; d = 1e-300 if abs(d) < 1e-300 else d; d = 1 / d; h = d
        for m in range(1, 201):
            m2 = 2 * m; aa = m * (b - m) * x / ((qam + m2) * (a + m2)); d = 1 + aa * d; d = 1e-300 if abs(d) < 1e-300 else d; c = 1 + aa / c; c = 1e-300 if abs(c) < 1e-300 else c; d = 1 / d; h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2)); d = 1 + aa * d; d = 1e-300 if abs(d) < 1e-300 else d; c = 1 + aa / c; c = 1e-300 if abs(c) < 1e-300 else c; d = 1 / d; delta = d * c; h *= delta
            if abs(delta - 1) < 3e-14: break
        return h
