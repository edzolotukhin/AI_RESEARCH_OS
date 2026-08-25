from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class QuantitativeApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class QuantitativeTerminalOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_NO_SUPPORTED_FINDINGS = "COMPLETED_WITH_NO_SUPPORTED_FINDINGS"
    COMPLETED_WITH_NO_SUPPORTED_INSIGHTS = "COMPLETED_WITH_NO_SUPPORTED_INSIGHTS"
    COMPLETED_WITH_NO_SUPPORTED_REPORT = "COMPLETED_WITH_NO_SUPPORTED_REPORT"
    FAILED = "FAILED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"


@dataclass(frozen=True)
class QuantitativeAnalysisManifest:
    manifest_id: str
    dataset_version_id: str
    statistical_result_record_ids: tuple[str, ...]
    table_record_ids: tuple[str, ...]
    comparison_record_ids: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class QuantitativeApproval:
    approval_id: str
    project_id: str
    run_id: str
    subject_type: str
    subject_id: str
    subject_fingerprint: str
    decision: QuantitativeApprovalDecision
    actor_id: str
    decided_at: str
    rationale: str
    current: bool
    fingerprint: str


@dataclass(frozen=True)
class QuantitativeTerminalResult:
    result_id: str
    project_id: str
    run_id: str
    methodology: str
    dataset_version_id: str
    dataset_fingerprint: str
    qc_status: str
    cleaning_lineage: tuple[str, ...]
    weight_set_id: str
    weight_set_fingerprint: str
    weight_approval_id: str
    statistical_result_ids: tuple[str, ...]
    accepted_finding_count: int
    rejected_finding_count: int
    accepted_insight_count: int
    rejected_insight_count: int
    report_id: str
    report_status: str
    limitations: tuple[str, ...]
    execution_status: str
    terminal_outcome: QuantitativeTerminalOutcome
    fingerprint: str
@dataclass(frozen=True)
class QuantitativeStudyProjection:
    study_id: str
    project_id: str
    run_id: str
    title: str
    description: str
    state: str
    dataset_record_id: str | None = None
    codebook_record_id: str | None = None
    qc_record_id: str | None = None
    qc_approval_id: str | None = None
    target_plan_record_id: str | None = None
    weight_set_record_id: str | None = None
    weight_approval_id: str | None = None
    terminal_result_record_id: str | None = None
    revision: int = 0
    fingerprint: str = ""


@dataclass(frozen=True)
class QuantitativeRunRearmEvent:
    event_id: str
    project_id: str
    run_id: str
    actor_id: str
    previous_status: str
    previous_version: int
    previous_task_statuses: tuple[tuple[str, str], ...]
    previous_task_results_fingerprint: str
    reason: str
    rearmed_at: str
    fingerprint: str
