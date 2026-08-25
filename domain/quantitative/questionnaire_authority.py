from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from domain.quantitative.dataset import PiiClassification, VariableRole, VariableType


FINGERPRINT_METHOD_VERSION = "ra-1"


class QuestionnaireLifecycle(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class QuestionnaireAuthorshipMode(StrEnum):
    INTERNAL_HUMAN = "INTERNAL_HUMAN"
    EXTERNAL_AUTHORED = "EXTERNAL_AUTHORED"


class QuestionnaireQuestionType(StrEnum):
    SINGLE_CHOICE = "SINGLE_CHOICE"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    NUMERIC = "NUMERIC"
    OPEN_TEXT = "OPEN_TEXT"
    RATING_SCALE = "RATING_SCALE"
    LIKERT = "LIKERT"
    NPS = "NPS"
    MATRIX_SINGLE_CHOICE = "MATRIX_SINGLE_CHOICE"
    MATRIX_RATING = "MATRIX_RATING"


class QuestionnaireQuestionRole(StrEnum):
    SUBSTANTIVE = "SUBSTANTIVE"
    SCREENING = "SCREENING"
    DEMOGRAPHIC = "DEMOGRAPHIC"
    QUALITY_CONTROL = "QUALITY_CONTROL"
    TECHNICAL_ROUTING = "TECHNICAL_ROUTING"


class ScaleInterpretation(StrEnum):
    ORDINAL = "ORDINAL"
    NUMERIC = "NUMERIC"


class RoutingConditionKind(StrEnum):
    EQUALS_OPTION = "EQUALS_OPTION"
    IN_OPTION_SET = "IN_OPTION_SET"
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"
    NUMERIC_COMPARE = "NUMERIC_COMPARE"
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class NumericComparator(StrEnum):
    LT = "LT"
    LTE = "LTE"
    EQ = "EQ"
    GTE = "GTE"
    GT = "GT"


class RoutingActionType(StrEnum):
    DEFAULT_CONTINUE = "DEFAULT_CONTINUE"
    GOTO_QUESTION = "GOTO_QUESTION"
    GOTO_SECTION = "GOTO_SECTION"
    SKIP_QUESTION = "SKIP_QUESTION"
    SKIP_SECTION = "SKIP_SECTION"
    TERMINATE = "TERMINATE"
    SCREENED_OUT = "SCREENED_OUT"


class QuestionnaireCoverageStatus(StrEnum):
    MEASURED = "MEASURED"
    PARTIALLY_MEASURED = "PARTIALLY_MEASURED"
    NOT_MEASURED = "NOT_MEASURED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class QuestionnaireApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class QuestionnaireAuthorityPresence(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"


class QuestionnaireCoverageAuthorityStatus(StrEnum):
    NOT_ASSESSED_NO_QUESTIONNAIRE = "NOT_ASSESSED_NO_QUESTIONNAIRE"


@dataclass(frozen=True)
class AnswerOption:
    option_id: str
    label: str
    dataset_value_code: str
    display_order: int
    ordinal_position: int | None = None
    analytical_score: Decimal | None = None
    exclusive: bool = False
    other_specify: bool = False
    missing_semantic: str | None = None


@dataclass(frozen=True)
class ScaleDefinition:
    minimum: Decimal
    maximum: Decimal
    ordered_labels: tuple[tuple[Decimal, str], ...]
    interpretation: ScaleInterpretation
    analytical_scores: tuple[tuple[Decimal, Decimal], ...] = ()
    missing_value_codes: tuple[tuple[Decimal, str], ...] = ()


@dataclass(frozen=True)
class MatrixRow:
    row_id: str
    label: str
    display_order: int


@dataclass(frozen=True)
class ExpectedVariableBinding:
    expected_variable_id: str
    variable_name: str
    option_id: str | None = None
    matrix_row_id: str | None = None


@dataclass(frozen=True)
class QuestionnaireSection:
    section_id: str
    title: str
    purpose: str
    display_order: int


@dataclass(frozen=True)
class QuestionnaireQuestion:
    question_id: str
    section_id: str
    role: QuestionnaireQuestionRole
    question_type: QuestionnaireQuestionType
    wording: str
    respondent_instructions: str | None
    interviewer_instructions: str | None
    analytical_requirement_ids: tuple[str, ...]
    role_purpose: str | None
    response_required: bool
    answer_options: tuple[AnswerOption, ...]
    scale: ScaleDefinition | None
    matrix_rows: tuple[MatrixRow, ...]
    validation_constraints: tuple[tuple[str, str], ...]
    expected_variable_bindings: tuple[ExpectedVariableBinding, ...]
    routing_participation: bool
    display_order: int
    provenance: str


@dataclass(frozen=True)
class RoutingCondition:
    kind: RoutingConditionKind
    question_id: str | None = None
    option_ids: tuple[str, ...] = ()
    comparator: NumericComparator | None = None
    numeric_value: Decimal | None = None
    children: tuple["RoutingCondition", ...] = ()


@dataclass(frozen=True)
class RoutingAction:
    action_type: RoutingActionType
    target_id: str | None = None
    termination_code: str | None = None


@dataclass(frozen=True)
class QuestionnaireRoutingRule:
    rule_id: str
    source_question_id: str
    priority: int
    condition: RoutingCondition
    action: RoutingAction


@dataclass(frozen=True)
class RequirementCoverageDeclaration:
    requirement_id: str
    status: QuestionnaireCoverageStatus
    rationale: str


@dataclass(frozen=True)
class ExpectedMissingValueRule:
    code: str
    semantic: str


@dataclass(frozen=True)
class ExpectedVariableDefinition:
    expected_variable_id: str
    variable_name: str
    source_question_id: str
    source_option_id: str | None
    matrix_row_id: str | None
    label: str
    variable_type: VariableType
    analytical_role: VariableRole
    measurement_level: str
    value_labels: tuple[tuple[str, str], ...]
    ordinal_ordering: tuple[str, ...]
    analytical_scoring: tuple[tuple[str, Decimal], ...]
    missing_value_rules: tuple[ExpectedMissingValueRule, ...]
    multiple_response_set_id: str | None
    matrix_group_id: str | None
    semantic_hooks: tuple[str, ...]
    weighting_control_eligible: bool
    pii_expectation: PiiClassification
    fingerprint: str


@dataclass(frozen=True)
class ExpectedMeasurementSchema:
    schema_id: str
    project_id: str
    questionnaire_version_id: str
    questionnaire_fingerprint: str
    variables: tuple[ExpectedVariableDefinition, ...]
    fingerprint: str
    fingerprint_method_version: str = FINGERPRINT_METHOD_VERSION


@dataclass(frozen=True)
class QuestionnaireValidationManifest:
    manifest_id: str
    project_id: str
    questionnaire_version_id: str
    questionnaire_fingerprint: str
    valid: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    fingerprint: str
    fingerprint_method_version: str = FINGERPRINT_METHOD_VERSION


@dataclass(frozen=True)
class RequirementMeasurementCoverage:
    requirement_id: str
    status: QuestionnaireCoverageStatus
    supporting_question_ids: tuple[str, ...]
    expected_variable_ids: tuple[str, ...]
    rationale: str | None


@dataclass(frozen=True)
class QuestionnaireDesignCoverageManifest:
    manifest_id: str
    project_id: str
    research_design_version_id: str
    research_design_fingerprint: str
    questionnaire_version_id: str
    questionnaire_fingerprint: str
    expected_measurement_schema_fingerprint: str
    requirements: tuple[RequirementMeasurementCoverage, ...]
    fingerprint: str
    fingerprint_method_version: str = FINGERPRINT_METHOD_VERSION


@dataclass(frozen=True)
class QuantitativeQuestionnaireVersion:
    questionnaire_id: str
    version_id: str
    version_sequence: int
    project_id: str
    methodology: str
    research_design_version_id: str
    research_design_fingerprint: str
    title: str
    purpose: str
    language: str
    sections: tuple[QuestionnaireSection, ...]
    questions: tuple[QuestionnaireQuestion, ...]
    routing_rules: tuple[QuestionnaireRoutingRule, ...]
    expected_measurement_schema_id: str
    expected_measurement_schema_fingerprint: str
    provenance: str
    authorship_mode: QuestionnaireAuthorshipMode
    estimated_interview_length_minutes: int
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    coverage_declarations: tuple[RequirementCoverageDeclaration, ...]
    parent_version_id: str | None
    lifecycle_status: QuestionnaireLifecycle
    approval_reference: str | None
    validation_manifest_id: str
    validation_manifest_fingerprint: str
    coverage_manifest_id: str
    coverage_manifest_fingerprint: str
    fingerprint: str
    created_at: str
    created_by: str
    fingerprint_method_version: str = FINGERPRINT_METHOD_VERSION


@dataclass(frozen=True)
class QuantitativeQuestionnaireApproval:
    approval_id: str
    project_id: str
    methodology: str
    questionnaire_version_id: str
    questionnaire_fingerprint: str
    research_design_version_id: str
    research_design_fingerprint: str
    validation_manifest_fingerprint: str
    coverage_manifest_fingerprint: str
    actor_id: str
    decided_at: str
    decision: QuestionnaireApprovalDecision
    rationale: str
    fingerprint: str


@dataclass(frozen=True)
class DatasetOnlyQuestionnaireAuthority:
    authority_id: str
    project_id: str
    run_id: str
    questionnaire_authority: QuestionnaireAuthorityPresence
    measurement_coverage_status: QuestionnaireCoverageAuthorityStatus
    limitation: str
    fingerprint: str


@dataclass(frozen=True)
class ApprovedQuestionnaireProjection:
    questionnaire_id: str
    version_id: str
    fingerprint: str
    research_design_version_id: str
    research_design_fingerprint: str
    sections: tuple[tuple[str, str], ...]
    questions: tuple[tuple[str, str, str, str], ...]
    options: tuple[tuple[str, str, str, str], ...]
    routing_summary: tuple[tuple[str, str, str], ...]
    expected_variables: tuple[tuple[str, str, str], ...]
    requirement_traceability: tuple[tuple[str, tuple[str, ...]], ...]
    coverage: tuple[tuple[str, str], ...]
    limitations: tuple[str, ...]
