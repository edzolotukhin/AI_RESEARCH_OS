from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext
from statistics import median
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from application.ports.quantitative_dataset_ports import DatasetStorage
from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.quantitative.fingerprints import (
    canonical_scalar,
    fingerprint_analysis_specification,
    fingerprint_statistical_result_payload,
)
from domain.quantitative.analysis import AnalysisSpecification, StatisticalResult
from domain.quantitative.dataset import CodebookVersion, DatasetVersion, MissingValueRule, VariableDefinition, VariableType


class QuantitativeAnalysisError(ValueError):
    pass


COMPUTATION_METHOD = "deterministic_unweighted_one_way"
COMPUTATION_VERSION = "qa-1"


class OneWayStatisticsService:
    def __init__(
        self,
        *,
        storage: DatasetStorage,
        digest_provider: DeterministicDigestProvider,
    ) -> None:
        self._storage = storage
        self._digest_provider = digest_provider

    def compute(
        self,
        *,
        dataset: DatasetVersion,
        codebook: CodebookVersion,
        specification: AnalysisSpecification,
    ) -> tuple[StatisticalResult, ...]:
        variable = codebook.variable_by_id(specification.variable_id)
        if not codebook.approved:
            raise QuantitativeAnalysisError("codebook is not approved")
        if codebook.fingerprint != dataset.codebook_fingerprint:
            raise QuantitativeAnalysisError("codebook fingerprint does not match dataset")
        if not variable.analytically_eligible:
            raise QuantitativeAnalysisError("variable is not analytically eligible")
        if specification.weighting_status != "UNWEIGHTED":
            raise QuantitativeAnalysisError("first slice supports UNWEIGHTED only")

        rows = self._storage.get_parsed_rows(dataset.version_id)
        variable_index = next(
            index for index, item in enumerate(codebook.variables) if item.variable_id == variable.variable_id
        )
        values = [row[variable_index] for row in rows]
        missing = [value for value in values if _is_missing(value, variable.missing_rules)]
        valid = [value for value in values if not _is_missing(value, variable.missing_rules)]
        spec_fingerprint = fingerprint_analysis_specification(
            specification,
            digest_provider=self._digest_provider,
        )
        resolved_spec = replace(specification, fingerprint=spec_fingerprint)

        if variable.variable_type in {
            VariableType.CATEGORICAL,
            VariableType.ORDINAL_SCALE,
            VariableType.DEMOGRAPHIC,
            VariableType.TECHNICAL_ID,
        }:
            return self._categorical_results(
                dataset,
                variable,
                resolved_spec,
                valid,
                len(missing),
                len(values),
                digest_provider=self._digest_provider,
            )
        if variable.variable_type is VariableType.NUMERIC:
            return self._numeric_results(
                dataset,
                variable,
                resolved_spec,
                valid,
                len(missing),
                len(values),
                digest_provider=self._digest_provider,
            )
        raise QuantitativeAnalysisError("unsupported variable type")

    def _categorical_results(
        self,
        dataset: DatasetVersion,
        variable: VariableDefinition,
        specification: AnalysisSpecification,
        valid: list[Any],
        missing_count: int,
        total: int,
        digest_provider: DeterministicDigestProvider,
    ) -> tuple[StatisticalResult, ...]:
        results = [
            self._result(dataset, variable, specification, "TOTAL_BASE", total, None, None, True, digest_provider),
            self._result(dataset, variable, specification, "VALID_BASE", len(valid), None, None, True, digest_provider),
            self._result(dataset, variable, specification, "MISSING_COUNT", missing_count, total, None, True, digest_provider),
        ]
        counts: dict[tuple[str, str], tuple[Any, int]] = {}
        for value in valid:
            key_payload = canonical_scalar(value)
            key = (key_payload["type"], key_payload["value"])
            original, count = counts.get(key, (value, 0))
            counts[key] = (original, count + 1)
        for key in sorted(counts):
            value, count = counts[key]
            results.append(
                self._result(dataset, variable, specification, "CATEGORY_COUNT", count, len(valid), value, True, digest_provider)
            )
            with localcontext() as context:
                context.prec = 28
                percentage = (
                    Decimal(count) * Decimal(100) / Decimal(len(valid))
                    if valid
                    else Decimal(0)
                )
            eligible = percentage > specification.presentation_threshold_percent
            results.append(
                self._result(
                    dataset,
                    variable,
                    specification,
                    "VALID_PERCENTAGE",
                    percentage,
                    len(valid),
                    value,
                    eligible,
                    digest_provider,
                )
            )
        return tuple(results)

    def _numeric_results(
        self,
        dataset: DatasetVersion,
        variable: VariableDefinition,
        specification: AnalysisSpecification,
        valid: list[Any],
        missing_count: int,
        total: int,
        digest_provider: DeterministicDigestProvider,
    ) -> tuple[StatisticalResult, ...]:
        numeric = [Decimal(str(item)) for item in valid]
        results = [
            self._result(dataset, variable, specification, "TOTAL_BASE", total, None, None, True, digest_provider),
            self._result(dataset, variable, specification, "VALID_N", len(numeric), None, None, True, digest_provider),
            self._result(dataset, variable, specification, "MISSING_N", missing_count, total, None, True, digest_provider),
        ]
        if numeric:
            with localcontext() as context:
                context.prec = 28
                mean_value = sum(numeric, Decimal(0)) / Decimal(len(numeric))
            results.extend(
                [
                    self._result(dataset, variable, specification, "MEAN", mean_value, len(numeric), None, True, digest_provider),
                    self._result(dataset, variable, specification, "MEDIAN", median(numeric), len(numeric), None, True, digest_provider),
                ]
            )
        return tuple(results)

    @staticmethod
    def _result(
        dataset: DatasetVersion,
        variable: VariableDefinition,
        specification: AnalysisSpecification,
        statistic_type: str,
        value: int | Decimal,
        denominator: int | Decimal | None,
        category_value: Any | None,
        presentation_eligible: bool,
        digest_provider: DeterministicDigestProvider,
    ) -> StatisticalResult:
        missing_payload = tuple(
            {
                "kind": rule.kind,
                "value": canonical_scalar(rule.value),
                "low": canonical_scalar(rule.low),
                "high": canonical_scalar(rule.high),
                "source": rule.source,
            }
            for rule in variable.missing_rules
        )
        payload = {
            "dataset_version_id": dataset.version_id,
            "dataset_fingerprint": dataset.dataset_fingerprint,
            "data_fingerprint": dataset.data_fingerprint,
            "codebook_fingerprint": dataset.codebook_fingerprint,
            "variable_id": variable.variable_id,
            "variable_fingerprint": variable.fingerprint,
            "analysis_specification_id": specification.specification_id,
            "analysis_specification_fingerprint": specification.fingerprint,
            "weighting_status": "UNWEIGHTED",
            "filter_definition": specification.filter_definition,
            "base_definition": specification.base_definition,
            "missing_value_semantics": missing_payload,
            "statistic_type": statistic_type,
            "value": canonical_scalar(value),
            "denominator": canonical_scalar(denominator),
            "category_value": canonical_scalar(category_value),
            "computation_method": COMPUTATION_METHOD,
            "computation_version": COMPUTATION_VERSION,
            "presentation_eligible": presentation_eligible,
        }
        fingerprint = fingerprint_statistical_result_payload(
            payload,
            digest_provider=digest_provider,
        )
        result_id = str(uuid5(NAMESPACE_URL, f"qa-statistical-result:{fingerprint}"))
        return StatisticalResult(
            result_id=result_id,
            dataset_version_id=dataset.version_id,
            dataset_fingerprint=dataset.dataset_fingerprint,
            data_fingerprint=dataset.data_fingerprint,
            codebook_fingerprint=dataset.codebook_fingerprint,
            variable_id=variable.variable_id,
            variable_fingerprint=variable.fingerprint,
            analysis_specification_id=specification.specification_id,
            analysis_specification_fingerprint=specification.fingerprint,
            weighting_status="UNWEIGHTED",
            filter_definition=specification.filter_definition,
            base_definition=specification.base_definition,
            missing_value_semantics=missing_payload,
            statistic_type=statistic_type,
            value=value,
            denominator=denominator,
            category_value=category_value,
            computation_method=COMPUTATION_METHOD,
            computation_version=COMPUTATION_VERSION,
            presentation_eligible=presentation_eligible,
            reproducibility_fingerprint=fingerprint,
        )


def _is_missing(value: Any, rules: tuple[MissingValueRule, ...]) -> bool:
    if value is None or (isinstance(value, float) and value != value):
        return True
    for rule in rules:
        if rule.kind == "value" and value == rule.value:
            return True
        if rule.kind == "range" and rule.low is not None and rule.high is not None:
            if rule.low <= value <= rule.high:
                return True
    return False
