from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RoutingConsequence(StrEnum):
    REQUIRED = "REQUIRED"
    SKIPPED = "SKIPPED"
    TERMINATED = "TERMINATED"
    ALLOWED = "ALLOWED"


class InterviewState(StrEnum):
    COMPLETED = "COMPLETED"
    SCREENED_OUT = "SCREENED_OUT"
    PARTIAL = "PARTIAL"


class IssueClass(StrEnum):
    DETERMINISTIC_VIOLATION = "DETERMINISTIC_VIOLATION"
    DETERMINISTIC_ANOMALY = "DETERMINISTIC_ANOMALY"
    HEURISTIC_SUSPICION = "HEURISTIC_SUSPICION"
    METHODOLOGICAL_REVIEW_FLAG = "METHODOLOGICAL_REVIEW_FLAG"


class IssueType(StrEnum):
    OUT_OF_DOMAIN_VALUE = "OUT_OF_DOMAIN_VALUE"
    ROUTING_VIOLATION = "ROUTING_VIOLATION"
    REQUIRED_ANSWER_MISSING = "REQUIRED_ANSWER_MISSING"
    DUPLICATE_RESPONDENT_ID = "DUPLICATE_RESPONDENT_ID"
    PARTIAL_INTERVIEW = "PARTIAL_INTERVIEW"


class RuleEvaluation(StrEnum):
    EVALUATED = "EVALUATED"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True)
class RoutingRule:
    rule_id: str
    version: str
    antecedent_variable_id: str
    antecedent_values: tuple[Any, ...]
    target_variable_id: str
    consequence: RoutingConsequence
    fingerprint: str


@dataclass(frozen=True)
class QuestionnaireSnapshot:
    snapshot_id: str
    version: str
    codebook_version_id: str
    question_variable_bindings: tuple[tuple[str, str], ...]
    answer_domains: tuple[tuple[str, tuple[Any, ...]], ...]
    required_variable_ids: tuple[str, ...]
    routing_rules: tuple[RoutingRule, ...]
    interview_state_variable_id: str | None
    technical_id_variable_id: str | None
    fingerprint: str


@dataclass(frozen=True)
class DataQualityIssue:
    issue_id: str
    dataset_version_id: str
    dataset_fingerprint: str
    detection_run_id: str
    issue_type: IssueType
    issue_class: IssueClass
    rule_id: str
    rule_version: str
    rule_fingerprint: str
    affected_respondent_refs: tuple[str, ...]
    affected_set_fingerprint: str
    affected_count: int
    affected_share: str
    affected_variable_ids: tuple[str, ...]
    severity: str
    contextual_metrics: tuple[tuple[str, str], ...]
    reproducibility_fingerprint: str
    evaluation: RuleEvaluation = RuleEvaluation.EVALUATED


@dataclass(frozen=True)
class QualityControlRun:
    run_id: str
    dataset_version_id: str
    dataset_fingerprint: str
    questionnaire_fingerprint: str
    issues: tuple[DataQualityIssue, ...]
    not_evaluated_rule_ids: tuple[str, ...]
    fingerprint: str


class CleaningAction(StrEnum):
    NO_ACTION = "NO_ACTION"
    INVESTIGATE = "INVESTIGATE"
    EXCLUDE_RESPONDENTS = "EXCLUDE_RESPONDENTS"
    SET_MISSING = "SET_MISSING"
    RECODE = "RECODE"


class ApprovalState(StrEnum):
    DRAFT = "DRAFT"
    PREVIEWED = "PREVIEWED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"
    EXECUTED = "EXECUTED"


@dataclass(frozen=True)
class CleaningDecision:
    decision_id: str
    parent_dataset_fingerprint: str
    issue_ids: tuple[str, ...]
    action: CleaningAction
    affected_respondent_refs: tuple[str, ...]
    affected_variable_ids: tuple[str, ...]
    transformation: tuple[tuple[str, Any], ...]
    rationale: str
    actor_id: str
    preview_count: int
    expected_transformation_fingerprint: str
    fingerprint: str

    @property
    def material(self) -> bool:
        return self.action in {
            CleaningAction.EXCLUDE_RESPONDENTS,
            CleaningAction.SET_MISSING,
            CleaningAction.RECODE,
        }


@dataclass(frozen=True)
class CleaningDecisionSet:
    decision_set_id: str
    parent_version_id: str
    parent_dataset_fingerprint: str
    decisions: tuple[CleaningDecision, ...]
    preview_fingerprint: str
    previewed_affected_count: int
    approval_state: ApprovalState
    approver_id: str | None
    approved_at: str | None
    fingerprint: str


class ReconciliationState(StrEnum):
    NEW = "NEW"
    REMAINS = "REMAINS"
    RESOLVED = "RESOLVED"
    SUPERSEDED = "SUPERSEDED"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True)
class IssueReconciliation:
    issue_id: str
    state: ReconciliationState
    related_issue_id: str | None = None


class DatasetQualityState(StrEnum):
    QC_PENDING = "QC_PENDING"
    QC_REVIEW_REQUIRED = "QC_REVIEW_REQUIRED"
    QC_APPROVED = "QC_APPROVED"
    QC_BLOCKED = "QC_BLOCKED"


@dataclass(frozen=True)
class DatasetQualityAssessment:
    dataset_version_id: str
    dataset_fingerprint: str
    qc_run_fingerprint: str | None
    state: DatasetQualityState
    approval_fingerprint: str | None
    current: bool
    fingerprint: str
