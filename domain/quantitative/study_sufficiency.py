from dataclasses import dataclass
from enum import StrEnum

RJ_METHOD_VERSION="rj-1"
class StudyObjectiveObligation(StrEnum): MANDATORY="MANDATORY"; OPTIONAL="OPTIONAL"
class StudySufficiencyLifecycle(StrEnum): DRAFT="DRAFT"; IN_REVIEW="IN_REVIEW"; APPROVED="APPROVED"; REJECTED="REJECTED"; SUPERSEDED="SUPERSEDED"
class StudyPolicyDecision(StrEnum): APPROVED="APPROVED"; REJECTED="REJECTED"
class StudySufficiencyStatus(StrEnum):
    READY_FOR_STUDY_REVIEW="READY_FOR_STUDY_REVIEW"; PARTIALLY_SUPPORTED="PARTIALLY_SUPPORTED"; INCONCLUSIVE="INCONCLUSIVE"; NOT_SUFFICIENT="NOT_SUFFICIENT"; NOT_APPLICABLE_REVIEW="NOT_APPLICABLE_REVIEW"; REQUIRES_METHODOLOGICAL_REVIEW="REQUIRES_METHODOLOGICAL_REVIEW"; BLOCKED="BLOCKED"
class StudySufficiencyDecision(StrEnum):
    STUDY_SUFFICIENT="STUDY_SUFFICIENT"; STUDY_PARTIALLY_SUFFICIENT="STUDY_PARTIALLY_SUFFICIENT"; STUDY_INCONCLUSIVE="STUDY_INCONCLUSIVE"; STUDY_NOT_SUFFICIENT="STUDY_NOT_SUFFICIENT"; STUDY_NOT_APPLICABLE="STUDY_NOT_APPLICABLE"

@dataclass(frozen=True)
class StudyObjectivePolicyEntry: objective_id:str; obligation:StudyObjectiveObligation; rationale:str
@dataclass(frozen=True)
class QuantitativeStudyObjectiveObligationPolicyVersion:
    policy_id:str; version_id:str; version_sequence:int; project_id:str; run_id:str; methodology:str
    selection_id:str; selection_fingerprint:str; manifest_id:str; manifest_fingerprint:str
    research_design_version_id:str; research_design_fingerprint:str; source_brief_version_id:str; source_brief_fingerprint:str
    entries:tuple[StudyObjectivePolicyEntry,...]; method_version:str; parent_version_id:str|None
    lifecycle_status:StudySufficiencyLifecycle; approval_reference:str|None; fingerprint:str; created_at:str; created_by:str
@dataclass(frozen=True)
class QuantitativeStudyObjectiveObligationPolicyApproval:
    approval_id:str; project_id:str; run_id:str; policy_version_id:str; policy_fingerprint:str
    selection_fingerprint:str; manifest_fingerprint:str; research_design_fingerprint:str
    decision:StudyPolicyDecision; actor_id:str; decided_at:str; rationale:str; fingerprint:str
@dataclass(frozen=True)
class StudyObjectiveAssessmentReference:
    objective_id:str; obligation:StudyObjectiveObligation; assessment_version_id:str; assessment_fingerprint:str
    approval_id:str; approval_fingerprint:str; decision:str; deterministic_status:str
    blockers:tuple[str,...]; limitations:tuple[str,...]; fingerprint:str
@dataclass(frozen=True)
class QuantitativeStudySufficiencyAssessmentVersion:
    assessment_id:str; version_id:str; version_sequence:int; project_id:str; run_id:str; methodology:str
    selection_id:str; selection_fingerprint:str; manifest_id:str; manifest_fingerprint:str
    source_brief_version_id:str; source_brief_fingerprint:str; research_design_version_id:str; research_design_fingerprint:str
    policy_version_id:str; policy_fingerprint:str; policy_approval_id:str; policy_approval_fingerprint:str
    mandatory_objective_ids:tuple[str,...]; optional_objective_ids:tuple[str,...]
    objective_assessments:tuple[StudyObjectiveAssessmentReference,...]; blockers:tuple[str,...]; limitations:tuple[str,...]
    status:StudySufficiencyStatus; method_version:str; parent_version_id:str|None
    lifecycle_status:StudySufficiencyLifecycle; approval_reference:str|None; fingerprint:str; created_at:str; created_by:str
@dataclass(frozen=True)
class QuantitativeStudySufficiencyApproval:
    approval_id:str; project_id:str; run_id:str; assessment_version_id:str; assessment_fingerprint:str
    selection_id:str; selection_fingerprint:str; manifest_id:str; manifest_fingerprint:str
    policy_version_id:str; policy_fingerprint:str; policy_approval_id:str; policy_approval_fingerprint:str
    mandatory_assessment_fingerprints:tuple[str,...]; mandatory_approval_fingerprints:tuple[str,...]
    decision:StudySufficiencyDecision; actor_id:str; decided_at:str; rationale:str; fingerprint:str
@dataclass(frozen=True)
class ApprovedStudySufficiencyProjection:
    project_id:str; run_id:str; selection_id:str; selection_fingerprint:str; manifest_id:str; manifest_fingerprint:str
    research_design_version_id:str; research_design_fingerprint:str; assessment_version_id:str; assessment_fingerprint:str
    approval_id:str; approval_fingerprint:str; decision:StudySufficiencyDecision; deterministic_status:StudySufficiencyStatus
    mandatory_objective_references:tuple[StudyObjectiveAssessmentReference,...]; optional_objective_references:tuple[StudyObjectiveAssessmentReference,...]
    blockers:tuple[str,...]; limitations:tuple[str,...]; fingerprint:str
@dataclass(frozen=True)
class DatasetOnlyStudySufficiencyAbsence:
    absence_id:str; project_id:str; run_id:str; status:str; limitation:str; fingerprint:str
