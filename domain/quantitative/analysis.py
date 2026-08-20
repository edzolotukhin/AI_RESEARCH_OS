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
class NpsAnalysisSpecification(NumericAnalysisSpecification):
    statistic_family: str = "NPS"
    scale_minimum: int = 0
    scale_maximum: int = 10
    detractor_range: tuple[int, int] = (0, 6)
    passive_range: tuple[int, int] = (7, 8)
    promoter_range: tuple[int, int] = (9, 10)
    method_version: str = "STANDARD_NPS_V1"


@dataclass(frozen=True)
class IndexTerm:
    variable_id: str
    coefficient: Decimal


@dataclass(frozen=True)
class CustomIndexAnalysisSpecification(AnalysisSpecification):
    statistic_family: str = "CUSTOM_INDEX"
    terms: tuple[IndexTerm, ...] = ()
    intercept: Decimal = Decimal(0)
    formula_method: str = "MEAN_OF_ROW_LINEAR_COMBINATION"
    formula_version: str = "LINEAR_INDEX_V1"
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


@dataclass(frozen=True)
class ComparisonSpecification:
    comparison_id: str
    method: str
    variable_id: str
    group_variable_id: str
    group_a_category: Any
    group_b_category: Any
    outcome_category: Any | None = None
    alpha: Decimal = Decimal("0.05")
    sidedness: str = "TWO_SIDED"
    minimum_group_base: int = 2
    filter_definition: str = "ALL_ROWS"
    base_definition: str = "VALID_RESPONSES_BY_INDEPENDENT_GROUP"
    method_version: str = "QG_1"
    fingerprint: str = ""


@dataclass(frozen=True)
class AnalyticalComparisonResult:
    comparison_result_id: str
    dataset_version_id: str
    dataset_fingerprint: str
    data_fingerprint: str
    specification_id: str
    specification_fingerprint: str
    group_a_result_id: str
    group_a_result_fingerprint: str
    group_b_result_id: str
    group_b_result_fingerprint: str
    observed_difference: Decimal
    test_statistic: Decimal
    p_value: Decimal
    alpha: Decimal
    significant: bool
    sidedness: str
    minimum_group_base: int
    group_a_base: int
    group_b_base: int
    method: str
    method_version: str
    reproducibility_fingerprint: str

    @property
    def supports_significance_wording(self) -> bool:
        return self.significant
