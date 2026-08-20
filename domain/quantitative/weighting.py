from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class WeightSourceType(StrEnum):
    EMBEDDED_VARIABLE = "EMBEDDED_VARIABLE"
    SEPARATE_FILE = "SEPARATE_FILE"


class WeightValidationStatus(StrEnum):
    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    BLOCKED = "BLOCKED"


class WeightApprovalState(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class WeightSet:
    weight_set_id: str
    dataset_version_id: str
    dataset_fingerprint: str
    source_type: WeightSourceType
    source_provenance_fingerprint: str
    respondent_key_specification_fingerprint: str
    weight_vector: tuple[tuple[str, Decimal], ...]
    vector_fingerprint: str
    weight_count: int
    retained_respondent_count: int
    coverage_count: int
    coverage_share: Decimal
    minimum_weight: Decimal | None
    maximum_weight: Decimal | None
    mean_weight: Decimal | None
    sum_weights: Decimal
    zero_weight_count: int
    negative_weight_count: int
    missing_weight_count: int
    non_finite_count: int
    unknown_key_count: int
    excluded_parent_row_count: int
    validation_status: WeightValidationStatus
    validation_messages: tuple[str, ...]
    validation_fingerprint: str
    reproducibility_fingerprint: str
    source_checksum: str | None = None
    source_variable_fingerprint: str | None = None
    parser_name: str | None = None
    parser_version: str | None = None


@dataclass(frozen=True)
class WeightSetApproval:
    weight_set_id: str
    weight_set_fingerprint: str
    dataset_fingerprint: str
    validation_fingerprint: str
    state: WeightApprovalState
    approver_id: str | None
    approved_at: str | None
    fingerprint: str


class WeightingMode(StrEnum):
    UNWEIGHTED = "UNWEIGHTED"
    WEIGHTED = "WEIGHTED"


@dataclass(frozen=True)
class AnalyticalDatasetView:
    view_id: str
    dataset_version_id: str
    dataset_fingerprint: str
    dataset_quality_assessment_fingerprint: str
    analysis_specification_fingerprint: str
    weighting_mode: WeightingMode
    weight_set_id: str | None
    weight_set_fingerprint: str | None
    eligible_respondent_set_fingerprint: str
    filter_definition: str
    base_definition: str
    fingerprint: str
