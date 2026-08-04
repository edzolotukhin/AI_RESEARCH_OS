from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from application.report.exceptions import InvalidReportProvenanceError

REJECTION_CATEGORY_INVALID_FINDING_REF = "invalid_finding_ref"
REJECTION_CATEGORY_INVALID_INSIGHT_REF = "invalid_insight_ref"
REJECTION_CATEGORY_INVALID_EVIDENCE_REF = "invalid_evidence_ref"
REJECTION_CATEGORY_CROSS_RUN_REF = "cross_run_ref"
REJECTION_CATEGORY_CROSS_PROJECT_REF = "cross_project_ref"
REJECTION_CATEGORY_CROSS_DESIGN_REF = "cross_design_ref"
REJECTION_CATEGORY_MISSING_TITLE = "missing_title"
REJECTION_CATEGORY_MISSING_CONTENT = "missing_content"
REJECTION_CATEGORY_EMPTY_SUPPORT = "empty_support"
REJECTION_CATEGORY_DUPLICATE_SECTION = "duplicate_section"
REJECTION_CATEGORY_PROVENANCE = "provenance_rejection"

FAILURE_CATEGORY_PARSE_ERROR = "parse_error"
FAILURE_CATEGORY_LLM_ERROR = "llm_error"
FAILURE_CATEGORY_TRUNCATED_OUTPUT = "truncated_output"
FAILURE_CATEGORY_BATCH_ERROR = "batch_error"


@dataclass
class ReportBatchDiagnostics:
    batch_question_id: str | None
    input_finding_count: int
    input_insight_count: int
    candidate_section_count: int = 0
    valid_section_count: int = 0
    rejected_section_count: int = 0
    engine_dropped_count: int = 0
    failure_category: str | None = None
    parse_failure_category: str | None = None
    rejection_counts: dict[str, int] = field(default_factory=dict)
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    visible_output_length: int | None = None
    finish_reason: str | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_question_id": self.batch_question_id,
            "input_finding_count": self.input_finding_count,
            "input_insight_count": self.input_insight_count,
            "candidate_section_count": self.candidate_section_count,
            "valid_section_count": self.valid_section_count,
            "rejected_section_count": self.rejected_section_count,
            "engine_dropped_count": self.engine_dropped_count,
            "failure_category": self.failure_category,
            "parse_failure_category": self.parse_failure_category,
            "rejection_counts": dict(self.rejection_counts),
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "visible_output_length": self.visible_output_length,
            "finish_reason": self.finish_reason,
            "max_output_tokens": self.max_output_tokens,
            "reasoning_effort": self.reasoning_effort,
        }


@dataclass
class ReportFailureDiagnostics:
    workflow_run_id: str
    finding_count: int
    insight_count: int
    batch_count: int
    batch_failures: int
    sections_rejected: int
    batches: list[ReportBatchDiagnostics] = field(default_factory=list)

    @property
    def total_candidates(self) -> int:
        return sum(batch.candidate_section_count for batch in self.batches)

    @property
    def total_valid(self) -> int:
        return sum(batch.valid_section_count for batch in self.batches)

    @property
    def total_rejected(self) -> int:
        return sum(batch.rejected_section_count for batch in self.batches)

    @property
    def total_engine_dropped(self) -> int:
        return sum(batch.engine_dropped_count for batch in self.batches)

    @property
    def rejection_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for batch in self.batches:
            for category, count in batch.rejection_counts.items():
                summary[category] = summary.get(category, 0) + count
        return summary

    @property
    def failure_category_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for batch in self.batches:
            if batch.failure_category:
                summary[batch.failure_category] = (
                    summary.get(batch.failure_category, 0) + 1
                )
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_run_id": self.workflow_run_id,
            "finding_count": self.finding_count,
            "insight_count": self.insight_count,
            "batch_count": self.batch_count,
            "batch_failures": self.batch_failures,
            "sections_rejected": self.sections_rejected,
            "total_candidates": self.total_candidates,
            "total_valid": self.total_valid,
            "total_rejected": self.total_rejected,
            "total_engine_dropped": self.total_engine_dropped,
            "rejection_summary": self.rejection_summary,
            "failure_category_summary": self.failure_category_summary,
            "batches": [batch.to_dict() for batch in self.batches],
        }


def classify_provenance_rejection(error: InvalidReportProvenanceError) -> str:
    category = getattr(error, "category", None)
    if category:
        return str(category)

    message = str(error).lower()
    if "unknown finding" in message:
        return REJECTION_CATEGORY_INVALID_FINDING_REF
    if "unknown insight" in message:
        return REJECTION_CATEGORY_INVALID_INSIGHT_REF
    if "unknown evidence" in message:
        return REJECTION_CATEGORY_INVALID_EVIDENCE_REF
    if "different workflow run" in message:
        return REJECTION_CATEGORY_CROSS_RUN_REF
    if "different research design" in message:
        return REJECTION_CATEGORY_CROSS_DESIGN_REF
    if "different project" in message:
        return REJECTION_CATEGORY_CROSS_PROJECT_REF
    if "title must not be empty" in message:
        return REJECTION_CATEGORY_MISSING_TITLE
    if "content must not be empty" in message:
        return REJECTION_CATEGORY_MISSING_CONTENT
    if "must reference at least one finding or insight" in message:
        return REJECTION_CATEGORY_EMPTY_SUPPORT
    return REJECTION_CATEGORY_PROVENANCE


def format_zero_sections_message(diagnostics: ReportFailureDiagnostics) -> str:
    summary = diagnostics.to_dict()
    return (
        f"No valid report sections produced for workflow run {diagnostics.workflow_run_id}; "
        f"finding_count={summary['finding_count']} "
        f"insight_count={summary['insight_count']} "
        f"batch_count={summary['batch_count']} "
        f"batch_failures={summary['batch_failures']} "
        f"total_candidates={summary['total_candidates']} "
        f"total_valid={summary['total_valid']} "
        f"total_rejected={summary['total_rejected']} "
        f"total_engine_dropped={summary['total_engine_dropped']} "
        f"rejection_summary={summary['rejection_summary']} "
        f"failure_category_summary={summary['failure_category_summary']}"
    )
