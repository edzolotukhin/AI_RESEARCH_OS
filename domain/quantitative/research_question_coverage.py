from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


RH_METHOD_VERSION = "rh-1"


@dataclass(frozen=True)
class QuantitativeAuthorityReference:
    authority_kind: str
    authority_id: str
    authority_fingerprint: str


@dataclass(frozen=True)
class RequirementExecutionBranchReference:
    planned_item_id: str
    planned_item_kind: str
    rd_outcome_id: str
    rd_outcome_fingerprint: str
    finding_ids_and_qh_fingerprints: tuple[tuple[str, str], ...] = ()
    re_lineage_entry_fingerprints: tuple[str, ...] = ()
    insight_ids_and_qj_fingerprints: tuple[tuple[str, str], ...] = ()
    rf_lineage_entry_fingerprints: tuple[str, ...] = ()
    report_section_ids_and_lineage_fingerprints: tuple[tuple[str, str], ...] = ()


class ResearchQuestionAssessmentStatus(StrEnum):
    READY_FOR_SUFFICIENCY_REVIEW = "READY_FOR_SUFFICIENCY_REVIEW"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"
    NOT_ANSWERED = "NOT_ANSWERED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REQUIRES_METHODOLOGICAL_REVIEW = "REQUIRES_METHODOLOGICAL_REVIEW"


class ResearchQuestionCoverageDecision(StrEnum):
    SUFFICIENTLY_ANSWERED = "SUFFICIENTLY_ANSWERED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_ANSWERED = "NOT_ANSWERED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ResearchQuestionCoverageLifecycle(StrEnum):
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class AnalyticalRequirementEvidenceAssessment:
    analytical_requirement_id: str
    obligation: str
    ra_status: str
    rb_status: str
    rc_status: str
    rd_statuses: tuple[tuple[str, str, str], ...]
    re_status: str
    finding_ids: tuple[str, ...]
    insight_status: str | None
    insight_ids: tuple[str, ...]
    report_status: str | None
    report_section_ids: tuple[str, ...]
    status: ResearchQuestionAssessmentStatus
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...]
    fingerprint: str
    branch_references: tuple[RequirementExecutionBranchReference, ...] = ()


@dataclass(frozen=True)
class QuantitativeResearchQuestionCoverageAssessmentVersion:
    assessment_id: str
    version_id: str
    version_sequence: int
    project_id: str
    run_id: str
    methodology: str
    research_design_version_id: str
    research_design_fingerprint: str
    research_question_id: str
    research_question_statement: str
    objective_ids: tuple[str, ...]
    mandatory_requirement_ids: tuple[str, ...]
    optional_requirement_ids: tuple[str, ...]
    requirement_assessments: tuple[AnalyticalRequirementEvidenceAssessment, ...]
    upstream_authority_fingerprints: tuple[tuple[str, str], ...]
    status: ResearchQuestionAssessmentStatus
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    method_version: str
    parent_version_id: str | None
    lifecycle_status: ResearchQuestionCoverageLifecycle
    approval_reference: str | None
    fingerprint: str
    created_at: str
    created_by: str
    upstream_authority_references: tuple[QuantitativeAuthorityReference, ...] = ()


@dataclass(frozen=True)
class QuantitativeResearchQuestionCoverageRunManifest:
    manifest_id: str
    project_id: str
    run_id: str
    research_design_version_id: str
    research_design_fingerprint: str
    assessment_versions_and_fingerprints: tuple[tuple[str, str], ...]
    status: str
    method_version: str
    fingerprint: str

@dataclass(frozen=True)
class QuantitativeResearchQuestionCoverageApproval:
    approval_id: str
    project_id: str
    run_id: str
    assessment_version_id: str
    assessment_fingerprint: str
    upstream_authority_fingerprints: tuple[tuple[str, str], ...]
    decision: ResearchQuestionCoverageDecision
    actor_id: str
    decided_at: str
    rationale: str
    fingerprint: str
    upstream_authority_references: tuple[QuantitativeAuthorityReference, ...] = ()


@dataclass(frozen=True)
class ApprovedResearchQuestionCoverageProjection:
    assessment_id: str
    assessment_version_id: str
    assessment_fingerprint: str
    research_question_id: str
    objective_ids: tuple[str, ...]
    decision: ResearchQuestionCoverageDecision
    requirement_statuses: tuple[tuple[str, str], ...]
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    approval_id: str = ""
    approval_fingerprint: str = ""
    research_design_version_id: str = ""
    research_design_fingerprint: str = ""
    mandatory_requirement_ids: tuple[str, ...] = ()
    optional_requirement_ids: tuple[str, ...] = ()
    upstream_authority_fingerprints: tuple[tuple[str, str], ...] = ()
    upstream_authority_references: tuple[QuantitativeAuthorityReference, ...] = ()


@dataclass(frozen=True)
class DatasetOnlyResearchQuestionCoverageAbsence:
    absence_id: str
    project_id: str
    run_id: str
    status: str
    limitation: str
    fingerprint: str
