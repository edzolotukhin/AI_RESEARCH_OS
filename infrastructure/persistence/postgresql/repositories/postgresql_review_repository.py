from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from application.ports.review_ports import ReviewRepository
from application.review.exceptions import DuplicateReviewError
from domain.reviews.review_result import ReviewResult

from infrastructure.persistence.postgresql.mappers.review_mapper import (
    review_from_model,
    review_to_model,
)
from infrastructure.persistence.postgresql.models.review_model import ReviewModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLReviewRepository(ReviewRepository):
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, review: ReviewResult) -> int:
        with self._session_factory.session() as session:
            try:
                session.add(review_to_model(review, version=1))
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateReviewError(
                    f"Review already exists for run/key: "
                    f"{review.workflow_run_id}/{review.deduplication_key}",
                ) from exc
            review.version = 1
            return 1

    def get_by_id(self, review_id: str) -> ReviewResult | None:
        with self._session_factory.session() as session:
            model = session.get(ReviewModel, review_id)
            if model is None:
                return None
            return review_from_model(model)

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> ReviewResult | None:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = select(ReviewModel).where(
                ReviewModel.workflow_run_id == workflow_run_id,
                ReviewModel.deduplication_key == deduplication_key,
            )
            model = session.scalars(statement).first()
            if model is None:
                return None
            return review_from_model(model)

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        report_id: str | None = None,
        verdict: str | None = None,
    ) -> list[ReviewResult]:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = (
                select(ReviewModel)
                .where(ReviewModel.project_id == project_id)
                .order_by(ReviewModel.created_at)
            )
            if workflow_run_id is not None:
                statement = statement.where(
                    ReviewModel.workflow_run_id == workflow_run_id,
                )
            if report_id is not None:
                statement = statement.where(ReviewModel.report_id == report_id)
            if verdict is not None:
                statement = statement.where(ReviewModel.verdict == verdict)
            models = session.scalars(statement).all()
        return [review_from_model(model) for model in models]

    def count_for_run(self, project_id: str, workflow_run_id: str) -> int:
        return len(
            self.list_for_project(project_id, workflow_run_id=workflow_run_id),
        )
