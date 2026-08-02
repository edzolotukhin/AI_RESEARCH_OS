"""DR-07 review crash-window and idempotent retry tests."""

from __future__ import annotations

import unittest

from application.ports.review_ports import ReviewRepository
from domain.reviews.review_result import ReviewResult

from tests.integration.postgresql.dr07_fixtures import build_review_service, seed_review_prerequisites
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase


class _FailAfterReviewCreate(ReviewRepository):
    """Simulate crash after review row is persisted (PF-04 service boundary)."""

    def __init__(self, delegate: ReviewRepository) -> None:
        self._delegate = delegate
        self._fail_next = True

    def create(self, review: ReviewResult) -> int:
        result = self._delegate.create(review)
        if self._fail_next:
            self._fail_next = False
            raise RuntimeError("simulated crash after review persisted")
        return result

    def get_by_id(self, review_id: str):
        return self._delegate.get_by_id(review_id)

    def get_by_deduplication_key(self, workflow_run_id: str, deduplication_key: str):
        return self._delegate.get_by_deduplication_key(workflow_run_id, deduplication_key)

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        report_id: str | None = None,
        verdict: str | None = None,
    ):
        return self._delegate.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
            report_id=report_id,
            verdict=verdict,
        )

    def count_for_run(self, project_id: str, workflow_run_id: str) -> int:
        return self._delegate.count_for_run(project_id, workflow_run_id)


class ReviewCrashRecoveryPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_review_persisted_before_checkpoint_retry_is_idempotent(self) -> None:
        """
        PF-04 behavior: ReviewResult row may exist before task checkpoint.
        Retry must reuse the durable review and complete finality without duplicates.
        """
        project, context, _ = seed_review_prerequisites(
            self.session_factory,
            run_id="run-review-crash-after-persist",
        )
        service = build_review_service(self.session_factory)
        base_repo = service._review_repository
        service._review_repository = _FailAfterReviewCreate(base_repo)

        with self.assertRaises(RuntimeError):
            service.review_for_context(context)

        reviews_after_crash = base_repo.list_for_project(
            project.id,
            workflow_run_id=context.workflow_run.id,
        )
        self.assertEqual(len(reviews_after_crash), 1)
        review_id_after_crash = reviews_after_crash[0].id

        artifacts_after_crash = service._artifact_repository.list_for_run(
            context.workflow_run.id,
        )
        self.assertEqual(len(artifacts_after_crash), 1)
        self.assertEqual(artifacts_after_crash[0].status, "draft")

        summary = service.review_for_context(context)
        self.assertEqual(summary.review_id, review_id_after_crash)

        reviews_after_retry = base_repo.list_for_project(
            project.id,
            workflow_run_id=context.workflow_run.id,
        )
        self.assertEqual(len(reviews_after_retry), 1)

        artifact = service._artifact_repository.get_by_id(summary.artifact_id)
        assert artifact is not None
        self.assertEqual(artifact.status, "approved")


if __name__ == "__main__":
    unittest.main()
