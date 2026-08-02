from __future__ import annotations

from domain.reviews.review_result import ReviewResult

from api.schemas.reviews import (
    QualityDimensionResponse,
    ReviewIssueResponse,
    ReviewResponse,
)


def review_to_response(review: ReviewResult) -> ReviewResponse:
    payload = review.to_dict()
    return ReviewResponse(
        id=payload["id"],
        project_id=payload["project_id"],
        workflow_run_id=payload["workflow_run_id"],
        research_design_id=payload["research_design_id"],
        report_id=payload["report_id"],
        artifact_id=payload.get("artifact_id"),
        previous_report_id=payload.get("previous_report_id"),
        review_attempt=payload["review_attempt"],
        verdict=payload["verdict"],
        quality_dimensions=[
            QualityDimensionResponse(**item)
            for item in payload.get("quality_dimensions", [])
        ],
        issues=[ReviewIssueResponse(**item) for item in payload.get("issues", [])],
        summary=payload["summary"],
        review_method=payload["review_method"],
        created_at=payload["created_at"],
    )
