from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation, localcontext
from statistics import median
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.ports.quantitative_dataset_ports import DatasetStorage
from application.quantitative.cross_tab_statistics import CrossTabStatisticsService
from application.quantitative.fingerprints import (
    canonical_digest,
    canonical_scalar,
    fingerprint_analysis_specification,
    fingerprint_statistical_result_payload,
)
from application.quantitative.one_way_statistics import QuantitativeAnalysisError, _is_missing
from domain.quantitative.analysis import NumericAnalysisSpecification, StatisticalResult
from domain.quantitative.dataset import (
    CodebookVersion,
    DatasetVersion,
    PiiClassification,
    VariableDefinition,
    VariableRole,
    VariableType,
)
from domain.quantitative.weighting import (
    AnalyticalDatasetView,
    WeightSet,
    WeightValidationStatus,
    WeightingMode,
)


COMPUTATION_METHOD = "deterministic_numeric_summary"
COMPUTATION_VERSION = "qe-1"


class NumericStatisticsService:
    def __init__(self, *, storage: DatasetStorage, digest_provider: DeterministicDigestProvider) -> None:
        self._storage = storage
        self._digest = digest_provider

    def eligible_respondent_refs(self, *, dataset: DatasetVersion, codebook: CodebookVersion, specification: NumericAnalysisSpecification) -> tuple[str, ...]:
        rows = self._storage.get_parsed_rows(dataset.version_id)
        refs = self._storage.get_respondent_lineage(dataset.version_id)
        if len(rows) != len(refs):
            raise QuantitativeAnalysisError("respondent lineage does not match dataset rows")
        filter_variable = self._validate_filter(codebook, specification, rows)
        if filter_variable is None:
            return tuple(refs)
        index = self._index(codebook, filter_variable.variable_id)
        target = self._key(specification.filter_category_value)
        return tuple(ref for row, ref in zip(rows, refs) if not _is_missing(row[index], filter_variable.missing_rules) and self._key(row[index]) == target)

    def compute(self, *, dataset: DatasetVersion, codebook: CodebookVersion, specification: NumericAnalysisSpecification, view: AnalyticalDatasetView, weight_set: WeightSet | None = None) -> tuple[StatisticalResult, ...]:
        if not codebook.approved or codebook.fingerprint != dataset.codebook_fingerprint:
            raise QuantitativeAnalysisError("approved codebook must match dataset")
        variable = codebook.variable_by_id(specification.variable_id)
        self._validate_numeric_variable(variable)
        spec_fp = fingerprint_analysis_specification(specification, digest_provider=self._digest)
        spec = replace(specification, fingerprint=spec_fp)
        if view.dataset_version_id != dataset.version_id or view.dataset_fingerprint != dataset.dataset_fingerprint or view.analysis_specification_fingerprint != spec_fp:
            raise QuantitativeAnalysisError("analytical view is stale or belongs to another specification")

        weighted = specification.weighting_status == "WEIGHTED"
        if weighted:
            if (
                view.weighting_mode is not WeightingMode.WEIGHTED
                or weight_set is None
                or weight_set.validation_status is WeightValidationStatus.BLOCKED
                or weight_set.dataset_version_id != dataset.version_id
                or weight_set.dataset_fingerprint != dataset.dataset_fingerprint
                or view.weight_set_id != weight_set.weight_set_id
                or view.weight_set_fingerprint != weight_set.reproducibility_fingerprint
            ):
                raise QuantitativeAnalysisError("weighted numeric summary requires a current valid WeightSet view")
        elif specification.weighting_status == "UNWEIGHTED":
            if view.weighting_mode is not WeightingMode.UNWEIGHTED or weight_set is not None or view.weight_set_id is not None:
                raise QuantitativeAnalysisError("unweighted numeric summary cannot carry a WeightSet")
        else:
            raise QuantitativeAnalysisError("unsupported weighting status")

        rows = self._storage.get_parsed_rows(dataset.version_id)
        refs = self._storage.get_respondent_lineage(dataset.version_id)
        eligible_refs = self.eligible_respondent_refs(dataset=dataset, codebook=codebook, specification=specification)
        expected_eligible_fp = canonical_digest(tuple(sorted(eligible_refs)), digest_provider=self._digest)
        if view.eligible_respondent_set_fingerprint != expected_eligible_fp:
            raise QuantitativeAnalysisError("analytical view respondent set does not match filter")
        weights = dict(weight_set.weight_vector) if weight_set else {}
        if weighted and set(refs) != set(weights):
            raise QuantitativeAnalysisError("WeightSet does not cover retained respondents")

        eligible = set(eligible_refs)
        index = self._index(codebook, variable.variable_id)
        valid: list[tuple[Decimal, Decimal]] = []
        missing_n = 0
        for row, ref in zip(rows, refs):
            if ref not in eligible:
                continue
            raw = row[index]
            if _is_missing(raw, variable.missing_rules):
                missing_n += 1
                continue
            valid.append((self._decimal(raw), weights[ref] if weighted else Decimal(1)))

        valid_n = len(valid)
        weighted_base = sum((weight for _, weight in valid), Decimal(0)) if weighted else None
        if weighted and valid and weighted_base <= 0:
            raise QuantitativeAnalysisError("weighted valid base must be positive")
        results = [
            self._result(dataset, variable, spec, view, weight_set, "NUMERIC_VALID_N", valid_n, None, valid_n, weighted_base),
            self._result(dataset, variable, spec, view, weight_set, "NUMERIC_MISSING_N", missing_n, None, valid_n, weighted_base),
        ]
        if not valid:
            return tuple(results)
        values = [value for value, _ in valid]
        if weighted:
            results.append(self._result(dataset, variable, spec, view, weight_set, "NUMERIC_WEIGHTED_BASE", weighted_base, None, valid_n, weighted_base))
            with localcontext() as context:
                context.prec = 28
                mean = sum((value * weight for value, weight in valid), Decimal(0)) / weighted_base
            results.append(self._result(dataset, variable, spec, view, weight_set, "NUMERIC_WEIGHTED_MEAN", mean, weighted_base, valid_n, weighted_base))
        else:
            with localcontext() as context:
                context.prec = 28
                mean = sum(values, Decimal(0)) / Decimal(valid_n)
            results.extend(
                (
                    self._result(dataset, variable, spec, view, None, "NUMERIC_MEAN", mean, valid_n, valid_n, None),
                    self._result(dataset, variable, spec, view, None, "NUMERIC_MEDIAN", median(values), valid_n, valid_n, None),
                    self._result(dataset, variable, spec, view, None, "NUMERIC_MINIMUM", min(values), valid_n, valid_n, None),
                    self._result(dataset, variable, spec, view, None, "NUMERIC_MAXIMUM", max(values), valid_n, valid_n, None),
                )
            )
        return tuple(results)

    def _validate_filter(self, codebook, specification, rows):
        if specification.filter_variable_id is None:
            if specification.filter_category_value is not None or specification.filter_definition != "ALL_ROWS":
                raise QuantitativeAnalysisError("invalid categorical filter")
            return None
        variable = codebook.variable_by_id(specification.filter_variable_id)
        if not variable.analytically_eligible or variable.variable_type not in {VariableType.CATEGORICAL, VariableType.ORDINAL_SCALE, VariableType.DEMOGRAPHIC} or variable.role in {VariableRole.TECHNICAL_ID, VariableRole.PII, VariableRole.WEIGHT} or variable.pii_classification is not PiiClassification.NONE:
            raise QuantitativeAnalysisError("filter variable is not an eligible categorical variable")
        if specification.filter_category_value is None:
            raise QuantitativeAnalysisError("categorical filter requires a category")
        expected = CrossTabStatisticsService.filter_definition(variable.variable_id, specification.filter_category_value)
        if specification.filter_definition != expected:
            raise QuantitativeAnalysisError("filter definition does not match categorical filter")
        index = self._index(codebook, variable.variable_id)
        observed = {self._key(row[index]) for row in rows if not _is_missing(row[index], variable.missing_rules)}
        if self._key(specification.filter_category_value) not in observed:
            raise QuantitativeAnalysisError("unknown filter category")
        return variable

    @staticmethod
    def _validate_numeric_variable(variable: VariableDefinition) -> None:
        if not variable.analytically_eligible or variable.variable_type is not VariableType.NUMERIC or variable.role in {VariableRole.TECHNICAL_ID, VariableRole.PII, VariableRole.WEIGHT} or variable.pii_classification is not PiiClassification.NONE or variable.multiple_response_set is not None:
            raise QuantitativeAnalysisError("variable is not an eligible numeric analytical variable")

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        if isinstance(value, bool):
            raise QuantitativeAnalysisError("invalid numeric value")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise QuantitativeAnalysisError("invalid numeric value") from None
        if not result.is_finite():
            raise QuantitativeAnalysisError("invalid numeric value")
        return result

    @staticmethod
    def _index(codebook: CodebookVersion, variable_id: str) -> int:
        return next(index for index, item in enumerate(codebook.variables) if item.variable_id == variable_id)

    @staticmethod
    def _key(value: Any) -> tuple[str, str]:
        scalar = canonical_scalar(value)
        return scalar["type"], scalar["value"]

    def _result(self, dataset, variable, spec, view, weight_set, statistic_type, value, denominator, unweighted_n, weighted_base):
        missing = tuple({"kind": rule.kind, "value": canonical_scalar(rule.value), "low": canonical_scalar(rule.low), "high": canonical_scalar(rule.high), "source": rule.source} for rule in variable.missing_rules)
        payload = {
            "dataset_version_id": dataset.version_id, "dataset_fingerprint": dataset.dataset_fingerprint,
            "data_fingerprint": dataset.data_fingerprint, "codebook_fingerprint": dataset.codebook_fingerprint,
            "variable_id": variable.variable_id, "variable_fingerprint": variable.fingerprint,
            "analysis_specification_id": spec.specification_id, "analysis_specification_fingerprint": spec.fingerprint,
            "filter_definition": spec.filter_definition, "base_definition": spec.base_definition,
            "missing_value_semantics": missing, "weighting_status": spec.weighting_status,
            "weight_set_fingerprint": weight_set.reproducibility_fingerprint if weight_set else None,
            "analytical_view_fingerprint": view.fingerprint, "statistic_type": statistic_type,
            "value": canonical_scalar(value), "denominator": canonical_scalar(denominator),
            "unweighted_n": unweighted_n, "weighted_base": canonical_scalar(weighted_base),
            "computation_method": COMPUTATION_METHOD, "computation_version": COMPUTATION_VERSION,
        }
        fingerprint = fingerprint_statistical_result_payload(payload, digest_provider=self._digest)
        return StatisticalResult(
            result_id=str(uuid5(NAMESPACE_URL, f"qe-statistical-result:{fingerprint}")), dataset_version_id=dataset.version_id,
            dataset_fingerprint=dataset.dataset_fingerprint, data_fingerprint=dataset.data_fingerprint,
            codebook_fingerprint=dataset.codebook_fingerprint, variable_id=variable.variable_id,
            variable_fingerprint=variable.fingerprint, analysis_specification_id=spec.specification_id,
            analysis_specification_fingerprint=spec.fingerprint, weighting_status=spec.weighting_status,
            filter_definition=spec.filter_definition, base_definition=spec.base_definition,
            missing_value_semantics=missing, statistic_type=statistic_type, value=value, denominator=denominator,
            category_value=None, computation_method=COMPUTATION_METHOD, computation_version=COMPUTATION_VERSION,
            presentation_eligible=True, reproducibility_fingerprint=fingerprint,
            weight_set_id=weight_set.weight_set_id if weight_set else None,
            weight_set_fingerprint=weight_set.reproducibility_fingerprint if weight_set else None,
            analytical_view_id=view.view_id, analytical_view_fingerprint=view.fingerprint,
            unweighted_n=unweighted_n, weighted_base=weighted_base,
        )
