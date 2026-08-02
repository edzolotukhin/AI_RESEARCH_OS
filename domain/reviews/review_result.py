from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.reviews.quality_dimension import QualityDimension
from domain.reviews.review_issue import ReviewIssue
from domain.reviews.review_verdict import ReviewVerdict


@dataclass
class ReviewResult:
    """Durable independent review of a generated report (DR-07)."""

    id: str
    project_id: str
    workflow_run_id: str
    research_design_id: str
    report_id: str
    review_attempt: int
    verdict: ReviewVerdict
    quality_dimensions: tuple[QualityDimension, ...]
    issues: tuple[ReviewIssue, ...]
    summary: str
    review_method: str
    created_at: str
    deduplication_key: str
    artifact_id: str | None = None
    previous_report_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "workflow_run_id": self.workflow_run_id,
            "research_design_id": self.research_design_id,
            "report_id": self.report_id,
            "artifact_id": self.artifact_id,
            "previous_report_id": self.previous_report_id,
            "review_attempt": self.review_attempt,
            "verdict": self.verdict.value,
            "quality_dimensions": [item.to_dict() for item in self.quality_dimensions],
            "issues": [item.to_dict() for item in self.issues],
            "summary": self.summary,
            "review_method": self.review_method,
            "created_at": self.created_at,
            "deduplication_key": self.deduplication_key,
            "metadata": dict(self.metadata),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReviewResult:
        return cls(
            id=str(payload["id"]),
            project_id=str(payload["project_id"]),
            workflow_run_id=str(payload["workflow_run_id"]),
            research_design_id=str(payload["research_design_id"]),
            report_id=str(payload["report_id"]),
            artifact_id=payload.get("artifact_id"),
            previous_report_id=payload.get("previous_report_id"),
            review_attempt=int(payload.get("review_attempt", 1)),
            verdict=ReviewVerdict(str(payload["verdict"])),
            quality_dimensions=tuple(
                QualityDimension.from_dict(item)
                for item in payload.get("quality_dimensions", [])
            ),
            issues=tuple(
                ReviewIssue.from_dict(item) for item in payload.get("issues", [])
            ),
            summary=str(payload.get("summary", "")),
            review_method=str(payload.get("review_method", "unknown")),
            created_at=str(payload.get("created_at", "")),
            deduplication_key=str(payload.get("deduplication_key", "")),
            metadata=dict(payload.get("metadata", {})),
            version=int(payload.get("version", 0)),
        )
