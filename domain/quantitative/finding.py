from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any


class QuantitativeClaimType(str, Enum):
    DESCRIPTIVE_VALUE = "DESCRIPTIVE_VALUE"
    NUMERIC_SUMMARY = "NUMERIC_SUMMARY"
    KPI_VALUE = "KPI_VALUE"
    DESCRIPTIVE_COMPARISON = "DESCRIPTIVE_COMPARISON"
    SIGNIFICANT_COMPARISON = "SIGNIFICANT_COMPARISON"


class QuantitativeSupportStatus(str, Enum):
    UNVALIDATED = "UNVALIDATED"
    SUPPORTED = "SUPPORTED"


@dataclass(frozen=True)
class QuantitativeResultReference:
    result_id: str
    reproducibility_fingerprint: str


@dataclass(frozen=True)
class QuantitativeComparisonReference:
    comparison_result_id: str
    reproducibility_fingerprint: str


@dataclass(frozen=True)
class QuantitativeClaim:
    claim_type: QuantitativeClaimType
    value: Decimal | None
    variable_id: str
    statistic_type: str | None = None
    category_value: Any | None = None
    filter_definition: str = "ALL_ROWS"
    base_definition: str = "VALID_RESPONSES"
    weighting_status: str = "UNWEIGHTED"
    weight_set_fingerprint: str | None = None
    direction: str | None = None
    display_value: str | None = None


@dataclass(frozen=True)
class QuantitativeFinding:
    finding_id: str
    text: str
    claim: QuantitativeClaim
    statistical_result_refs: tuple[QuantitativeResultReference, ...]
    comparison_result_refs: tuple[QuantitativeComparisonReference, ...] = ()
    methodology: str = "QUANTITATIVE"
    rounding_decimal_places: int = 1
    rounding_policy: str = "ROUND_HALF_UP"
    rounding_version: str = "QH_DISPLAY_V1"
    pii_exposures: tuple[str, ...] = ()
    analytical_context_fingerprint: str = ""
    support_validation_status: QuantitativeSupportStatus = QuantitativeSupportStatus.UNVALIDATED
    support_validation_fingerprint: str = ""
    support_validation_version: str = "qh-1"
