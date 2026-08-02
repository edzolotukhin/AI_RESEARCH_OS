"""Two-run report/artifact isolation within one project."""

from __future__ import annotations

import unittest

from tests.integration.postgresql.dr06_fixtures import (
    build_report_service,
    seed_report_prerequisites,
)
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase


class RunReportArtifactIsolationPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_two_runs_keep_independent_report_and_artifact_counts(self) -> None:
        service = build_report_service(self.session_factory)

        project, context_a, _, _, _, _ = seed_report_prerequisites(
            self.session_factory,
            project_name="Isolation Project",
            run_id="iso-run-a",
        )
        _, context_b, _, _, _, _ = seed_report_prerequisites(
            self.session_factory,
            run_id="iso-run-b",
            project=project,
        )

        def report_count(run_id: str) -> int:
            return len(
                service._report_repository.list_for_project(
                    project.id,
                    workflow_run_id=run_id,
                ),
            )

        def artifact_count(run_id: str) -> int:
            return len(service._artifact_repository.list_for_run(run_id))

        self.assertEqual(report_count("iso-run-a"), 0)
        self.assertEqual(report_count("iso-run-b"), 0)
        self.assertEqual(artifact_count("iso-run-a"), 0)
        self.assertEqual(artifact_count("iso-run-b"), 0)

        summary_a = service.write_for_context(context_a)
        self.assertEqual(report_count("iso-run-a"), 1)
        self.assertEqual(artifact_count("iso-run-a"), 1)
        self.assertEqual(report_count("iso-run-b"), 0)
        self.assertEqual(artifact_count("iso-run-b"), 0)

        summary_b = service.write_for_context(context_b)
        self.assertEqual(report_count("iso-run-a"), 1)
        self.assertEqual(artifact_count("iso-run-a"), 1)
        self.assertEqual(report_count("iso-run-b"), 1)
        self.assertEqual(artifact_count("iso-run-b"), 1)
        self.assertNotEqual(summary_a.report_id, summary_b.report_id)
        self.assertNotEqual(summary_a.artifact_id, summary_b.artifact_id)

        reports_a = service._report_repository.list_for_project(
            project.id,
            workflow_run_id="iso-run-a",
        )
        reports_b = service._report_repository.list_for_project(
            project.id,
            workflow_run_id="iso-run-b",
        )
        self.assertEqual(len(reports_a), 1)
        self.assertEqual(len(reports_b), 1)
        self.assertNotEqual(reports_a[0].id, reports_b[0].id)


if __name__ == "__main__":
    unittest.main()
