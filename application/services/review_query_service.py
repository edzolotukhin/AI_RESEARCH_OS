from __future__ import annotations

from application.persistence.exceptions import EntityNotFoundError
from application.ports.review_ports import ReviewRepository
from domain.reviews.review_result import ReviewResult


class ReviewQueryService:
    """Read-only review query service."""

    def __init__(self, *, review_repository: ReviewRepository) -> None:
        self._review_repository = review_repository

    def get_review(self, review_id: str) -> ReviewResult:
        review = self._review_repository.get_by_id(review_id)
        if review is None:
            raise EntityNotFoundError(f"Review not found: {review_id}")
        return review

    def list_reviews_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        report_id: str | None = None,
        verdict: str | None = None,
    ) -> list[ReviewResult]:
        return self._review_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
            report_id=report_id,
            verdict=verdict,
        )

    def count_for_run(self, project_id: str, workflow_run_id: str) -> int:
        return self._review_repository.count_for_run(project_id, workflow_run_id)

    def final_verdict_for_run(
        self,
        project_id: str,
        workflow_run_id: str,
    ) -> str | None:
        reviews = self.list_reviews_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        if not reviews:
            return None
        return reviews[-1].verdict.value
