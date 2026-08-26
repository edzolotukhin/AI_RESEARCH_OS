from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from domain.quantitative.insight_lineage import InsightFindingLineageBranch


REPORT_LINEAGE_METHOD_VERSION = "rg-1"
REPORT_COMPOSITION_CONTRACT_VERSION = "QK_REPORT_COMPOSITION_V2"


class ReportCoverageStatus(StrEnum):
    REPORT_COVERED = "REPORT_COVERED"
    SUPPORTED_CONTENT_NOT_REPORTED = "SUPPORTED_CONTENT_NOT_REPORTED"
    NO_SUPPORTED_CONTENT = "NO_SUPPORTED_CONTENT"
    REPORT_PROPOSAL_REJECTED = "REPORT_PROPOSAL_REJECTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class DesignAwareReportFindingSupportEntry:
    finding_id: str
    qh_validation_fingerprint: str
    safe_finding_projection: Mapping[str, Any]
    re_lineage_entry_fingerprint: str
    branches: tuple[InsightFindingLineageBranch, ...]
    limitations: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class DesignAwareReportInsightSupportEntry:
    insight_id: str
    qj_validation_fingerprint: str
    safe_insight_projection: Mapping[str, Any]
    rf_lineage_entry_fingerprint: str
    supporting_finding_ids: tuple[str, ...]
    branches_by_finding: tuple[tuple[str, tuple[InsightFindingLineageBranch, ...]], ...]
    common_analytical_requirement_ids: tuple[str, ...]
    common_research_question_ids: tuple[str, ...]
    common_scope_objective_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class DesignAwareReportInputAuthority:
    authority_id: str
    project_id: str
    run_id: str
    execution_mode: str
    finding_generation_record_id: str
    finding_generation_fingerprint: str
    insight_generation_record_id: str
    insight_generation_fingerprint: str
    re_input_authority_id: str
    re_input_authority_fingerprint: str
    re_lineage_manifest_id: str
    re_lineage_manifest_fingerprint: str
    re_coverage_id: str
    re_coverage_fingerprint: str
    rf_input_authority_id: str
    rf_input_authority_fingerprint: str
    rf_lineage_manifest_id: str
    rf_lineage_manifest_fingerprint: str
    rf_coverage_id: str
    rf_coverage_fingerprint: str
    rd_execution_manifest_id: str
    rd_execution_manifest_fingerprint: str
    rc_plan_id: str
    rc_plan_version_id: str
    rc_plan_fingerprint: str
    dataset_version_id: str
    dataset_fingerprint: str
    codebook_version_id: str
    codebook_fingerprint: str
    finding_entries: tuple[DesignAwareReportFindingSupportEntry, ...]
    insight_entries: tuple[DesignAwareReportInsightSupportEntry, ...]
    analytical_requirement_ids: tuple[str, ...]
    deliverable_constraints: tuple[tuple[str, str, str], ...]
    limitations: tuple[str, ...]
    contract_version: str
    method_version: str
    fingerprint: str


@dataclass(frozen=True)
class ReportSectionEffectiveSupportBranch:
    support_kind: str
    support_id: str
    finding_id: str
    branch: InsightFindingLineageBranch


@dataclass(frozen=True)
class ReportSectionDesignLineageEntry:
    section_id: str
    section_support_fingerprint: str
    finding_ids_and_fingerprints: tuple[tuple[str, str], ...]
    insight_ids_and_fingerprints: tuple[tuple[str, str], ...]
    re_lineage_entry_fingerprints: tuple[str, ...]
    rf_lineage_entry_fingerprints: tuple[str, ...]
    effective_support_branches: tuple[ReportSectionEffectiveSupportBranch, ...]
    common_analytical_requirement_ids: tuple[str, ...]
    common_research_question_ids: tuple[str, ...]
    common_scope_objective_ids: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class ReportCoverageEntry:
    analytical_requirement_id: str
    status: ReportCoverageStatus
    section_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    insight_ids: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class QuantitativeReportCoverageManifest:
    coverage_id: str
    project_id: str
    run_id: str
    input_authority_id: str
    input_authority_fingerprint: str
    report_composition_record_id: str
    report_composition_fingerprint: str
    entries: tuple[ReportCoverageEntry, ...]
    method_version: str
    fingerprint: str


@dataclass(frozen=True)
class QuantitativeReportDesignLineageManifest:
    manifest_id: str
    project_id: str
    run_id: str
    report_composition_record_id: str
    report_composition_fingerprint: str
    report_id: str
    qk_validation_fingerprint: str
    input_authority_id: str
    input_authority_fingerprint: str
    re_lineage_manifest_id: str
    re_lineage_manifest_fingerprint: str
    re_coverage_id: str
    re_coverage_fingerprint: str
    rf_lineage_manifest_id: str
    rf_lineage_manifest_fingerprint: str
    rf_coverage_id: str
    rf_coverage_fingerprint: str
    rd_execution_manifest_id: str
    rd_execution_manifest_fingerprint: str
    rc_plan_id: str
    rc_plan_fingerprint: str
    coverage_manifest_id: str
    coverage_manifest_fingerprint: str
    entries: tuple[ReportSectionDesignLineageEntry, ...]
    method_version: str
    fingerprint: str


@dataclass(frozen=True)
class DatasetOnlyReportLineageAbsence:
    absence_id: str
    project_id: str
    run_id: str
    report_composition_record_id: str
    report_composition_fingerprint: str
    status: str
    fingerprint: str
