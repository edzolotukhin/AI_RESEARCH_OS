from __future__ import annotations

import copy

from domain.reviews.review_result import ReviewResult

from application.review.exceptions import DuplicateReviewError
from application.ports.review_ports import ReviewRepository


class InMemoryReviewRepository(ReviewRepository):
    def __init__(self) -> None:
        self._reviews: dict[str, ReviewResult] = {}
        self._dedup_index: dict[tuple[str, str], str] = {}
        self._project_index: dict[str, list[str]] = {}

    def create(self, review: ReviewResult) -> int:
        key = (review.workflow_run_id, review.deduplication_key)
        if key in self._dedup_index:
            raise DuplicateReviewError(
                f"Review already exists for run/key: {review.workflow_run_id}/{review.deduplication_key}",
            )
        self._reviews[review.id] = copy.deepcopy(review)
        self._dedup_index[key] = review.id
        project_items = self._project_index.setdefault(review.project_id, [])
        if review.id not in project_items:
            project_items.append(review.id)
        review.version = 1
        return 1

    def get_by_id(self, review_id: str) -> ReviewResult | None:
        review = self._reviews.get(review_id)
        return copy.deepcopy(review) if review is not None else None

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> ReviewResult | None:
        review_id = self._dedup_index.get((workflow_run_id, deduplication_key))
        if review_id is None:
            return None
        return self.get_by_id(review_id)

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        report_id: str | None = None,
        verdict: str | None = None,
    ) -> list[ReviewResult]:
        review_ids = self._project_index.get(project_id, [])
        reviews = [
            copy.deepcopy(self._reviews[review_id])
            for review_id in review_ids
            if review_id in self._reviews
        ]
        if workflow_run_id is not None:
            reviews = [
                item for item in reviews if item.workflow_run_id == workflow_run_id
            ]
        if report_id is not None:
            reviews = [item for item in reviews if item.report_id == report_id]
        if verdict is not None:
            reviews = [item for item in reviews if item.verdict.value == verdict]
        return reviews

    def count_for_run(self, project_id: str, workflow_run_id: str) -> int:
        return len(
            [
                item
                for item in self.list_for_project(project_id, workflow_run_id=workflow_run_id)
            ],
        )
