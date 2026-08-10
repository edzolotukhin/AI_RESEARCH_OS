"""Shared DR-07 PostgreSQL integration fixtures."""

from __future__ import annotations

from infrastructure.persistence.postgresql.session import DatabaseSessionFactory

from tests.integration.postgresql.dr06_fixtures import seed_report_prerequisites


def build_review_service(session_factory: DatabaseSessionFactory):
    from application.report.report_service import ReportService
    from infrastructure.persistence.postgresql.repositories.postgresql_artifact_repository import (
        PostgreSQLArtifactRepository,
    )
    from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import (
        PostgreSQLEvidenceRepository,
    )
    from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import (
        PostgreSQLFindingRepository,
    )
    from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import (
        PostgreSQLInsightRepository,
    )
    from infrastructure.persistence.postgresql.repositories.postgresql_report_repository import (
        PostgreSQLReportRepository,
    )
    from infrastructure.persistence.postgresql.repositories.postgresql_review_repository import (
        PostgreSQLReviewRepository,
    )
    from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import (
        PostgreSQLSourceRepository,
    )
    from infrastructure.report.deterministic_report_engine import DeterministicReportEngine
    from infrastructure.review.deterministic_review_engine import DeterministicReviewEngine

    report_service = ReportService(
        report_engine=DeterministicReportEngine(),
        finding_repository=PostgreSQLFindingRepository(session_factory),
        insight_repository=PostgreSQLInsightRepository(session_factory),
        evidence_repository=PostgreSQLEvidenceRepository(session_factory),
        source_repository=PostgreSQLSourceRepository(session_factory),
        report_repository=PostgreSQLReportRepository(session_factory),
        artifact_repository=PostgreSQLArtifactRepository(session_factory),
        max_findings_per_batch=10,
        max_chars_per_batch=12000,
    )
    from application.review.review_service import ReviewService

    return ReviewService(
        semantic_review_engine=DeterministicReviewEngine(),
        finding_repository=PostgreSQLFindingRepository(session_factory),
        insight_repository=PostgreSQLInsightRepository(session_factory),
        evidence_repository=PostgreSQLEvidenceRepository(session_factory),
        report_repository=PostgreSQLReportRepository(session_factory),
        artifact_repository=PostgreSQLArtifactRepository(session_factory),
        review_repository=PostgreSQLReviewRepository(session_factory),
        report_service=report_service,
        max_revision_attempts=1,
        max_chars_per_section=8000,
    )


def seed_review_prerequisites(
    session_factory: DatabaseSessionFactory,
    *,
    run_id: str | None = None,
):
    """Seed report prerequisites and write an initial draft report + artifact."""
    project, context, *_ = seed_report_prerequisites(
        session_factory,
        run_id=run_id,
    )
    report_service = build_review_service(session_factory)._report_service
    report_service.write_for_context(context)
    return project, context, report_service
