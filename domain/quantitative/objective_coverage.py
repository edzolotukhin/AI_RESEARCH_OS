from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

RI_METHOD_VERSION = "ri-1"

class ObjectiveResearchQuestionObligation(StrEnum):
    MANDATORY = "MANDATORY"
    OPTIONAL = "OPTIONAL"

class ObjectiveCoverageLifecycle(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"

class ObjectivePolicyDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class ObjectiveAssessmentStatus(StrEnum):
    READY_FOR_OBJECTIVE_REVIEW = "READY_FOR_OBJECTIVE_REVIEW"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"
    NOT_SATISFIED = "NOT_SATISFIED"
    NOT_APPLICABLE_REVIEW = "NOT_APPLICABLE_REVIEW"
    REQUIRES_METHODOLOGICAL_REVIEW = "REQUIRES_METHODOLOGICAL_REVIEW"

class ObjectiveCoverageDecision(StrEnum):
    OBJECTIVE_SATISFIED = "OBJECTIVE_SATISFIED"
    OBJECTIVE_PARTIALLY_SATISFIED = "OBJECTIVE_PARTIALLY_SATISFIED"
    OBJECTIVE_INCONCLUSIVE = "OBJECTIVE_INCONCLUSIVE"
    OBJECTIVE_NOT_SATISFIED = "OBJECTIVE_NOT_SATISFIED"
    OBJECTIVE_NOT_APPLICABLE = "OBJECTIVE_NOT_APPLICABLE"

@dataclass(frozen=True)
class ObjectiveResearchQuestionPolicyEdge:
    objective_id: str
    research_question_id: str
    obligation: ObjectiveResearchQuestionObligation
    rationale: str

@dataclass(frozen=True)
class QuantitativeObjectiveResearchQuestionPolicyVersion:
    policy_id: str
    version_id: str
    version_sequence: int
    project_id: str
    run_id: str
    methodology: str
    research_design_version_id: str
    research_design_fingerprint: str
    edges: tuple[ObjectiveResearchQuestionPolicyEdge, ...]
    method_version: str
    parent_version_id: str | None
    lifecycle_status: ObjectiveCoverageLifecycle
    approval_reference: str | None
    fingerprint: str
    created_at: str
    created_by: str

@dataclass(frozen=True)
class QuantitativeObjectiveResearchQuestionPolicyApproval:
    approval_id: str
    project_id: str
    run_id: str
    methodology: str
    policy_version_id: str
    policy_fingerprint: str
    research_design_version_id: str
    research_design_fingerprint: str
    decision: ObjectivePolicyDecision
    actor_id: str
    decided_at: str
    rationale: str
    fingerprint: str

@dataclass(frozen=True)
class ObjectiveResearchQuestionAssessmentReference:
    research_question_id: str
    obligation: ObjectiveResearchQuestionObligation
    assessment_version_id: str
    assessment_fingerprint: str
    approval_id: str
    approval_fingerprint: str
    decision: str
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    fingerprint: str

@dataclass(frozen=True)
class QuantitativeObjectiveCoverageAssessmentVersion:
    assessment_id: str
    version_id: str
    version_sequence: int
    project_id: str
    run_id: str
    methodology: str
    research_design_version_id: str
    research_design_fingerprint: str
    objective_id: str
    objective_statement: str
    objective_statement_fingerprint: str
    policy_version_id: str
    policy_fingerprint: str
    policy_approval_id: str
    policy_approval_fingerprint: str
    mandatory_research_question_ids: tuple[str, ...]
    optional_research_question_ids: tuple[str, ...]
    research_question_assessments: tuple[ObjectiveResearchQuestionAssessmentReference, ...]
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    status: ObjectiveAssessmentStatus
    method_version: str
    parent_version_id: str | None
    lifecycle_status: ObjectiveCoverageLifecycle
    approval_reference: str | None
    fingerprint: str
    created_at: str
    created_by: str

@dataclass(frozen=True)
class QuantitativeObjectiveCoverageApproval:
    approval_id: str
    project_id: str
    run_id: str
    methodology: str
    objective_id: str
    assessment_version_id: str
    assessment_fingerprint: str
    research_design_fingerprint: str
    policy_fingerprint: str
    research_question_assessment_fingerprints: tuple[str, ...]
    research_question_approval_fingerprints: tuple[str, ...]
    decision: ObjectiveCoverageDecision
    actor_id: str
    decided_at: str
    rationale: str
    fingerprint: str
    policy_approval_id: str = ""
    policy_approval_fingerprint: str = ""

@dataclass(frozen=True)
class ApprovedObjectiveCoverageProjection:
    project_id: str
    run_id: str
    objective_id: str
    research_design_version_id: str
    research_design_fingerprint: str
    assessment_version_id: str
    assessment_fingerprint: str
    approval_id: str
    approval_fingerprint: str
    decision: ObjectiveCoverageDecision
    deterministic_status: ObjectiveAssessmentStatus
    policy_version_id: str
    policy_fingerprint: str
    policy_approval_id: str
    policy_approval_fingerprint: str
    research_question_assessment_references: tuple[ObjectiveResearchQuestionAssessmentReference, ...]
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    fingerprint: str

@dataclass(frozen=True)
class QuantitativeObjectiveCoverageRunManifest:
    manifest_id: str
    project_id: str
    run_id: str
    research_design_version_id: str
    research_design_fingerprint: str
    assessment_references: tuple[tuple[str, str, str], ...]
    approval_references: tuple[tuple[str, str, str], ...]
    unresolved_objective_ids: tuple[str, ...]
    method_version: str
    fingerprint: str

@dataclass(frozen=True)
class DatasetOnlyObjectiveCoverageAbsence:
    absence_id: str
    project_id: str
    run_id: str
    status: str
    limitation: str
    fingerprint: str
