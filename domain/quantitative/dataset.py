from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class DatasetFormat(StrEnum):
    SAV = "SAV"
    XLSX = "XLSX"


class DatasetVersionKind(StrEnum):
    RAW = "RAW"
    CLEANED = "CLEANED"


class VariableType(StrEnum):
    CATEGORICAL = "CATEGORICAL"
    NUMERIC = "NUMERIC"
    ORDINAL_SCALE = "ORDINAL_SCALE"
    DEMOGRAPHIC = "DEMOGRAPHIC"
    TECHNICAL_ID = "TECHNICAL_ID"
    PII = "PII"
    OPEN_TEXT = "OPEN_TEXT"
    UNSUPPORTED = "UNSUPPORTED"


class VariableRole(StrEnum):
    RESPONSE = "RESPONSE"
    DEMOGRAPHIC = "DEMOGRAPHIC"
    TECHNICAL_ID = "TECHNICAL_ID"
    PII = "PII"
    OTHER = "OTHER"
    WEIGHT = "WEIGHT"


class PiiClassification(StrEnum):
    NONE = "NONE"
    PII_RESTRICTED = "PII_RESTRICTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ValidationStatus(StrEnum):
    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class MissingValueRule:
    kind: str
    value: Any | None = None
    low: Any | None = None
    high: Any | None = None
    source: str = "import"


@dataclass(frozen=True)
class VariableDefinition:
    variable_id: str
    name: str
    label: str
    variable_type: VariableType
    role: VariableRole = VariableRole.RESPONSE
    measurement_level: str = "unknown"
    value_labels: tuple[tuple[Any, str], ...] = ()
    missing_rules: tuple[MissingValueRule, ...] = ()
    pii_classification: PiiClassification = PiiClassification.NONE
    multiple_response_set: str | None = None
    semantic_hooks: tuple[str, ...] = ()
    validation_status: ValidationStatus = ValidationStatus.VALID
    validation_messages: tuple[str, ...] = ()
    fingerprint: str = ""
    metadata_provenance: tuple[tuple[str, str], ...] = ()

    @property
    def analytically_eligible(self) -> bool:
        return (
            self.validation_status is not ValidationStatus.BLOCKED
            and self.variable_type
            not in {VariableType.PII, VariableType.OPEN_TEXT, VariableType.UNSUPPORTED}
            and self.role is not VariableRole.WEIGHT
            and self.pii_classification is not PiiClassification.PII_RESTRICTED
        )


@dataclass(frozen=True)
class CodebookVersion:
    codebook_version_id: str
    variables: tuple[VariableDefinition, ...]
    fingerprint: str
    approved: bool = True

    def variable_by_id(self, variable_id: str) -> VariableDefinition:
        for variable in self.variables:
            if variable.variable_id == variable_id:
                return variable
        raise KeyError(variable_id)


@dataclass(frozen=True)
class DatasetVersion:
    dataset_id: str
    version_id: str
    project_id: str
    run_id: str
    version_kind: DatasetVersionKind
    source_file_id: str
    original_filename: str
    file_checksum: str
    format: DatasetFormat
    row_count: int
    variable_count: int
    schema_fingerprint: str
    codebook_version_id: str
    codebook_fingerprint: str
    data_fingerprint: str
    dataset_fingerprint: str
    pii_classification_status: PiiClassification
    validation_status: ValidationStatus
    storage_locator: str
    parser_name: str
    parser_version: str
    warnings: tuple[str, ...] = ()
    respondent_identity_kind: str = "generated_pseudonym"
    weight_set_binding_supported: bool = False
    parent_version_id: str | None = None
    parent_dataset_fingerprint: str | None = None
    cleaning_decision_set_id: str | None = None
    cleaning_decision_set_fingerprint: str | None = None
    cleaning_engine_version: str | None = None
    retained_respondent_set_fingerprint: str | None = None
    excluded_respondent_set_fingerprint: str | None = None
