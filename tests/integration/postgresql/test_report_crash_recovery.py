"""DR-06 crash-window and idempotent retry tests."""

from __future__ import annotations

import unittest

from application.persistence.records import ArtifactRecord
from application.ports.artifact_repository import ArtifactRepository
from application.report.deduplication import compute_content_checksum
from application.report.exceptions import ReportError
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase


class _FailOnceArtifactRepository(ArtifactRepository):
    def __init__(self, delegate: ArtifactRepository) -> None:
        self._delegate = delegate
        self._fail_next_create = True

    def create(self, artifact: ArtifactRecord) -> int:
        if self._fail_next_create:
            self._fail_next_create = False
            raise RuntimeError("simulated crash before artifact persisted")
        return self._delegate.create(artifact)

    def get_by_id(self, artifact_id: str):
        return self._delegate.get_by_id(artifact_id)

    def get_by_deduplication_key(self, workflow_run_id: str, deduplication_key: str):
        return self._delegate.get_by_deduplication_key(workflow_run_id, deduplication_key)

    def list_for_project(self, project_id: str):
        return self._delegate.list_for_project(project_id)

    def list_for_run(self, run_id: str):
        return self._delegate.list_for_run(run_id)


class ReportCrashRecoveryPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_report_before_artifact_crash_reuses_report_on_retry(self) -> None:
        from infrastructure.persistence.postgresql.repositories.postgresql_artifact_repository import (
            PostgreSQLArtifactRepository,
        )
        from tests.integration.postgresql.dr06_fixtures import (
            build_report_service,
            seed_report_prerequisites,
        )

        project, context, _, _, _, _ = seed_report_prerequisites(
            self.session_factory,
            run_id="run-crash-report-before-artifact",
        )
        base_artifact_repo = PostgreSQLArtifactRepository(self.session_factory)
        service = build_report_service(self.session_factory)
        service._artifact_repository = _FailOnceArtifactRepository(base_artifact_repo)

        with self.assertRaises(RuntimeError):
            service.write_for_context(context)

        reports_after_crash = service._report_repository.list_for_project(
            project.id,
            workflow_run_id=context.workflow_run.id,
        )
        artifacts_after_crash = service._artifact_repository.list_for_run(
            context.workflow_run.id,
        )
        self.assertEqual(len(reports_after_crash), 1)
        self.assertEqual(len(artifacts_after_crash), 0)
        report_id_after_crash = reports_after_crash[0].id

        summary = service.write_for_context(context)
        self.assertEqual(summary.report_id, report_id_after_crash)

        reports_after_retry = service._report_repository.list_for_project(
            project.id,
            workflow_run_id=context.workflow_run.id,
        )
        artifacts_after_retry = service._artifact_repository.list_for_run(
            context.workflow_run.id,
        )
        self.assertEqual(len(reports_after_retry), 1)
        self.assertEqual(len(artifacts_after_retry), 1)
        self.assertEqual(summary.artifact_id, artifacts_after_retry[0].id)

        artifact = service._artifact_repository.get_by_id(summary.artifact_id)
        assert artifact is not None
        self.assertEqual(
            artifact.content_checksum,
            compute_content_checksum(artifact.content),
        )

    def test_artifact_before_checkpoint_retry_reuses_both_rows(self) -> None:
        """PF-04 note: task checkpoint is separate; ReportService retry is idempotent."""
        from tests.integration.postgresql.dr06_fixtures import (
            build_report_service,
            seed_report_prerequisites,
        )

        project, context, _, _, _, _ = seed_report_prerequisites(
            self.session_factory,
            run_id="run-crash-artifact-before-checkpoint",
        )
        service = build_report_service(self.session_factory)

        first = service.write_for_context(context)
        second = service.write_for_context(context)

        self.assertEqual(first.report_id, second.report_id)
        self.assertEqual(first.artifact_id, second.artifact_id)

        reports = service._report_repository.list_for_project(
            project.id,
            workflow_run_id=context.workflow_run.id,
        )
        artifacts = service._artifact_repository.list_for_run(context.workflow_run.id)
        self.assertEqual(len(reports), 1)
        self.assertEqual(len(artifacts), 1)

        first_artifact = service._artifact_repository.get_by_id(first.artifact_id)
        second_artifact = service._artifact_repository.get_by_id(second.artifact_id)
        assert first_artifact is not None
        assert second_artifact is not None
        self.assertEqual(first_artifact.content_checksum, second_artifact.content_checksum)
        self.assertEqual(first_artifact.content, second_artifact.content)

    def test_report_stage_retry_with_different_llm_title_still_reuses_report(self) -> None:
        from application.ports.report_ports import ReportCandidate, ReportInput, ReportSectionCandidate
        from tests.integration.postgresql.dr06_fixtures import (
            build_report_service,
            seed_report_prerequisites,
        )

        class TitleDriftEngine:
            method_name = "deterministic"

            def __init__(self) -> None:
                self._call_count = 0

            def generate_sections(
                self,
                report_input: ReportInput,
            ) -> tuple[ReportSectionCandidate, ...]:
                from infrastructure.report.deterministic_report_engine import (
                    DeterministicReportEngine,
                )

                return DeterministicReportEngine().generate_sections(report_input)

            def generate_executive_summary(
                self,
                report_input: ReportInput,
                *,
                sections: tuple[ReportSectionCandidate, ...],
            ) -> ReportCandidate:
                self._call_count += 1
                title = f"LLM Title Attempt {self._call_count}"
                return ReportCandidate(
                    title=title,
                    executive_summary=f"Summary for {title}",
                    sections=sections,
                    limitations=(),
                    metadata={"attempt": self._call_count},
                )

        project, context, _, _, _, _ = seed_report_prerequisites(
            self.session_factory,
            run_id="run-title-drift-retry",
        )
        service = build_report_service(self.session_factory)
        engine = TitleDriftEngine()
        service._report_engine = engine

        first = service.write_for_context(context)
        second = service.write_for_context(context)

        self.assertEqual(first.report_id, second.report_id)
        reports = service._report_repository.list_for_project(
            project.id,
            workflow_run_id=context.workflow_run.id,
        )
        self.assertEqual(len(reports), 1)
        self.assertEqual(engine._call_count, 2)


if __name__ == "__main__":
    unittest.main()
