from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

FINGERPRINT_METHOD_VERSION = "rb-1"

class ReconciliationMatchStatus(StrEnum):
    EXACT_MATCH = "EXACT_MATCH"
    COMPATIBLE_MATCH = "COMPATIBLE_MATCH"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    MISSING_IN_DATA = "MISSING_IN_DATA"
    INCOMPATIBLE_IN_DATA = "INCOMPATIBLE_IN_DATA"
    TRANSFORMATION_REQUIRED = "TRANSFORMATION_REQUIRED"

class ImportedExtraStatus(StrEnum):
    EXTRA_SAFE_UNMAPPED = "EXTRA_SAFE_UNMAPPED"
    EXTRA_ANALYTICAL_REVIEW_REQUIRED = "EXTRA_ANALYTICAL_REVIEW_REQUIRED"
    EXTRA_TECHNICAL = "EXTRA_TECHNICAL"
    EXTRA_PII_RESTRICTED = "EXTRA_PII_RESTRICTED"

class ReconciliationOverallStatus(StrEnum):
    DETERMINISTICALLY_ACCEPTED = "DETERMINISTICALLY_ACCEPTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED_WITH_MAPPINGS = "APPROVED_WITH_MAPPINGS"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"

class ReconciliationLifecycle(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"

class DataAvailabilityStatus(StrEnum):
    DATA_MEASUREMENT_AVAILABLE = "DATA_MEASUREMENT_AVAILABLE"
    PARTIALLY_AVAILABLE = "PARTIALLY_AVAILABLE"
    MISSING_IN_DATA = "MISSING_IN_DATA"
    INCOMPATIBLE_IN_DATA = "INCOMPATIBLE_IN_DATA"
    TRANSFORMATION_REQUIRED = "TRANSFORMATION_REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"

class ReconciliationApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class SemanticHookEquivalenceDecision(StrEnum):
    APPROVE_EQUIVALENCE = "APPROVE_EQUIVALENCE"
    REJECT_EQUIVALENCE = "REJECT_EQUIVALENCE"

@dataclass(frozen=True)
class ReviewedSemanticHookEquivalence:
    decision_id: str; project_id: str; run_id: str
    reconciliation_version_id: str; reconciliation_fingerprint: str
    expected_variable_id: str; expected_variable_fingerprint: str; expected_semantic_hook: str
    actual_variable_id: str; actual_variable_fingerprint: str; codebook_fingerprint: str
    decision: SemanticHookEquivalenceDecision; actor_id: str; rationale: str; decided_at: str
    method_version: str; fingerprint: str

@dataclass(frozen=True)
class ReviewedMeasurementMapping:
    decision_id: str; expected_variable_id: str; expected_variable_fingerprint: str
    actual_variable_id: str; actual_variable_fingerprint: str
    category_code_mapping: tuple[tuple[str, str], ...]; missing_semantic_mapping: tuple[tuple[str, str], ...]
    scale_mapping: tuple[tuple[str, str], ...]; mr_matrix_mapping: tuple[tuple[str, str], ...]
    actor_id: str; rationale: str; decided_at: str; fingerprint: str
    semantic_hook_equivalences: tuple[ReviewedSemanticHookEquivalence, ...] = ()

@dataclass(frozen=True)
class MeasurementVariableReconciliation:
    mapping_id: str; expected_variable_id: str; expected_variable_fingerprint: str; source_question_id: str
    source_option_id: str | None; matrix_row_id: str | None; actual_variable_id: str | None; actual_variable_fingerprint: str | None
    status: ReconciliationMatchStatus; category_code_mapping: tuple[tuple[str, str], ...]
    missing_semantic_mapping: tuple[tuple[str, str], ...]; scale_mapping: tuple[tuple[str, str], ...]
    mr_matrix_mapping: tuple[tuple[str, str], ...]; transformation_reference: str | None
    reviewer_decision_reference: str | None; reasons: tuple[str, ...]; fingerprint: str

@dataclass(frozen=True)
class ImportedVariableClassification:
    actual_variable_id: str; actual_variable_fingerprint: str; status: ImportedExtraStatus; reason: str; fingerprint: str

@dataclass(frozen=True)
class RequirementDataAvailability:
    requirement_id: str; status: DataAvailabilityStatus; expected_variable_ids: tuple[str, ...]
    usable_actual_variable_ids: tuple[str, ...]; reasons: tuple[str, ...]

@dataclass(frozen=True)
class MeasurementDataAvailabilityManifest:
    manifest_id: str; project_id: str; questionnaire_version_id: str; questionnaire_fingerprint: str
    expected_measurement_schema_fingerprint: str; dataset_version_id: str; dataset_fingerprint: str
    codebook_version_id: str; codebook_fingerprint: str; reconciliation_fingerprint: str
    requirements: tuple[RequirementDataAvailability, ...]; fingerprint: str

@dataclass(frozen=True)
class QuantitativeMeasurementReconciliationVersion:
    reconciliation_id: str; version_id: str; version_sequence: int; project_id: str; methodology: str
    questionnaire_id: str; questionnaire_version_id: str; questionnaire_fingerprint: str
    expected_measurement_schema_fingerprint: str; dataset_version_id: str; dataset_fingerprint: str
    data_fingerprint: str; schema_fingerprint: str; codebook_version_id: str; codebook_fingerprint: str
    reconciliation_method_version: str; variable_outcomes: tuple[MeasurementVariableReconciliation, ...]
    imported_extras: tuple[ImportedVariableClassification, ...]; reviewed_mapping_decision_ids: tuple[str, ...]
    required_transformation_references: tuple[str, ...]; data_availability_manifest_id: str
    data_availability_manifest_fingerprint: str; questionnaire_snapshot_id: str | None
    questionnaire_snapshot_fingerprint: str | None; overall_status: ReconciliationOverallStatus
    lifecycle_status: ReconciliationLifecycle; parent_version_id: str | None; approval_reference: str | None
    fingerprint: str; created_at: str; created_by: str; fingerprint_method_version: str = FINGERPRINT_METHOD_VERSION

@dataclass(frozen=True)
class QuantitativeMeasurementReconciliationApproval:
    approval_id: str; project_id: str; methodology: str; reconciliation_version_id: str
    reconciliation_fingerprint: str; questionnaire_fingerprint: str; expected_measurement_schema_fingerprint: str
    dataset_fingerprint: str; data_fingerprint: str; schema_fingerprint: str; codebook_fingerprint: str
    actor_id: str; decided_at: str; decision: ReconciliationApprovalDecision; rationale: str; fingerprint: str

@dataclass(frozen=True)
class ApprovedMeasurementReconciliationProjection:
    reconciliation_version_id: str; reconciliation_fingerprint: str; questionnaire_version_id: str
    questionnaire_fingerprint: str; expected_measurement_schema_fingerprint: str; dataset_version_id: str
    dataset_fingerprint: str; codebook_version_id: str; codebook_fingerprint: str
    variable_mappings: tuple[tuple[str, str, str, str], ...]; data_availability: tuple[tuple[str, str], ...]
    questionnaire_snapshot_id: str | None; questionnaire_snapshot_fingerprint: str | None; limitations: tuple[str, ...]

@dataclass(frozen=True)
class DatasetOnlyReconciliationAuthority:
    authority_id: str; project_id: str; run_id: str; status: str; limitation: str; fingerprint: str
