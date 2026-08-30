from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum

EXECUTION_METHOD_VERSION="rd-1"
class QuantitativeAnalysisExecutionMode(StrEnum):
    DESIGN_AWARE_EXECUTION="DESIGN_AWARE_EXECUTION"
    DATASET_ONLY_EXPLORATORY_EXECUTION="DATASET_ONLY_EXPLORATORY_EXECUTION"
class AnalysisItemExecutionStatus(StrEnum):
    EXECUTED_WITH_RESULTS="EXECUTED_WITH_RESULTS"; EXECUTED_NO_VALID_RESULT="EXECUTED_NO_VALID_RESULT"; FAILED_EXECUTION="FAILED_EXECUTION"; BLOCKED_STALE_AUTHORITY="BLOCKED_STALE_AUTHORITY"; BLOCKED_PRECURSOR="BLOCKED_PRECURSOR"; SKIPPED_OPTIONAL="SKIPPED_OPTIONAL"
class AnalysisExecutionManifestStatus(StrEnum):
    IN_PROGRESS="IN_PROGRESS"; COMPLETED="COMPLETED"; COMPLETED_WITH_OPTIONAL_FAILURES="COMPLETED_WITH_OPTIONAL_FAILURES"; FAILED="FAILED"; BLOCKED="BLOCKED"
@dataclass(frozen=True)
class ExecutionArtifactReference:
    artifact_type:str; record_id:str; authority_id:str; authority_fingerprint:str
@dataclass(frozen=True)
class PlannedAnalysisExecutionOutcome:
    outcome_id:str; project_id:str; run_id:str; plan_version_id:str; plan_fingerprint:str; planned_analysis_id:str; specification_id:str; specification_fingerprint:str; objective_ids:tuple[str,...]; research_question_ids:tuple[str,...]; analytical_requirement_ids:tuple[str,...]; variable_fingerprints:tuple[tuple[str,str],...]; weight_set_fingerprint:str|None; status:AnalysisItemExecutionStatus; artifacts:tuple[ExecutionArtifactReference,...]; failure_category:str|None; limitations:tuple[str,...]; execution_identity:str; fingerprint:str
@dataclass(frozen=True)
class PlannedComparisonExecutionOutcome:
    outcome_id:str; project_id:str; run_id:str; plan_version_id:str; plan_fingerprint:str; planned_comparison_id:str; specification_id:str; specification_fingerprint:str; precursor_outcome_ids:tuple[str,...]; precursor_result_fingerprints:tuple[str,...]; objective_ids:tuple[str,...]; research_question_ids:tuple[str,...]; analytical_requirement_ids:tuple[str,...]; status:AnalysisItemExecutionStatus; artifacts:tuple[ExecutionArtifactReference,...]; failure_category:str|None; limitations:tuple[str,...]; execution_identity:str; fingerprint:str
@dataclass(frozen=True)
class AnalysisExecutionCoverageEntry:
    planned_item_id:str; item_kind:str; analytical_requirement_ids:tuple[str,...]; status:AnalysisItemExecutionStatus; outcome_id:str
@dataclass(frozen=True)
class AnalysisExecutionCoverageManifest:
    coverage_id:str; project_id:str; run_id:str; execution_manifest_id:str; plan_fingerprint:str|None; entries:tuple[AnalysisExecutionCoverageEntry,...]; fingerprint:str
@dataclass(frozen=True)
class QuantitativeAnalysisExecutionManifest:
    manifest_id:str; project_id:str; run_id:str; execution_mode:QuantitativeAnalysisExecutionMode; execution_method_version:str; plan_id:str|None; plan_version_id:str|None; plan_fingerprint:str|None; dataset_version_id:str; dataset_fingerprint:str; data_fingerprint:str; schema_fingerprint:str; codebook_version_id:str; codebook_fingerprint:str; quality_assessment_fingerprint:str; qc_approval_id:str; qc_approval_fingerprint:str; analysis_outcome_ids:tuple[str,...]; comparison_outcome_ids:tuple[str,...]; coverage_manifest_id:str; coverage_manifest_fingerprint:str; status:AnalysisExecutionManifestStatus; parent_manifest_id:str|None; sequence:int; limitations:tuple[str,...]; fingerprint:str; weighting_mode:str="WEIGHTED"; weighting_authority_fingerprint:str|None=None
@dataclass(frozen=True)
class QuantitativeExecutionLineageEntry:
    planned_analysis_id:str; specification_id:str; specification_fingerprint:str; objective_ids:tuple[str,...]; research_question_ids:tuple[str,...]; analytical_requirement_ids:tuple[str,...]; result_ids_and_fingerprints:tuple[tuple[str,str],...]; status:AnalysisItemExecutionStatus
@dataclass(frozen=True)
class QuantitativeExecutionLineageProjection:
    manifest_id:str; manifest_fingerprint:str; coverage_manifest_id:str; entries:tuple[QuantitativeExecutionLineageEntry,...]; complete_design_aware_result_set:bool
