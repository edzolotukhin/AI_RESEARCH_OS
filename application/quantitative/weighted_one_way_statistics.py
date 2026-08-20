from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.ports.quantitative_dataset_ports import DatasetStorage
from application.quantitative.fingerprints import (
    canonical_digest,
    canonical_scalar,
    fingerprint_analysis_specification,
    fingerprint_statistical_result_payload,
)
from application.quantitative.one_way_statistics import QuantitativeAnalysisError, _is_missing
from domain.quantitative.analysis import AnalysisSpecification, StatisticalResult
from domain.quantitative.dataset import CodebookVersion, DatasetVersion, VariableDefinition, VariableType
from domain.quantitative.weighting import AnalyticalDatasetView, WeightSet, WeightingMode


COMPUTATION_METHOD = "deterministic_weighted_one_way"
COMPUTATION_VERSION = "qc-1"


class WeightedOneWayStatisticsService:
    def __init__(self, *, storage: DatasetStorage, digest_provider: DeterministicDigestProvider) -> None:
        self._storage = storage
        self._digest = digest_provider

    def compute(
        self,
        *,
        dataset: DatasetVersion,
        codebook: CodebookVersion,
        specification: AnalysisSpecification,
        view: AnalyticalDatasetView,
        weight_set: WeightSet,
    ) -> tuple[StatisticalResult, ...]:
        variable = codebook.variable_by_id(specification.variable_id)
        if not codebook.approved or codebook.fingerprint != dataset.codebook_fingerprint:
            raise QuantitativeAnalysisError("approved codebook must match dataset")
        if not variable.analytically_eligible:
            raise QuantitativeAnalysisError("variable is not analytically eligible")
        if specification.weighting_status != "WEIGHTED" or view.weighting_mode is not WeightingMode.WEIGHTED:
            raise QuantitativeAnalysisError("weighted analysis requires a weighted specification and view")
        if (
            view.dataset_version_id != dataset.version_id
            or weight_set.dataset_version_id != dataset.version_id
            or view.dataset_fingerprint != dataset.dataset_fingerprint
            or view.weight_set_fingerprint != weight_set.reproducibility_fingerprint
            or weight_set.dataset_fingerprint != dataset.dataset_fingerprint
        ):
            raise QuantitativeAnalysisError("analytical view or WeightSet is stale")

        refs = self._storage.get_respondent_lineage(dataset.version_id)
        rows = self._storage.get_parsed_rows(dataset.version_id)
        weights = dict(weight_set.weight_vector)
        if len(refs) != len(rows) or set(refs) != set(weights):
            raise QuantitativeAnalysisError("WeightSet does not cover the analytical respondent set")
        if specification.filter_definition != "ALL_ROWS":
            raise QuantitativeAnalysisError("weighted filters are not implemented in this slice")
        expected_eligible = canonical_digest(tuple(sorted(refs)), digest_provider=self._digest)
        if view.eligible_respondent_set_fingerprint != expected_eligible:
            raise QuantitativeAnalysisError("analytical view respondent set does not match execution")
        index = next(i for i, item in enumerate(codebook.variables) if item.variable_id == variable.variable_id)
        observations = tuple((row[index], weights[ref]) for row, ref in zip(rows, refs))
        valid = tuple((value, weight) for value, weight in observations if not _is_missing(value, variable.missing_rules))
        spec = replace(
            specification,
            fingerprint=fingerprint_analysis_specification(specification, digest_provider=self._digest),
        )
        if view.analysis_specification_fingerprint != spec.fingerprint:
            raise QuantitativeAnalysisError("analytical view does not match analysis specification")
        if variable.variable_type in {
            VariableType.CATEGORICAL,
            VariableType.ORDINAL_SCALE,
            VariableType.DEMOGRAPHIC,
            VariableType.TECHNICAL_ID,
        }:
            return self._categorical(dataset, variable, spec, view, weight_set, valid)
        if variable.variable_type is VariableType.NUMERIC:
            return self._numeric(dataset, variable, spec, view, weight_set, valid)
        raise QuantitativeAnalysisError("unsupported variable type")

    def _categorical(self, dataset, variable, spec, view, weight_set, valid):
        valid_base = sum((weight for _, weight in valid), Decimal(0))
        if valid and valid_base <= 0:
            raise QuantitativeAnalysisError("weighted valid base must be positive")
        buckets: dict[tuple[str, str], tuple[Any, int, Decimal]] = {}
        for value, weight in valid:
            scalar = canonical_scalar(value)
            key = scalar["type"], scalar["value"]
            original, count, base = buckets.get(key, (value, 0, Decimal(0)))
            buckets[key] = original, count + 1, base + weight
        results = [
            self._result(dataset, variable, spec, view, weight_set, "UNWEIGHTED_VALID_N", len(valid), None, None, True, len(valid), valid_base),
            self._result(dataset, variable, spec, view, weight_set, "WEIGHTED_VALID_BASE", valid_base, None, None, True, len(valid), valid_base),
        ]
        for key in sorted(buckets):
            value, count, base = buckets[key]
            percentage = Decimal(0)
            if valid_base:
                with localcontext() as context:
                    context.prec = 28
                    percentage = base * Decimal(100) / valid_base
            results.extend((
                self._result(dataset, variable, spec, view, weight_set, "UNWEIGHTED_CATEGORY_N", count, len(valid), value, True, count, base),
                self._result(dataset, variable, spec, view, weight_set, "WEIGHTED_CATEGORY_BASE", base, valid_base, value, True, count, base),
                self._result(dataset, variable, spec, view, weight_set, "WEIGHTED_PERCENTAGE", percentage, valid_base, value, percentage > spec.presentation_threshold_percent, count, base),
            ))
        return tuple(results)

    def _numeric(self, dataset, variable, spec, view, weight_set, valid):
        weighted_base = sum((weight for _, weight in valid), Decimal(0))
        if valid and weighted_base <= 0:
            raise QuantitativeAnalysisError("weighted valid base must be positive")
        results = [
            self._result(dataset, variable, spec, view, weight_set, "UNWEIGHTED_VALID_N", len(valid), None, None, True, len(valid), weighted_base),
            self._result(dataset, variable, spec, view, weight_set, "WEIGHTED_VALID_BASE", weighted_base, None, None, True, len(valid), weighted_base),
        ]
        if valid:
            with localcontext() as context:
                context.prec = 28
                mean = sum((Decimal(str(value)) * weight for value, weight in valid), Decimal(0)) / weighted_base
            results.append(self._result(dataset, variable, spec, view, weight_set, "WEIGHTED_MEAN", mean, weighted_base, None, True, len(valid), weighted_base))
        return tuple(results)

    def _result(self, dataset, variable, spec, view, weight_set, statistic_type, value, denominator, category, eligible, unweighted_n, weighted_base):
        missing_payload = tuple({
            "kind": rule.kind,
            "value": canonical_scalar(rule.value),
            "low": canonical_scalar(rule.low),
            "high": canonical_scalar(rule.high),
            "source": rule.source,
        } for rule in variable.missing_rules)
        payload = {
            "dataset_version_id": dataset.version_id,
            "dataset_fingerprint": dataset.dataset_fingerprint,
            "data_fingerprint": dataset.data_fingerprint,
            "codebook_fingerprint": dataset.codebook_fingerprint,
            "variable_id": variable.variable_id,
            "variable_fingerprint": variable.fingerprint,
            "analysis_specification_fingerprint": spec.fingerprint,
            "weight_set_id": weight_set.weight_set_id,
            "weight_set_fingerprint": weight_set.reproducibility_fingerprint,
            "analytical_view_id": view.view_id,
            "analytical_view_fingerprint": view.fingerprint,
            "unweighted_n": unweighted_n,
            "weighted_base": canonical_scalar(weighted_base),
            "missing_value_semantics": missing_payload,
            "statistic_type": statistic_type,
            "value": canonical_scalar(value),
            "denominator": canonical_scalar(denominator),
            "category_value": canonical_scalar(category),
            "computation_method": COMPUTATION_METHOD,
            "computation_version": COMPUTATION_VERSION,
            "presentation_eligible": eligible,
        }
        fingerprint = fingerprint_statistical_result_payload(payload, digest_provider=self._digest)
        return StatisticalResult(
            result_id=str(uuid5(NAMESPACE_URL, f"qc-statistical-result:{fingerprint}")),
            dataset_version_id=dataset.version_id,
            dataset_fingerprint=dataset.dataset_fingerprint,
            data_fingerprint=dataset.data_fingerprint,
            codebook_fingerprint=dataset.codebook_fingerprint,
            variable_id=variable.variable_id,
            variable_fingerprint=variable.fingerprint,
            analysis_specification_id=spec.specification_id,
            analysis_specification_fingerprint=spec.fingerprint,
            weighting_status="WEIGHTED",
            filter_definition=spec.filter_definition,
            base_definition=spec.base_definition,
            missing_value_semantics=missing_payload,
            statistic_type=statistic_type,
            value=value,
            denominator=denominator,
            category_value=category,
            computation_method=COMPUTATION_METHOD,
            computation_version=COMPUTATION_VERSION,
            presentation_eligible=eligible,
            reproducibility_fingerprint=fingerprint,
            weight_set_id=weight_set.weight_set_id,
            weight_set_fingerprint=weight_set.reproducibility_fingerprint,
            analytical_view_id=view.view_id,
            analytical_view_fingerprint=view.fingerprint,
            unweighted_n=unweighted_n,
            weighted_base=weighted_base,
        )
