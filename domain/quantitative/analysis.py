from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class AnalysisSpecification:
    specification_id: str
    variable_id: str
    statistic_family: str = "ONE_WAY"
    weighting_status: str = "UNWEIGHTED"
    filter_definition: str = "ALL_ROWS"
    base_definition: str = "VALID_RESPONSES"
    presentation_threshold_percent: Decimal = Decimal("1.0")
    fingerprint: str = ""


@dataclass(frozen=True)
class StatisticalResult:
    result_id: str
    dataset_version_id: str
    dataset_fingerprint: str
    data_fingerprint: str
    codebook_fingerprint: str
    variable_id: str
    variable_fingerprint: str
    analysis_specification_id: str
    analysis_specification_fingerprint: str
    weighting_status: str
    filter_definition: str
    base_definition: str
    missing_value_semantics: tuple[dict[str, Any], ...]
    statistic_type: str
    value: int | Decimal
    denominator: int | Decimal | None
    category_value: Any | None
    computation_method: str
    computation_version: str
    presentation_eligible: bool
    reproducibility_fingerprint: str
    weight_set_id: str | None = None
    weight_set_fingerprint: str | None = None
    analytical_view_id: str | None = None
    analytical_view_fingerprint: str | None = None
    unweighted_n: int | None = None
    weighted_base: Decimal | None = None
