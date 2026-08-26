from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


FINDING_LINEAGE_METHOD_VERSION = "re-1"


class FindingCoverageStatus(StrEnum):
    FINDING_SUPPORTED = "FINDING_SUPPORTED"
    NO_FINDING_PROPOSED = "NO_FINDING_PROPOSED"
    PROPOSALS_REJECTED_UNSUPPORTED = "PROPOSALS_REJECTED_UNSUPPORTED"
    BLOCKED_NO_EXECUTED_RESULT = "BLOCKED_NO_EXECUTED_RESULT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class DesignAwareAnalysisSupportEntry:
    result_id: str
    result_fingerprint: str
    safe_numerical_projection: Mapping[str, Any]
    rd_outcome_id: str
    rd_outcome_fingerprint: str
    planned_analysis_id: str
    specification_id: str
    specification_fingerprint: str
    objective_ids: tuple[str, ...]
    research_question_ids: tuple[str, ...]
    analytical_requirement_ids: tuple[str, ...]
    obligation: str
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class DesignAwareComparisonSupportEntry:
    comparison_result_id: str
    comparison_result_fingerprint: str
    safe_comparison_projection: Mapping[str, Any]
    precursor_result_ids_and_fingerprints: tuple[tuple[str, str], ...]
    rd_outcome_id: str
    rd_outcome_fingerprint: str
    planned_comparison_id: str
    specification_id: str
    specification_fingerprint: str
    objective_ids: tuple[str, ...]
    research_question_ids: tuple[str, ...]
    analytical_requirement_ids: tuple[str, ...]
    obligation: str
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class DesignAwareFindingInputAuthority:
    authority_id: str
    project_id: str
    run_id: str
    rd_execution_manifest_id: str
    rd_execution_manifest_fingerprint: str
    rd_coverage_manifest_id: str
    rd_coverage_manifest_fingerprint: str
    rc_plan_id: str
    rc_plan_version_id: str
    rc_plan_fingerprint: str
    dataset_version_id: str
    dataset_fingerprint: str
    codebook_version_id: str
    codebook_fingerprint: str
    analysis_entries: tuple[DesignAwareAnalysisSupportEntry, ...]
    comparison_entries: tuple[DesignAwareComparisonSupportEntry, ...]
    analytical_requirement_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    method_version: str
    fingerprint: str


@dataclass(frozen=True)
class FindingDesignLineageEntry:
    finding_id: str
    qh_validation_fingerprint: str
    statistical_result_ids_and_fingerprints: tuple[tuple[str, str], ...]
    comparison_result_ids_and_fingerprints: tuple[tuple[str, str], ...]
    rd_outcome_ids_and_fingerprints: tuple[tuple[str, str], ...]
    planned_analysis_ids: tuple[str, ...]
    planned_comparison_ids: tuple[str, ...]
    objective_ids: tuple[str, ...]
    research_question_ids: tuple[str, ...]
    analytical_requirement_ids: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class FindingCoverageEntry:
    analytical_requirement_id: str
    status: FindingCoverageStatus
    finding_ids: tuple[str, ...]
    rd_outcome_ids: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class QuantitativeFindingCoverageManifest:
    coverage_id: str
    project_id: str
    run_id: str
    input_authority_id: str
    input_authority_fingerprint: str
    finding_generation_fingerprint: str
    entries: tuple[FindingCoverageEntry, ...]
    method_version: str
    fingerprint: str


@dataclass(frozen=True)
class QuantitativeFindingDesignLineageManifest:
    manifest_id: str
    project_id: str
    run_id: str
    finding_generation_record_id: str
    finding_generation_fingerprint: str
    input_authority_id: str
    input_authority_fingerprint: str
    rd_execution_manifest_id: str
    rd_execution_manifest_fingerprint: str
    rc_plan_id: str
    rc_plan_fingerprint: str
    coverage_manifest_id: str
    coverage_manifest_fingerprint: str
    entries: tuple[FindingDesignLineageEntry, ...]
    method_version: str
    fingerprint: str


@dataclass(frozen=True)
class DatasetOnlyFindingLineageAbsence:
    absence_id: str
    project_id: str
    run_id: str
    finding_generation_record_id: str
    finding_generation_fingerprint: str
    status: str
    fingerprint: str
