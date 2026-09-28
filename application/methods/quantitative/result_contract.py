"""Immutable provenance view over persisted deterministic Quant results.

This does not calculate statistics or create a second result store. Result IDs and
fingerprints remain those of the accepted computation services.
"""

from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from application.quantitative.fingerprints import canonical_digest, canonical_scalar, fingerprint_analysis_specification
from application.quantitative.comparison_statistics import fingerprint_comparison_specification
from domain.quantitative.analysis import AnalyticalComparisonResult, StatisticalResult
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


def _canonical(value: Any):
    if is_dataclass(value):
        return {field.name: _canonical(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (Decimal, int, float, bool)) or value is None:
        return canonical_scalar(value)
    return str(value)


@dataclass(frozen=True)
class CanonicalQuantResult:
    method_id: str
    method_version: str
    execution_version: int
    method_fingerprint: str
    analysis_fingerprint: str
    result_id: str
    result_fingerprint: str
    dataset_id: str
    dataset_version_id: str
    dataset_fingerprint: str
    source_checksum: str
    schema_fingerprint: str
    codebook_fingerprint: str
    procedure: str
    procedure_version: str
    variable_ids: tuple[str, ...]
    filter_definition: str
    weighting_status: str
    weight_set_fingerprint: str | None
    source_n: int
    unweighted_n: int | None
    denominator: dict | None
    weighted_base: dict | None
    outside_base_n: int | None
    missing_value_semantics: tuple
    precursor_result_refs: tuple[tuple[str, str], ...]
    outputs: dict
    p_value: dict | None
    uncertainty_capability: str
    parameters: dict
    provenance_fingerprint: str


def project_result(*, method_pin, analysis_pin, dataset, codebook, specification,
                   result: StatisticalResult | AnalyticalComparisonResult) -> CanonicalQuantResult:
    from application.methods.quantitative.pin import resolve_method_pin, verify_analysis_pin

    state = analysis_pin.get("authority", {}) if isinstance(analysis_pin, dict) else {}
    verify_analysis_pin(analysis_pin, method_pin=method_pin, project_id=dataset.project_id,
                        run_id=dataset.run_id, dataset=dataset, codebook=codebook,
                        state=state)
    if (result.dataset_version_id, result.dataset_fingerprint, result.data_fingerprint) != (
        dataset.version_id, dataset.dataset_fingerprint, dataset.data_fingerprint
    ):
        raise ValueError("Statistical result does not belong to bound dataset")
    method = resolve_method_pin(method_pin, project_id=dataset.project_id, run_id=dataset.run_id)
    if isinstance(result, StatisticalResult):
        if result.codebook_fingerprint != codebook.fingerprint:
            raise ValueError("Statistical result codebook is stale")
        if result.analysis_specification_fingerprint != fingerprint_analysis_specification(
            specification, digest_provider=Sha256DigestProvider()):
            raise ValueError("Statistical result parameters are not the persisted specification")
        result_id, fingerprint = result.result_id, result.reproducibility_fingerprint
        procedure, version = result.statistic_type, result.computation_version
        variables = tuple(item for item in (result.variable_id, result.row_variable_id,
                                               result.column_variable_id) if item)
        denominator = canonical_scalar(result.denominator)
        unweighted_n = result.unweighted_n
        weighted_base = canonical_scalar(result.weighted_base) if result.weighted_base is not None else None
        outside = (dataset.row_count - int(result.denominator)
                   if result.weighting_status == "UNWEIGHTED" and isinstance(result.denominator, int)
                   and 0 <= result.denominator <= dataset.row_count else None)
        outputs = {"value": canonical_scalar(result.value), "statistic_type": result.statistic_type}
        p_value, uncertainty = None, "NOT_PRODUCED"
        weighting, weight_fp = result.weighting_status, result.weight_set_fingerprint
        filter_definition = result.filter_definition
        missing_semantics = tuple(_canonical(item) for item in result.missing_value_semantics)
        precursor_refs = ()
    elif isinstance(result, AnalyticalComparisonResult):
        if result.specification_fingerprint != fingerprint_comparison_specification(
            specification, digest_provider=Sha256DigestProvider()):
            raise ValueError("Comparison parameters are not the persisted specification")
        result_id, fingerprint = result.comparison_result_id, result.reproducibility_fingerprint
        procedure, version = result.method, result.method_version
        variables = (specification.variable_id, specification.group_variable_id)
        denominator, outside = None, None
        unweighted_n, weighted_base = None, None
        outputs = {"observed_difference": canonical_scalar(result.observed_difference),
                   "test_statistic": canonical_scalar(result.test_statistic),
                   "group_a_base": result.group_a_base, "group_b_base": result.group_b_base,
                   "significant": result.significant}
        p_value, uncertainty = canonical_scalar(result.p_value), "P_VALUE_ONLY_NO_CI"
        weighting, weight_fp = "UNWEIGHTED", None
        filter_definition = specification.filter_definition
        missing_semantics = ()
        precursor_refs = ((result.group_a_result_id, result.group_a_result_fingerprint),
                          (result.group_b_result_id, result.group_b_result_fingerprint))
    else:
        raise TypeError("Unsupported canonical Quant result type")
    parameters = _canonical(specification)
    payload = {"contract": "CMF_QUANT_RESULT_V1", "method": method_pin["fingerprint"],
               "analysis": analysis_pin["fingerprint"], "result": (result_id, fingerprint),
               "dataset": (dataset.dataset_id, dataset.version_id, dataset.dataset_fingerprint,
                           dataset.file_checksum, dataset.schema_fingerprint, codebook.fingerprint),
               "procedure": (procedure, version), "variables": variables, "filter": filter_definition,
               "weighting": (weighting, weight_fp), "source_n": dataset.row_count,
               "unweighted_n": unweighted_n, "denominator": denominator,
               "weighted_base": weighted_base, "outside_base_n": outside, "outputs": outputs,
               "missing": missing_semantics, "precursors": precursor_refs,
               "p_value": p_value, "uncertainty": uncertainty, "parameters": parameters}
    return CanonicalQuantResult(
        method.identity.method_id, method.identity.version, method.identity.execution_version,
        method_pin["fingerprint"], analysis_pin["fingerprint"], result_id, fingerprint,
        dataset.dataset_id, dataset.version_id, dataset.dataset_fingerprint,
        dataset.file_checksum, dataset.schema_fingerprint, codebook.fingerprint,
        procedure, version, variables, filter_definition, weighting, weight_fp,
        dataset.row_count, unweighted_n, denominator, weighted_base, outside,
        missing_semantics, precursor_refs,
        outputs, p_value, uncertainty,
        parameters, canonical_digest(payload, digest_provider=Sha256DigestProvider()),
    )
