from __future__ import annotations

import concurrent.futures
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from domain.reports.report import Report
from domain.reports.report_section import ReportSection

from application.report.deduplication import (
    DR06_RESEARCH_REPORT_TYPE,
    compute_report_deduplication_key,
)
from application.report.exceptions import DuplicateReportError
from infrastructure.persistence.postgresql.repositories.postgresql_report_repository import (
    PostgreSQLReportRepository,
)
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


def _sample_report(
    *,
    project_id: str,
    run_id: str,
    dedup_key: str,
    title: str,
) -> Report:
    now = datetime.now(timezone.utc).isoformat()
    return Report(
        id=str(uuid4()),
        project_id=project_id,
        workflow_run_id=run_id,
        research_design_id="design-1",
        title=title,
        language="en",
        sections=(
            ReportSection(
                id=str(uuid4()),
                title="Section",
                content="Content with provenance.",
                finding_refs=("finding-1",),
                insight_refs=("insight-1",),
                evidence_refs=("evidence-1",),
                citation_ids=("S1",),
            ),
        ),
        executive_summary="Summary",
        limitations=(),
        created_at=now,
        generation_method="deterministic",
        finding_refs=("finding-1",),
        insight_refs=("insight-1",),
        evidence_refs=("evidence-1",),
        citation_registry={
            "S1": {
                "citation_id": "S1",
                "source_id": "source-1",
                "title": "Source",
                "canonical_url": "https://example.com",
                "published_at": None,
                "retrieved_at": now,
                "source_type": "web",
            },
        },
        deduplication_key=dedup_key,
    )


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLConcurrentReportRepositoryTests(PostgreSQLIntegrationTestCase):
    def test_concurrent_create_resolves_single_report_row(self) -> None:
        from domain.factories.project_factory import ProjectFactory
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )

        project = ProjectFactory().create("Concurrent Report Project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        repository = PostgreSQLReportRepository(self.session_factory)
        dedup_key = compute_report_deduplication_key(
            workflow_run_id="run-a",
            report_type=DR06_RESEARCH_REPORT_TYPE,
            generation_method="deterministic",
        )

        def attempt(title: str) -> str:
            report = _sample_report(
                project_id=project.id,
                run_id="run-a",
                dedup_key=dedup_key,
                title=title,
            )
            try:
                repository.create(report)
                return report.id
            except DuplicateReportError:
                existing = repository.get_by_deduplication_key("run-a", dedup_key)
                assert existing is not None
                return existing.id

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt, "First Title Attempt"),
                executor.submit(attempt, "Different Title On Retry"),
            ]
            ids = [future.result() for future in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(set(ids)), 1)
        stored = repository.get_by_id(ids[0])
        assert stored is not None
        self.assertEqual(stored.deduplication_key, dedup_key)
        self.assertEqual(
            len(repository.list_for_project(project.id, workflow_run_id="run-a")),
            1,
        )


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLConcurrentReportServiceTests(PostgreSQLIntegrationTestCase):
    def test_concurrent_write_for_context_resolves_single_report(self) -> None:
        from tests.integration.postgresql.dr06_fixtures import (
            build_report_service,
            seed_report_prerequisites,
        )

        project, context, _, _, _, _ = seed_report_prerequisites(
            self.session_factory,
            run_id="run-report-concurrent",
        )
        service = build_report_service(self.session_factory)

        def attempt() -> tuple[str, str]:
            summary = service.write_for_context(context)
            return summary.report_id, summary.artifact_id

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt), executor.submit(attempt)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]

        report_ids = {item[0] for item in results}
        artifact_ids = {item[1] for item in results}
        self.assertEqual(len(report_ids), 1)
        self.assertEqual(len(artifact_ids), 1)

        reports = service._report_repository.list_for_project(
            project.id,
            workflow_run_id=context.workflow_run.id,
        )
        artifacts = service._artifact_repository.list_for_run(context.workflow_run.id)
        self.assertEqual(len(reports), 1)
        self.assertEqual(len(artifacts), 1)
        self.assertTrue(reports[0].citation_registry)
        self.assertTrue(artifacts[0].content_checksum)


if __name__ == "__main__":
    unittest.main()
