from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from domain.quantitative.analysis import AnalysisSpecification, ComparisonSpecification

FINGERPRINT_METHOD_VERSION = "rc-1"

class AnalysisPlanLifecycle(StrEnum):
    DRAFT="DRAFT"; IN_REVIEW="IN_REVIEW"; APPROVED="APPROVED"; REJECTED="REJECTED"; SUPERSEDED="SUPERSEDED"
class AnalysisPlanApprovalDecision(StrEnum): APPROVED="APPROVED"; REJECTED="REJECTED"
class AnalysisWeightingPolicy(StrEnum): UNWEIGHTED="UNWEIGHTED"; WEIGHTED_EXACT_WEIGHTSET="WEIGHTED_EXACT_WEIGHTSET"
class AnalysisExecutionSupport(StrEnum): SUPPORTED="SUPPORTED"; UNSUPPORTED="UNSUPPORTED"
class AnalysisPlanCoverageStatus(StrEnum):
    PLANNED_EXECUTABLE="PLANNED_EXECUTABLE"; PARTIALLY_PLANNED="PARTIALLY_PLANNED"; NOT_PLANNED="NOT_PLANNED"; BLOCKED_BY_MEASUREMENT="BLOCKED_BY_MEASUREMENT"; TRANSFORMATION_REQUIRED="TRANSFORMATION_REQUIRED"; NOT_ANALYZABLE_UNSUPPORTED_METHOD="NOT_ANALYZABLE_UNSUPPORTED_METHOD"; NOT_APPLICABLE="NOT_APPLICABLE"

@dataclass(frozen=True)
class CategoryEqualsFilter:
    variable_id: str; variable_fingerprint: str; category_code: Any; semantic_interpretation: str

@dataclass(frozen=True)
class PlanVariableBinding:
    expected_variable_id: str; actual_variable_id: str; actual_variable_fingerprint: str

@dataclass(frozen=True)
class ExactWeightSetBinding:
    weight_set_id: str; weight_set_fingerprint: str; dataset_version_id: str; dataset_fingerprint: str; validation_fingerprint: str; approval_fingerprint: str; effective_sample_size: str | None; limitations: tuple[str,...]=()

@dataclass(frozen=True)
class PlannedAnalysis:
    planned_analysis_id: str
    specification: AnalysisSpecification
    specification_fingerprint: str
    objective_ids: tuple[str,...]
    research_question_ids: tuple[str,...]
    analytical_requirement_ids: tuple[str,...]
    variable_bindings: tuple[PlanVariableBinding,...]
    expected_result_family: str
    obligation: str
    weighting_policy: AnalysisWeightingPolicy
    weight_set_binding: ExactWeightSetBinding | None = None
    category_filter: CategoryEqualsFilter | None = None
    assumptions: tuple[str,...]=()
    limitations: tuple[str,...]=()
    execution_support: AnalysisExecutionSupport=AnalysisExecutionSupport.SUPPORTED

@dataclass(frozen=True)
class ComparisonResultRoleSelector:
    role: str; precursor_analysis_id: str; statistic_type: str; variable_id: str; group_variable_id: str; outcome_category: Any | None; group_category: Any | None; filter_definition: str

@dataclass(frozen=True)
class PlannedComparison:
    planned_comparison_id: str; specification: ComparisonSpecification; specification_fingerprint: str
    precursor_analysis_ids: tuple[str,...]; research_question_ids: tuple[str,...]
    analytical_requirement_ids: tuple[str,...]; expected_result_family: str
    assumptions: tuple[str,...]=(); limitations: tuple[str,...]=()
    result_role_selectors: tuple[ComparisonResultRoleSelector,...]=()
    objective_ids: tuple[str,...]=()
    obligation: str="MANDATORY"

@dataclass(frozen=True)
class AnalysisPlanCoverageDeclaration:
    requirement_id: str; status: AnalysisPlanCoverageStatus; rationale: str; explicit_multi_component: bool=False

@dataclass(frozen=True)
class AnalysisRequirementPlanCoverage:
    requirement_id: str; status: AnalysisPlanCoverageStatus; planned_analysis_ids: tuple[str,...]; rationale: str | None

@dataclass(frozen=True)
class QuantitativeAnalysisPlanCoverageManifest:
    manifest_id: str; project_id: str; plan_version_id: str; plan_content_fingerprint: str; research_design_fingerprint: str; questionnaire_fingerprint: str; reconciliation_fingerprint: str; requirements: tuple[AnalysisRequirementPlanCoverage,...]; fingerprint: str
    fingerprint_method_version: str=FINGERPRINT_METHOD_VERSION

@dataclass(frozen=True)
class QuantitativeAnalysisPlanVersion:
    plan_id: str; version_id: str; version_sequence: int; project_id: str; methodology: str
    research_design_version_id: str; research_design_fingerprint: str
    questionnaire_version_id: str; questionnaire_fingerprint: str; expected_measurement_schema_fingerprint: str
    reconciliation_version_id: str; reconciliation_fingerprint: str
    dataset_version_id: str; dataset_fingerprint: str; data_fingerprint: str; schema_fingerprint: str
    codebook_version_id: str; codebook_fingerprint: str
    planned_analyses: tuple[PlannedAnalysis,...]; planned_comparisons: tuple[PlannedComparison,...]
    coverage_manifest_id: str; coverage_manifest_fingerprint: str
    coverage_declarations: tuple[AnalysisPlanCoverageDeclaration,...]
    assumptions: tuple[str,...]; limitations: tuple[str,...]; parent_version_id: str | None
    lifecycle_status: AnalysisPlanLifecycle; approval_reference: str | None; fingerprint: str
    created_at: str; created_by: str; fingerprint_method_version: str=FINGERPRINT_METHOD_VERSION

@dataclass(frozen=True)
class QuantitativeAnalysisPlanApproval:
    approval_id: str; project_id: str; methodology: str; plan_version_id: str; plan_fingerprint: str
    research_design_fingerprint: str; questionnaire_fingerprint: str; reconciliation_fingerprint: str
    dataset_fingerprint: str; codebook_fingerprint: str; weight_set_fingerprints: tuple[str,...]
    coverage_manifest_fingerprint: str; actor_id: str; decided_at: str; decision: AnalysisPlanApprovalDecision; rationale: str; fingerprint: str

@dataclass(frozen=True)
class ApprovedAnalysisPlanProjection:
    plan_id: str; version_id: str; fingerprint: str; upstream_fingerprints: tuple[tuple[str,str],...]
    planned_analyses: tuple[tuple[str,str,str,tuple[str,...],tuple[str,...],tuple[tuple[str,str,str],...]],...]
    planned_comparisons: tuple[tuple[str,str,tuple[str,str]],...]
    coverage: tuple[tuple[str,str],...]; assumptions: tuple[str,...]; limitations: tuple[str,...]

@dataclass(frozen=True)
class AnalysisExecutionProjection:
    plan_id: str; plan_version_id: str; plan_fingerprint: str; quality_assessment_fingerprint: str; coverage_manifest_id: str; coverage_manifest_fingerprint: str; planned_analyses: tuple[PlannedAnalysis,...]; planned_comparisons: tuple[PlannedComparison,...]; specifications: tuple[AnalysisSpecification,...]; comparisons: tuple[ComparisonSpecification,...]; fingerprint: str

@dataclass(frozen=True)
class DatasetOnlyAnalysisPlanAuthority:
    authority_id: str; project_id: str; run_id: str; status: str; limitation: str; fingerprint: str
