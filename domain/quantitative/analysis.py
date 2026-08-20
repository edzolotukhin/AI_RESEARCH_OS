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
class CrossTabAnalysisSpecification(AnalysisSpecification):
    statistic_family: str = "CROSS_TAB"
    column_variable_id: str = ""
    percentage_orientation: str = "COLUMN"
    filter_variable_id: str | None = None
    filter_category_value: Any | None = None
    row_categories: tuple[Any, ...] = ()
    column_categories: tuple[Any, ...] = ()


@dataclass(frozen=True)
class NumericAnalysisSpecification(AnalysisSpecification):
    statistic_family: str = "NUMERIC_SUMMARY"
    filter_variable_id: str | None = None
    filter_category_value: Any | None = None


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
    row_variable_id: str | None = None
    row_variable_fingerprint: str | None = None
    row_category_value: Any | None = None
    column_variable_id: str | None = None
    column_variable_fingerprint: str | None = None
    column_category_value: Any | None = None
    percentage_orientation: str | None = None


@dataclass(frozen=True)
class StatisticalTable:
    table_id: str
    analysis_specification_id: str
    analysis_specification_fingerprint: str
    row_variable_id: str
    column_variable_id: str
    percentage_orientation: str
    weighting_status: str
    weight_set_fingerprint: str | None
    analytical_view_fingerprint: str
    filter_definition: str
    base_definition: str
    ordered_result_ids: tuple[str, ...]
    row_labels: tuple[tuple[str, str], ...]
    column_labels: tuple[tuple[str, str], ...]
    fingerprint: str
