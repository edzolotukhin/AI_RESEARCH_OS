from __future__ import annotations

import json
import math
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Iterable

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from domain.quantitative.analysis import AnalysisSpecification
from domain.quantitative.dataset import CodebookVersion, VariableDefinition

FINGERPRINT_CONTRACT_VERSION = "qa-1"


def sha256_bytes(data: bytes, *, digest_provider: DeterministicDigestProvider) -> str:
    return digest_provider.sha256_hex(data)


def canonical_digest(
    payload: Any,
    *,
    digest_provider: DeterministicDigestProvider,
) -> str:
    body = {
        "contract_version": FINGERPRINT_CONTRACT_VERSION,
        "payload": payload,
    }
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return digest_provider.sha256_hex(encoded)


def canonical_scalar(value: Any) -> dict[str, str]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return {"type": "missing", "value": ""}
    if isinstance(value, bool):
        return {"type": "boolean", "value": "true" if value else "false"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, (float, Decimal)):
        decimal = Decimal(str(value))
        if not decimal.is_finite():
            raise ValueError("non-finite numeric values are not canonical")
        normalized = decimal.normalize()
        rendered = format(normalized, "f")
        if rendered == "-0":
            rendered = "0"
        return {"type": "decimal", "value": rendered}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, time):
        return {"type": "time", "value": value.isoformat(timespec="microseconds")}
    return {"type": "string", "value": str(value)}


def variable_payload(variable: VariableDefinition) -> dict[str, Any]:
    return {
        "variable_id": variable.variable_id,
        "name": variable.name,
        "label": variable.label,
        "variable_type": variable.variable_type.value,
        "role": variable.role.value,
        "measurement_level": variable.measurement_level,
        "value_labels": [
            {"value": canonical_scalar(value), "label": label}
            for value, label in variable.value_labels
        ],
        "missing_rules": [
            {
                "kind": rule.kind,
                "value": canonical_scalar(rule.value),
                "low": canonical_scalar(rule.low),
                "high": canonical_scalar(rule.high),
                "source": rule.source,
            }
            for rule in variable.missing_rules
        ],
        "pii_classification": variable.pii_classification.value,
        "multiple_response_set": variable.multiple_response_set,
        "semantic_hooks": list(variable.semantic_hooks),
        "validation_status": variable.validation_status.value,
        "metadata_provenance": list(variable.metadata_provenance),
    }


def fingerprint_variable(
    variable: VariableDefinition,
    *,
    digest_provider: DeterministicDigestProvider,
) -> str:
    return canonical_digest(variable_payload(variable), digest_provider=digest_provider)


def fingerprint_schema(
    variables: Iterable[VariableDefinition],
    *,
    digest_provider: DeterministicDigestProvider,
) -> str:
    return canonical_digest(
        [
            {
                "ordinal": ordinal,
                "variable_id": item.variable_id,
                "name": item.name,
                "variable_type": item.variable_type.value,
            }
            for ordinal, item in enumerate(variables)
        ],
        digest_provider=digest_provider,
    )


def fingerprint_codebook(
    codebook: CodebookVersion | Iterable[VariableDefinition],
    *,
    digest_provider: DeterministicDigestProvider,
) -> str:
    variables = codebook.variables if isinstance(codebook, CodebookVersion) else tuple(codebook)
    return canonical_digest(
        [variable_payload(item) for item in variables],
        digest_provider=digest_provider,
    )


def fingerprint_data(
    rows: Iterable[tuple[Any, ...]],
    *,
    digest_provider: DeterministicDigestProvider,
) -> str:
    return canonical_digest(
        [
            {
                "row_ordinal": ordinal,
                "values": [canonical_scalar(value) for value in row],
            }
            for ordinal, row in enumerate(rows)
        ],
        digest_provider=digest_provider,
    )


def fingerprint_dataset(
    *,
    file_checksum: str,
    schema_fingerprint: str,
    codebook_fingerprint: str,
    data_fingerprint: str,
    digest_provider: DeterministicDigestProvider,
) -> str:
    return canonical_digest(
        {
            "file_checksum": file_checksum,
            "schema_fingerprint": schema_fingerprint,
            "codebook_fingerprint": codebook_fingerprint,
            "data_fingerprint": data_fingerprint,
        },
        digest_provider=digest_provider,
    )


def fingerprint_analysis_specification(
    specification: AnalysisSpecification,
    *,
    digest_provider: DeterministicDigestProvider,
) -> str:
    payload = {
            "specification_id": specification.specification_id,
            "variable_id": specification.variable_id,
            "statistic_family": specification.statistic_family,
            "weighting_status": specification.weighting_status,
            "filter_definition": specification.filter_definition,
            "base_definition": specification.base_definition,
            "presentation_threshold_percent": canonical_scalar(
                specification.presentation_threshold_percent
            ),
        }
    if specification.statistic_family == "CROSS_TAB":
        payload.update(
            {
                "column_variable_id": getattr(specification, "column_variable_id", ""),
                "percentage_orientation": getattr(specification, "percentage_orientation", ""),
                "filter_variable_id": getattr(specification, "filter_variable_id", None),
                "filter_category_value": canonical_scalar(
                    getattr(specification, "filter_category_value", None),
                ),
                "row_categories": [
                    canonical_scalar(item)
                    for item in getattr(specification, "row_categories", ())
                ],
                "column_categories": [
                    canonical_scalar(item)
                    for item in getattr(specification, "column_categories", ())
                ],
            }
        )
    elif specification.statistic_family in {"NUMERIC_SUMMARY", "NPS"}:
        payload.update(
            {
                "filter_variable_id": getattr(specification, "filter_variable_id", None),
                "filter_category_value": canonical_scalar(
                    getattr(specification, "filter_category_value", None),
                ),
            }
        )
        if specification.statistic_family == "NPS":
            payload.update(
                {
                    "scale_minimum": getattr(specification, "scale_minimum", None),
                    "scale_maximum": getattr(specification, "scale_maximum", None),
                    "detractor_range": list(getattr(specification, "detractor_range", ())),
                    "passive_range": list(getattr(specification, "passive_range", ())),
                    "promoter_range": list(getattr(specification, "promoter_range", ())),
                    "method_version": getattr(specification, "method_version", ""),
                }
            )
    elif specification.statistic_family == "CUSTOM_INDEX":
        payload.update(
            {
                "terms": [
                    {
                        "variable_id": item.variable_id,
                        "coefficient": canonical_scalar(item.coefficient),
                    }
                    for item in getattr(specification, "terms", ())
                ],
                "intercept": canonical_scalar(getattr(specification, "intercept", None)),
                "formula_method": getattr(specification, "formula_method", ""),
                "formula_version": getattr(specification, "formula_version", ""),
                "filter_variable_id": getattr(specification, "filter_variable_id", None),
                "filter_category_value": canonical_scalar(
                    getattr(specification, "filter_category_value", None),
                ),
            }
        )
    return canonical_digest(payload, digest_provider=digest_provider)


def fingerprint_statistical_result_payload(
    payload: dict[str, Any],
    *,
    digest_provider: DeterministicDigestProvider,
) -> str:
    return canonical_digest(payload, digest_provider=digest_provider)
