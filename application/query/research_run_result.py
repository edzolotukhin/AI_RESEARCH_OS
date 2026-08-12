"""Bounded Research run result read projection (P1-18.1).

ResearchRunResult is a composition-only view over canonical persisted entities.
It is never persisted and must not become a second source of truth.

Product outcome enum is named ResearchRunOutcome to avoid colliding with the
domain ResearchOutcome (ready_for_analysis | insufficient_research).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResearchRunOutcome(str, Enum):
    """Projected product outcome for a terminal Research run."""

    APPROVED = "APPROVED"
    NOT_READY = "NOT_READY"
    QUALITY_REJECTED = "QUALITY_REJECTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class ResearchRunResultProjectionError(ValueError):
    """Fail-closed when canonical state cannot be projected safely."""


@dataclass(frozen=True)
class ReadinessProjection:
    ready_for_analysis: bool | None
    research_outcome: str | None
    termination_reason: str | None
    blocking_information_need_ids: tuple[str, ...]
    blocking_research_question_ids: tuple[str, ...]
    targeted_research_required: bool | None
    available: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "ready_for_analysis": self.ready_for_analysis,
            "research_outcome": self.research_outcome,
            "termination_reason": self.termination_reason,
            "blocking_information_need_ids": list(self.blocking_information_need_ids),
            "blocking_research_question_ids": list(
                self.blocking_research_question_ids,
            ),
            "targeted_research_required": self.targeted_research_required,
        }


@dataclass(frozen=True)
class BudgetUsageProjection:
    available: bool
    partial: bool
    total_llm_calls: int | None = None
    estimated_cost_usd: float | None = None
    budget_exhausted: bool | None = None
    exhaustion_stage: str | None = None
    exhaustion_reason: str | None = None
    stages: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "partial": self.partial,
            "total_llm_calls": self.total_llm_calls,
            "estimated_cost_usd": self.estimated_cost_usd,
            "budget_exhausted": self.budget_exhausted,
            "exhaustion_stage": self.exhaustion_stage,
            "exhaustion_reason": self.exhaustion_reason,
            "stages": dict(self.stages),
        }


@dataclass(frozen=True)
class EntityRefItem:
    id: str
    statement: str | None = None
    source_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id}
        if self.statement is not None:
            payload["statement"] = self.statement
        if self.source_id is not None:
            payload["source_id"] = self.source_id
        return payload


@dataclass(frozen=True)
class CollectionSummary:
    count: int
    ids: tuple[str, ...]
    items: tuple[EntityRefItem, ...] = ()
    acquired_count: int | None = None
    failed_count: int | None = None
    truncated_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "count": self.count,
            "ids": list(self.ids),
            "items": [item.to_dict() for item in self.items],
        }
        if self.acquired_count is not None:
            payload["acquired_count"] = self.acquired_count
        if self.failed_count is not None:
            payload["failed_count"] = self.failed_count
        if self.truncated_count is not None:
            payload["truncated_count"] = self.truncated_count
        return payload


@dataclass(frozen=True)
class ReportProjection:
    id: str
    revision_number: int
    previous_report_id: str | None
    title: str
    section_count: int
    finding_ref_count: int
    insight_ref_count: int
    evidence_ref_count: int
    limitations: tuple[str, ...]
    executive_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "revision_number": self.revision_number,
            "previous_report_id": self.previous_report_id,
            "title": self.title,
            "section_count": self.section_count,
            "finding_ref_count": self.finding_ref_count,
            "insight_ref_count": self.insight_ref_count,
            "evidence_ref_count": self.evidence_ref_count,
            "limitations": list(self.limitations),
            "executive_summary": self.executive_summary,
        }


@dataclass(frozen=True)
class ReviewProjection:
    id: str
    report_id: str
    review_attempt: int
    verdict: str
    issue_count: int
    major_issue_count: int
    minor_issue_count: int
    summary: str
    artifact_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "report_id": self.report_id,
            "review_attempt": self.review_attempt,
            "verdict": self.verdict,
            "issue_count": self.issue_count,
            "major_issue_count": self.major_issue_count,
            "minor_issue_count": self.minor_issue_count,
            "summary": self.summary,
            "artifact_id": self.artifact_id,
        }


@dataclass(frozen=True)
class ArtifactStatusProjection:
    count: int
    approved_count: int
    rejected_count: int
    draft_count: int
    approved_artifact_id: str | None
    approved_report_id: str | None
    statuses: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "approved_count": self.approved_count,
            "rejected_count": self.rejected_count,
            "draft_count": self.draft_count,
            "approved_artifact_id": self.approved_artifact_id,
            "approved_report_id": self.approved_report_id,
            "statuses": list(self.statuses),
        }


@dataclass(frozen=True)
class ProvenanceLink:
    finding_id: str | None
    insight_id: str | None
    evidence_id: str
    source_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "insight_id": self.insight_id,
            "evidence_id": self.evidence_id,
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class ProvenanceSummary:
    report_id: str | None
    finding_ids: tuple[str, ...]
    insight_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    links: tuple[ProvenanceLink, ...]
    unresolved_refs: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "finding_ids": list(self.finding_ids),
            "insight_ids": list(self.insight_ids),
            "evidence_ids": list(self.evidence_ids),
            "source_ids": list(self.source_ids),
            "links": [link.to_dict() for link in self.links],
            "unresolved_refs": list(self.unresolved_refs),
        }


@dataclass(frozen=True)
class ResearchRunResult:
    """Coherent inspectable projection of one terminal Research run."""

    run_id: str
    project_id: str
    workflow_status: str
    outcome: ResearchRunOutcome
    readiness: ReadinessProjection
    termination_reason: str | None
    limitations: tuple[str, ...]
    budget_usage: BudgetUsageProjection
    source_summary: CollectionSummary
    evidence_summary: CollectionSummary
    finding_summary: CollectionSummary
    insight_summary: CollectionSummary
    latest_report: ReportProjection | None
    latest_review: ReviewProjection | None
    artifact_status: ArtifactStatusProjection
    provenance_summary: ProvenanceSummary
    correlation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "correlation_id": self.correlation_id,
            "workflow_status": self.workflow_status,
            "outcome": self.outcome.value,
            "readiness": self.readiness.to_dict(),
            "termination_reason": self.termination_reason,
            "limitations": list(self.limitations),
            "budget_usage": self.budget_usage.to_dict(),
            "source_summary": self.source_summary.to_dict(),
            "evidence_summary": self.evidence_summary.to_dict(),
            "finding_summary": self.finding_summary.to_dict(),
            "insight_summary": self.insight_summary.to_dict(),
            "latest_report": (
                self.latest_report.to_dict() if self.latest_report is not None else None
            ),
            "latest_review": (
                self.latest_review.to_dict() if self.latest_review is not None else None
            ),
            "artifact_status": self.artifact_status.to_dict(),
            "provenance_summary": self.provenance_summary.to_dict(),
        }
