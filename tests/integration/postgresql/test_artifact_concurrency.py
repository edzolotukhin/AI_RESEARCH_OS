from __future__ import annotations

import concurrent.futures
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from application.persistence.records import ArtifactRecord
from application.report.deduplication import (
    DR06_RESEARCH_REPORT_TYPE,
    compute_artifact_deduplication_key,
    compute_content_checksum,
)
from application.report.exceptions import DuplicateArtifactError
from infrastructure.persistence.postgresql.repositories.postgresql_artifact_repository import (
    PostgreSQLArtifactRepository,
)
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


def _sample_artifact(
    *,
    project_id: str,
    run_id: str,
    dedup_key: str,
    title: str,
    filename: str,
    report_id: str,
) -> ArtifactRecord:
    content = f"# {title}\n\nDeterministic body."
    return ArtifactRecord(
        id=str(uuid4()),
        project_id=project_id,
        artifact_type=DR06_RESEARCH_REPORT_TYPE,
        title=title,
        content=content,
        run_id=run_id,
        status="Generated",
        media_type="text/markdown",
        filename=filename,
        content_checksum=compute_content_checksum(content),
        deduplication_key=dedup_key,
        report_id=report_id,
    )


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLConcurrentArtifactRepositoryTests(PostgreSQLIntegrationTestCase):
    def test_concurrent_create_resolves_single_artifact_row(self) -> None:
        from domain.factories.project_factory import ProjectFactory
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )

        project = ProjectFactory().create("Concurrent Artifact Project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        repository = PostgreSQLArtifactRepository(self.session_factory)
        dedup_key = compute_artifact_deduplication_key(
            workflow_run_id="run-a",
            artifact_type=DR06_RESEARCH_REPORT_TYPE,
        )
        report_id = str(uuid4())

        def attempt(*, title: str, filename: str) -> tuple[str, str]:
            artifact = _sample_artifact(
                project_id=project.id,
                run_id="run-a",
                dedup_key=dedup_key,
                title=title,
                filename=filename,
                report_id=report_id,
            )
            try:
                repository.create(artifact)
                return artifact.id, artifact.content_checksum
            except DuplicateArtifactError:
                existing = repository.get_by_deduplication_key("run-a", dedup_key)
                assert existing is not None
                return existing.id, existing.content_checksum

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    attempt,
                    title="Research Report v1",
                    filename="report-v1.md",
                ),
                executor.submit(
                    attempt,
                    title="Renamed Research Report",
                    filename="different-name.md",
                ),
            ]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]

        ids = {item[0] for item in results}
        checksums = {item[1] for item in results}
        self.assertEqual(len(ids), 1)
        self.assertEqual(len(checksums), 1)

        stored = repository.get_by_id(next(iter(ids)))
        assert stored is not None
        self.assertEqual(stored.deduplication_key, dedup_key)
        self.assertEqual(len(repository.list_for_run("run-a")), 1)
        self.assertTrue(stored.content)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLConcurrentArtifactServiceTests(PostgreSQLIntegrationTestCase):
    def test_concurrent_write_for_context_resolves_single_artifact(self) -> None:
        from tests.integration.postgresql.dr06_fixtures import (
            build_report_service,
            seed_report_prerequisites,
        )

        project, context, _, _, _, _ = seed_report_prerequisites(
            self.session_factory,
            run_id="run-artifact-concurrent",
        )
        service = build_report_service(self.session_factory)

        def attempt() -> tuple[str, str]:
            summary = service.write_for_context(context)
            artifact = service._artifact_repository.get_by_id(summary.artifact_id)
            assert artifact is not None
            return summary.artifact_id, artifact.content_checksum

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt), executor.submit(attempt)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]

        artifact_ids = {item[0] for item in results}
        checksums = {item[1] for item in results}
        self.assertEqual(len(artifact_ids), 1)
        self.assertEqual(len(checksums), 1)
        self.assertEqual(
            len(service._artifact_repository.list_for_run(context.workflow_run.id)),
            1,
        )


if __name__ == "__main__":
    unittest.main()
