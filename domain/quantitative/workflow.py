from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class QuantitativeApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class QuantitativeTerminalOutcome(StrEnum):
    COMPLETED = "COMPLETED"
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
