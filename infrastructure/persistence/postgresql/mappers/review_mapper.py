from __future__ import annotations

from datetime import datetime

from domain.reviews.review_result import ReviewResult

from infrastructure.persistence.postgresql.models.review_model import ReviewModel


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def review_to_model(review: ReviewResult, *, version: int) -> ReviewModel:
    return ReviewModel(
        id=review.id,
        project_id=review.project_id,
        workflow_run_id=review.workflow_run_id,
        research_design_id=review.research_design_id,
        report_id=review.report_id,
        artifact_id=review.artifact_id,
        previous_report_id=review.previous_report_id,
        review_attempt=review.review_attempt,
        verdict=review.verdict.value,
        quality_dimensions=[item.to_dict() for item in review.quality_dimensions],
        issues=[item.to_dict() for item in review.issues],
        summary=review.summary,
        review_method=review.review_method,
        created_at=_parse_datetime(review.created_at),
        deduplication_key=review.deduplication_key,
        metadata_json=dict(review.metadata),
        version=version,
    )


def review_from_model(model: ReviewModel) -> ReviewResult:
    return ReviewResult.from_dict(
        {
            "id": model.id,
            "project_id": model.project_id,
            "workflow_run_id": model.workflow_run_id,
            "research_design_id": model.research_design_id,
            "report_id": model.report_id,
            "artifact_id": model.artifact_id,
            "previous_report_id": model.previous_report_id,
            "review_attempt": model.review_attempt,
            "verdict": model.verdict,
            "quality_dimensions": model.quality_dimensions or [],
            "issues": model.issues or [],
            "summary": model.summary,
            "review_method": model.review_method,
            "created_at": model.created_at.isoformat(),
            "deduplication_key": model.deduplication_key,
            "metadata": dict(model.metadata_json or {}),
            "version": model.version,
        },
    )
