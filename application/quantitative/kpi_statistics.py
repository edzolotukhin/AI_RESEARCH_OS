from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation, localcontext
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
from application.quantitative.numeric_statistics import NumericStatisticsService
from application.quantitative.one_way_statistics import QuantitativeAnalysisError, _is_missing
from domain.quantitative.analysis import (
    CustomIndexAnalysisSpecification,
    NpsAnalysisSpecification,
    StatisticalResult,
)
from domain.quantitative.dataset import (
    CodebookVersion,
    DatasetVersion,
    PiiClassification,
    VariableDefinition,
    VariableRole,
    VariableType,
)
from domain.quantitative.weighting import AnalyticalDatasetView, WeightSet, WeightValidationStatus, WeightingMode


COMPUTATION_VERSION = "qf-1"


class KpiStatisticsService:
    def __init__(self, *, storage: DatasetStorage, digest_provider: DeterministicDigestProvider) -> None:
        self._storage = storage
        self._digest = digest_provider
        self._filters = NumericStatisticsService(storage=storage, digest_provider=digest_provider)

    def eligible_respondent_refs(self, *, dataset, codebook, specification):
        return self._filters.eligible_respondent_refs(dataset=dataset, codebook=codebook, specification=specification)

    def compute_nps(self, *, dataset: DatasetVersion, codebook: CodebookVersion, specification: NpsAnalysisSpecification, view: AnalyticalDatasetView, weight_set: WeightSet | None = None) -> tuple[StatisticalResult, ...]:
        self._validate_nps_specification(specification)
        variable = codebook.variable_by_id(specification.variable_id)
        self._validate_numeric_variable(variable)
        spec, rows, refs, eligible, weights, weighted = self._context(dataset, codebook, specification, view, weight_set)
        index = self._index(codebook, variable.variable_id)
        groups = {"DETRACTOR": [], "PASSIVE": [], "PROMOTER": []}
        missing_n = 0
        for row, ref in zip(rows, refs):
            if ref not in eligible:
                continue
            raw = row[index]
            if _is_missing(raw, variable.missing_rules):
                missing_n += 1
                continue
            value = self._decimal(raw)
            if value != value.to_integral_value() or value < specification.scale_minimum or value > specification.scale_maximum:
                raise QuantitativeAnalysisError("NPS source value is outside the declared integer scale")
            integer = int(value)
            group = self._nps_group(integer, specification)
            groups[group].append(weights[ref] if weighted else Decimal(1))
        valid_n = sum(len(items) for items in groups.values())
        total_base = sum((sum(items, Decimal(0)) for items in groups.values()), Decimal(0))
        if valid_n == 0 or total_base <= 0:
            raise QuantitativeAnalysisError("NPS requires a positive valid analytical base")
        results = [self._result(dataset, (variable,), spec, view, weight_set, "NPS_VALID_N", valid_n, None, valid_n, total_base if weighted else None, "deterministic_nps")]
        shares: dict[str, Decimal] = {}
        for group in ("DETRACTOR", "PASSIVE", "PROMOTER"):
            group_n = len(groups[group])
            group_base = sum(groups[group], Decimal(0))
            with localcontext() as context:
                context.prec = 28
                share = group_base * Decimal(100) / total_base
            shares[group] = share
            results.extend((
                self._result(dataset, (variable,), spec, view, weight_set, f"NPS_{group}_BASE", group_base if weighted else group_n, total_base if weighted else valid_n, group_n, group_base if weighted else None, "deterministic_nps"),
                self._result(dataset, (variable,), spec, view, weight_set, f"NPS_{group}_SHARE", share, total_base if weighted else valid_n, group_n, group_base if weighted else None, "deterministic_nps"),
            ))
        results.append(self._result(dataset, (variable,), spec, view, weight_set, "NPS", shares["PROMOTER"] - shares["DETRACTOR"], total_base if weighted else valid_n, valid_n, total_base if weighted else None, "deterministic_nps"))
        results.append(self._result(dataset, (variable,), spec, view, weight_set, "NPS_MISSING_N", missing_n, None, valid_n, total_base if weighted else None, "deterministic_nps"))
        return tuple(results)

    def compute_custom_index(self, *, dataset: DatasetVersion, codebook: CodebookVersion, specification: CustomIndexAnalysisSpecification, view: AnalyticalDatasetView, weight_set: WeightSet | None = None) -> tuple[StatisticalResult, ...]:
        self._validate_index_specification(specification)
        variables = tuple(codebook.variable_by_id(term.variable_id) for term in specification.terms)
        for variable in variables:
            self._validate_numeric_variable(variable)
        spec, rows, refs, eligible, weights, weighted = self._context(dataset, codebook, specification, view, weight_set)
        indexes = tuple(self._index(codebook, variable.variable_id) for variable in variables)
        complete: list[tuple[Decimal, Decimal]] = []
        missing_n = 0
        for row, ref in zip(rows, refs):
            if ref not in eligible:
                continue
            raw_values = tuple(row[index] for index in indexes)
            if any(_is_missing(value, variable.missing_rules) for value, variable in zip(raw_values, variables)):
                missing_n += 1
                continue
            values = tuple(self._decimal(item) for item in raw_values)
            score = specification.intercept + sum((term.coefficient * value for term, value in zip(specification.terms, values)), Decimal(0))
            if not score.is_finite():
                raise QuantitativeAnalysisError("custom index produced a non-finite score")
            complete.append((score, weights[ref] if weighted else Decimal(1)))
        valid_n = len(complete)
        base = sum((weight for _, weight in complete), Decimal(0))
        if valid_n == 0 or base <= 0:
            raise QuantitativeAnalysisError("custom index requires a positive valid analytical base")
        with localcontext() as context:
            context.prec = 28
            value = sum((score * weight for score, weight in complete), Decimal(0)) / base
        return (
            self._result(dataset, variables, spec, view, weight_set, "CUSTOM_INDEX_VALID_N", valid_n, None, valid_n, base if weighted else None, "deterministic_custom_index"),
            self._result(dataset, variables, spec, view, weight_set, "CUSTOM_INDEX_MISSING_N", missing_n, None, valid_n, base if weighted else None, "deterministic_custom_index"),
            self._result(dataset, variables, spec, view, weight_set, "CUSTOM_INDEX_WEIGHTED_BASE" if weighted else "CUSTOM_INDEX_VALID_BASE", base if weighted else valid_n, None, valid_n, base if weighted else None, "deterministic_custom_index"),
            self._result(dataset, variables, spec, view, weight_set, "CUSTOM_INDEX", value, base if weighted else valid_n, valid_n, base if weighted else None, "deterministic_custom_index"),
        )

    def _context(self, dataset, codebook, specification, view, weight_set):
        if not codebook.approved or codebook.fingerprint != dataset.codebook_fingerprint:
            raise QuantitativeAnalysisError("approved codebook must match dataset")
        spec_fp = fingerprint_analysis_specification(specification, digest_provider=self._digest)
        spec = replace(specification, fingerprint=spec_fp)
        if view.dataset_version_id != dataset.version_id or view.dataset_fingerprint != dataset.dataset_fingerprint or view.analysis_specification_fingerprint != spec_fp:
            raise QuantitativeAnalysisError("analytical view is stale or belongs to another KPI specification")
        weighted = specification.weighting_status == "WEIGHTED"
        if weighted:
            if view.weighting_mode is not WeightingMode.WEIGHTED or weight_set is None or weight_set.validation_status is WeightValidationStatus.BLOCKED or weight_set.dataset_version_id != dataset.version_id or weight_set.dataset_fingerprint != dataset.dataset_fingerprint or view.weight_set_id != weight_set.weight_set_id or view.weight_set_fingerprint != weight_set.reproducibility_fingerprint:
                raise QuantitativeAnalysisError("weighted KPI requires a current valid WeightSet view")
        elif specification.weighting_status == "UNWEIGHTED":
            if view.weighting_mode is not WeightingMode.UNWEIGHTED or weight_set is not None or view.weight_set_id is not None:
                raise QuantitativeAnalysisError("unweighted KPI cannot carry a WeightSet")
        else:
            raise QuantitativeAnalysisError("unsupported weighting status")
        rows = self._storage.get_parsed_rows(dataset.version_id)
        refs = self._storage.get_respondent_lineage(dataset.version_id)
        eligible_refs = self.eligible_respondent_refs(dataset=dataset, codebook=codebook, specification=specification)
        if view.eligible_respondent_set_fingerprint != canonical_digest(tuple(sorted(eligible_refs)), digest_provider=self._digest):
            raise QuantitativeAnalysisError("analytical view respondent set does not match filter")
        weights = dict(weight_set.weight_vector) if weight_set else {}
        if weighted and set(refs) != set(weights):
            raise QuantitativeAnalysisError("WeightSet does not cover retained respondents")
        return spec, rows, refs, set(eligible_refs), weights, weighted

    @staticmethod
    def _validate_nps_specification(specification):
        if specification.method_version != "STANDARD_NPS_V1" or specification.scale_minimum >= specification.scale_maximum:
            raise QuantitativeAnalysisError("invalid NPS specification")
        d, p, r = specification.detractor_range, specification.passive_range, specification.promoter_range
        if d[0] != specification.scale_minimum or d[1] + 1 != p[0] or p[1] + 1 != r[0] or r[1] != specification.scale_maximum or any(low > high for low, high in (d, p, r)):
            raise QuantitativeAnalysisError("NPS ranges must be complete, ordered, and non-overlapping")

    @staticmethod
    def _nps_group(value, specification):
        if specification.detractor_range[0] <= value <= specification.detractor_range[1]: return "DETRACTOR"
        if specification.passive_range[0] <= value <= specification.passive_range[1]: return "PASSIVE"
        if specification.promoter_range[0] <= value <= specification.promoter_range[1]: return "PROMOTER"
        raise QuantitativeAnalysisError("NPS value is not classified")

    @staticmethod
    def _validate_index_specification(specification):
        if specification.formula_method != "MEAN_OF_ROW_LINEAR_COMBINATION" or specification.formula_version != "LINEAR_INDEX_V1" or not specification.terms:
            raise QuantitativeAnalysisError("invalid custom index specification")
        ids = [item.variable_id for item in specification.terms]
        if len(ids) != len(set(ids)) or any(not item.coefficient.is_finite() or item.coefficient == 0 for item in specification.terms) or not specification.intercept.is_finite():
            raise QuantitativeAnalysisError("invalid custom index terms")

    @staticmethod
    def _validate_numeric_variable(variable: VariableDefinition):
        if not variable.analytically_eligible or variable.variable_type is not VariableType.NUMERIC or variable.role in {VariableRole.TECHNICAL_ID, VariableRole.PII, VariableRole.WEIGHT} or variable.pii_classification is not PiiClassification.NONE or variable.multiple_response_set is not None:
            raise QuantitativeAnalysisError("KPI source is not an eligible numeric variable")

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        if isinstance(value, bool): raise QuantitativeAnalysisError("non-finite or invalid numeric KPI input")
        try: result = Decimal(str(value))
        except (InvalidOperation, ValueError): raise QuantitativeAnalysisError("non-finite or invalid numeric KPI input") from None
        if not result.is_finite(): raise QuantitativeAnalysisError("non-finite or invalid numeric KPI input")
        return result

    @staticmethod
    def _index(codebook, variable_id):
        return next(index for index, item in enumerate(codebook.variables) if item.variable_id == variable_id)

    def _result(self, dataset, variables, spec, view, weight_set, statistic_type, value, denominator, unweighted_n, weighted_base, method):
        missing = tuple({"variable_id": variable.variable_id, "variable_fingerprint": variable.fingerprint, "rules": tuple({"kind": rule.kind, "value": canonical_scalar(rule.value), "low": canonical_scalar(rule.low), "high": canonical_scalar(rule.high), "source": rule.source} for rule in variable.missing_rules)} for variable in variables)
        payload = {"dataset_version_id": dataset.version_id, "dataset_fingerprint": dataset.dataset_fingerprint, "data_fingerprint": dataset.data_fingerprint, "codebook_fingerprint": dataset.codebook_fingerprint, "source_variables": tuple((item.variable_id, item.fingerprint) for item in variables), "analysis_specification_id": spec.specification_id, "analysis_specification_fingerprint": spec.fingerprint, "filter_definition": spec.filter_definition, "base_definition": spec.base_definition, "missing_value_semantics": missing, "weighting_status": spec.weighting_status, "weight_set_fingerprint": weight_set.reproducibility_fingerprint if weight_set else None, "analytical_view_fingerprint": view.fingerprint, "statistic_type": statistic_type, "value": canonical_scalar(value), "denominator": canonical_scalar(denominator), "unweighted_n": unweighted_n, "weighted_base": canonical_scalar(weighted_base), "computation_method": method, "computation_version": COMPUTATION_VERSION}
        fingerprint = fingerprint_statistical_result_payload(payload, digest_provider=self._digest)
        primary = variables[0]
        return StatisticalResult(result_id=str(uuid5(NAMESPACE_URL, f"qf-statistical-result:{fingerprint}")), dataset_version_id=dataset.version_id, dataset_fingerprint=dataset.dataset_fingerprint, data_fingerprint=dataset.data_fingerprint, codebook_fingerprint=dataset.codebook_fingerprint, variable_id=primary.variable_id, variable_fingerprint=primary.fingerprint, analysis_specification_id=spec.specification_id, analysis_specification_fingerprint=spec.fingerprint, weighting_status=spec.weighting_status, filter_definition=spec.filter_definition, base_definition=spec.base_definition, missing_value_semantics=missing, statistic_type=statistic_type, value=value, denominator=denominator, category_value=None, computation_method=method, computation_version=COMPUTATION_VERSION, presentation_eligible=True, reproducibility_fingerprint=fingerprint, weight_set_id=weight_set.weight_set_id if weight_set else None, weight_set_fingerprint=weight_set.reproducibility_fingerprint if weight_set else None, analytical_view_id=view.view_id, analytical_view_fingerprint=view.fingerprint, unweighted_n=unweighted_n, weighted_base=weighted_base)
