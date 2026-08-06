from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from application.analysis.exceptions import InvalidAnalysisProvenanceError


REJECTION_CATEGORY_INVALID_EVIDENCE_REF = "invalid_evidence_ref"
REJECTION_CATEGORY_CROSS_RUN_REF = "cross_run_ref"
REJECTION_CATEGORY_CROSS_DESIGN_REF = "cross_design_ref"
REJECTION_CATEGORY_CROSS_PROJECT_REF = "cross_project_ref"
REJECTION_CATEGORY_MISSING_SUPPORT = "missing_support"
REJECTION_CATEGORY_INVALID_CONFIDENCE = "invalid_confidence"
REJECTION_CATEGORY_MISSING_STATEMENT = "missing_statement"
REJECTION_CATEGORY_PROVENANCE = "provenance_rejection"

FAILURE_CATEGORY_LLM_ERROR = "llm_error"
FAILURE_CATEGORY_PARSE_ERROR = "parse_error"
FAILURE_CATEGORY_BATCH_ERROR = "batch_error"
FAILURE_CATEGORY_BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass
class AnalysisBatchDiagnostics:
    batch_question_id: str | None
    evidence_count: int
    candidate_count: int = 0
    valid_count: int = 0
    rejected_count: int = 0
    engine_dropped_count: int = 0
    failure_category: str | None = None
    rejection_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_question_id": self.batch_question_id,
            "evidence_count": self.evidence_count,
            "candidate_count": self.candidate_count,
            "valid_count": self.valid_count,
            "rejected_count": self.rejected_count,
            "engine_dropped_count": self.engine_dropped_count,
            "failure_category": self.failure_category,
            "rejection_counts": dict(self.rejection_counts),
        }


@dataclass
class AnalysisFailureDiagnostics:
    workflow_run_id: str
    evidence_count: int
    batch_count: int
    batch_failures: int
    finding_candidates_rejected: int
    batches: list[AnalysisBatchDiagnostics] = field(default_factory=list)

    @property
    def total_candidates(self) -> int:
        return sum(batch.candidate_count for batch in self.batches)

    @property
    def total_valid(self) -> int:
        return sum(batch.valid_count for batch in self.batches)

    @property
    def total_rejected(self) -> int:
        return sum(batch.rejected_count for batch in self.batches)

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
            "evidence_count": self.evidence_count,
            "batch_count": self.batch_count,
            "batch_failures": self.batch_failures,
            "finding_candidates_rejected": self.finding_candidates_rejected,
            "total_candidates": self.total_candidates,
            "total_valid": self.total_valid,
            "total_rejected": self.total_rejected,
            "total_engine_dropped": self.total_engine_dropped,
            "rejection_summary": self.rejection_summary,
            "failure_category_summary": self.failure_category_summary,
            "batches": [batch.to_dict() for batch in self.batches],
        }


def classify_provenance_rejection(error: InvalidAnalysisProvenanceError) -> str:
    category = getattr(error, "category", None)
    if category:
        return str(category)

    message = str(error).lower()
    if "unknown evidence" in message:
        return REJECTION_CATEGORY_INVALID_EVIDENCE_REF
    if "different workflow run" in message:
        return REJECTION_CATEGORY_CROSS_RUN_REF
    if "different research design" in message:
        return REJECTION_CATEGORY_CROSS_DESIGN_REF
    if "different project" in message:
        return REJECTION_CATEGORY_CROSS_PROJECT_REF
    if "must reference at least one evidence" in message:
        return REJECTION_CATEGORY_MISSING_SUPPORT
    if "confidence" in message:
        return REJECTION_CATEGORY_INVALID_CONFIDENCE
    if "statement must not be empty" in message:
        return REJECTION_CATEGORY_MISSING_STATEMENT
    return REJECTION_CATEGORY_PROVENANCE


def format_zero_findings_message(diagnostics: AnalysisFailureDiagnostics) -> str:
    summary = diagnostics.to_dict()
    return (
        f"No valid findings produced for workflow run {diagnostics.workflow_run_id}; "
        f"evidence_count={summary['evidence_count']} "
        f"batch_count={summary['batch_count']} "
        f"batch_failures={summary['batch_failures']} "
        f"total_candidates={summary['total_candidates']} "
        f"total_valid={summary['total_valid']} "
        f"total_rejected={summary['total_rejected']} "
        f"total_engine_dropped={summary['total_engine_dropped']} "
        f"rejection_summary={summary['rejection_summary']} "
        f"failure_category_summary={summary['failure_category_summary']}"
    )
