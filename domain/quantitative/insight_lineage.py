from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

INSIGHT_LINEAGE_METHOD_VERSION = "rf-1"

class InsightCoverageStatus(StrEnum):
    INSIGHT_SUPPORTED = "INSIGHT_SUPPORTED"
    NO_INSIGHT_PROPOSED = "NO_INSIGHT_PROPOSED"
    PROPOSALS_REJECTED_UNSUPPORTED = "PROPOSALS_REJECTED_UNSUPPORTED"
    BLOCKED_NO_SUPPORTED_FINDING = "BLOCKED_NO_SUPPORTED_FINDING"
    INCOMPATIBLE_FINDING_CONTEXT = "INCOMPATIBLE_FINDING_CONTEXT"
    NOT_APPLICABLE = "NOT_APPLICABLE"

@dataclass(frozen=True)
class InsightFindingLineageBranch:
    rd_outcome_id: str
    rd_outcome_fingerprint: str
    planned_analysis_id: str | None
    planned_comparison_id: str | None
    objective_ids: tuple[str, ...]
    research_question_ids: tuple[str, ...]
    analytical_requirement_ids: tuple[str, ...]

@dataclass(frozen=True)
class DesignAwareInsightFindingSupportEntry:
    finding_id: str
    qh_validation_fingerprint: str
    safe_finding_projection: Mapping[str, Any]
    re_lineage_entry_fingerprint: str
    statistical_result_ids_and_fingerprints: tuple[tuple[str, str], ...]
    comparison_result_ids_and_fingerprints: tuple[tuple[str, str], ...]
    branches: tuple[InsightFindingLineageBranch, ...]
    limitations: tuple[str, ...]
    fingerprint: str

@dataclass(frozen=True)
class DesignAwareInsightInputAuthority:
    authority_id: str
    project_id: str
    run_id: str
    execution_mode: str
    finding_generation_record_id: str
    finding_generation_fingerprint: str
    re_lineage_manifest_id: str
    re_lineage_manifest_fingerprint: str
    re_input_authority_id: str
    re_input_authority_fingerprint: str
    re_coverage_id: str
    re_coverage_fingerprint: str
    rd_execution_manifest_id: str
    rd_execution_manifest_fingerprint: str
    rc_plan_id: str
    rc_plan_version_id: str
    rc_plan_fingerprint: str
    finding_entries: tuple[DesignAwareInsightFindingSupportEntry, ...]
    analytical_requirement_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    method_version: str
    fingerprint: str

@dataclass(frozen=True)
class InsightDesignLineageEntry:
    insight_id: str
    qj_validation_fingerprint: str
    supporting_finding_ids: tuple[str, ...]
    qh_validation_fingerprints: tuple[str, ...]
    re_lineage_entry_fingerprints: tuple[str, ...]
    branches_by_finding: tuple[tuple[str, tuple[InsightFindingLineageBranch, ...]], ...]
    common_analytical_requirement_ids: tuple[str, ...]
    common_research_question_ids: tuple[str, ...]
    common_scope_objective_ids: tuple[str, ...]
    fingerprint: str

@dataclass(frozen=True)
class InsightCoverageEntry:
    analytical_requirement_id: str
    status: InsightCoverageStatus
    insight_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    rationale: str

@dataclass(frozen=True)
class QuantitativeInsightCoverageManifest:
    coverage_id: str
    project_id: str
    run_id: str
    input_authority_id: str
    input_authority_fingerprint: str
    insight_generation_fingerprint: str
    entries: tuple[InsightCoverageEntry, ...]
    method_version: str
    fingerprint: str

@dataclass(frozen=True)
class QuantitativeInsightDesignLineageManifest:
    manifest_id: str
    project_id: str
    run_id: str
    insight_generation_record_id: str
    insight_generation_fingerprint: str
    input_authority_id: str
    input_authority_fingerprint: str
    re_lineage_manifest_id: str
    re_lineage_manifest_fingerprint: str
    re_coverage_id: str
    re_coverage_fingerprint: str
    rd_execution_manifest_id: str
    rd_execution_manifest_fingerprint: str
    rc_plan_id: str
    rc_plan_fingerprint: str
    coverage_manifest_id: str
    coverage_manifest_fingerprint: str
    entries: tuple[InsightDesignLineageEntry, ...]
    method_version: str
    fingerprint: str

@dataclass(frozen=True)
class DatasetOnlyInsightLineageAbsence:
    absence_id: str
    project_id: str
    run_id: str
    insight_generation_record_id: str
    insight_generation_fingerprint: str
    status: str
    fingerprint: str
