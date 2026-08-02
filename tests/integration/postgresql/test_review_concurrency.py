"""DR-07 review concurrency PostgreSQL tests."""

from __future__ import annotations

import concurrent.futures
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from domain.reviews.quality_dimension import QualityDimension, QualityDimensionName, QualityDimensionStatus
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict

from application.review.deduplication import compute_review_deduplication_key
from application.review.exceptions import DuplicateReviewError
from infrastructure.persistence.postgresql.repositories.postgresql_review_repository import (
    PostgreSQLReviewRepository,
)
from tests.integration.postgresql.dr07_fixtures import build_review_service, seed_review_prerequisites
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


def _sample_review(*, project_id: str, run_id: str, report_id: str, dedup_key: str) -> ReviewResult:
    return ReviewResult(
        id=str(uuid4()),
        project_id=project_id,
        workflow_run_id=run_id,
        research_design_id="design-dr06",
        report_id=report_id,
        review_attempt=1,
        verdict=ReviewVerdict.APPROVE,
        quality_dimensions=(
            QualityDimension(
                name=QualityDimensionName.BRIEF_COVERAGE,
                status=QualityDimensionStatus.PASS,
            ),
        ),
        issues=(),
        summary="Approved",
        review_method="deterministic",
        created_at=datetime.now(timezone.utc).isoformat(),
        deduplication_key=dedup_key,
    )


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLConcurrentReviewRepositoryTests(PostgreSQLIntegrationTestCase):
    def test_concurrent_create_resolves_single_review_row(self) -> None:
        project, context, _ = seed_review_prerequisites(
            self.session_factory,
            run_id="run-review-concurrent-repo",
        )
        report_id = build_review_service(self.session_factory)._report_repository.list_for_project(
            project.id,
            workflow_run_id=context.workflow_run.id,
        )[0].id
        repository = PostgreSQLReviewRepository(self.session_factory)
        dedup_key = compute_review_deduplication_key(
            workflow_run_id=context.workflow_run.id,
            report_id=report_id,
            review_attempt=1,
        )

        def attempt(summary: str) -> str:
            review = _sample_review(
                project_id=project.id,
                run_id=context.workflow_run.id,
                report_id=report_id,
                dedup_key=dedup_key,
            )
            review = replace(review, summary=summary, id=str(uuid4()))
            try:
                repository.create(review)
                return review.id
            except DuplicateReviewError:
                existing = repository.get_by_deduplication_key(
                    context.workflow_run.id,
                    dedup_key,
                )
                assert existing is not None
                return existing.id

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt, "First review attempt"),
                executor.submit(attempt, "Different summary on retry"),
            ]
            ids = [future.result() for future in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(set(ids)), 1)
        stored = repository.get_by_id(ids[0])
        assert stored is not None
        self.assertEqual(stored.deduplication_key, dedup_key)
        self.assertEqual(
            repository.count_for_run(project.id, context.workflow_run.id),
            1,
        )


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLConcurrentReviewServiceTests(PostgreSQLIntegrationTestCase):
    def test_concurrent_review_for_context_resolves_single_review(self) -> None:
        project, context, _ = seed_review_prerequisites(
            self.session_factory,
            run_id="run-review-concurrent-service",
        )
        service = build_review_service(self.session_factory)

        def attempt() -> str:
            summary = service.review_for_context(context)
            return summary.review_id

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt), executor.submit(attempt)]
            review_ids = [future.result() for future in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(set(review_ids)), 1)
        reviews = service._review_repository.list_for_project(
            project.id,
            workflow_run_id=context.workflow_run.id,
        )
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].verdict, ReviewVerdict.APPROVE)


if __name__ == "__main__":
    unittest.main()
