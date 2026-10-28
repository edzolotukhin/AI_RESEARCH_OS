from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from application.deliverables.approved_delivery_provenance import ApprovedDeliveryProvenance
from application.deliverables.contracts import PdfDeliverable
from application.persistence.records import ArtifactRecord
from domain.factories.project_factory import ProjectFactory
from infrastructure.persistence.postgresql.repositories.postgresql_artifact_repository import PostgreSQLArtifactRepository
from infrastructure.persistence.postgresql.repositories.postgresql_pdf_store import PostgreSQLPdfStore
from infrastructure.persistence.postgresql.repositories.postgresql_presentation_jobs import PostgreSQLPresentationJobs
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, integration_tests_enabled


@unittest.skipUnless(integration_tests_enabled(), "disposable PostgreSQL test database required")
class PostgreSQLApprovedDeliveryProvenanceTests(PostgreSQLIntegrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.project_id = str(uuid4())
        PostgreSQLProjectRepository(self.session_factory).create(
            ProjectFactory().create("Approved delivery provenance", project_id=self.project_id)
        )
        self.report_id = str(uuid4())
        self.report_run_id = str(uuid4())
        self.provenance = ApprovedDeliveryProvenance(
            report_id=self.report_id,
            revision_number=3,
            authority_digest="a" * 64,
            presentation_digest="b" * 64,
            review_id=str(uuid4()),
            source_workflow_run_id=str(uuid4()),
            report_workflow_run_id=self.report_run_id,
            claim_set_digest="c" * 64,
            coverage_contract_digest="d" * 64,
        )

    def test_artifact_provenance_and_legacy_null_round_trip(self) -> None:
        repository = PostgreSQLArtifactRepository(self.session_factory)
        content = "# Approved report"
        artifact = ArtifactRecord(
            id=str(uuid4()), project_id=self.project_id, artifact_type="research_report",
            title="Approved report", content=content, run_id=self.report_run_id,
            content_checksum=hashlib.sha256(content.encode()).hexdigest(),
            deduplication_key="approved", report_id=self.report_id,
            approved_delivery_provenance=self.provenance,
        )
        repository.create(artifact)
        loaded = repository.get_by_id(artifact.id)
        self.assertEqual(loaded.approved_delivery_provenance, self.provenance)
        self.assertEqual(loaded.content_checksum, artifact.content_checksum)
        legacy = ArtifactRecord(
            id=str(uuid4()), project_id=self.project_id, artifact_type="legacy",
            title="Legacy", content="legacy", run_id="legacy-run",
            deduplication_key="legacy", report_id="legacy-report",
        )
        repository.create(legacy)
        self.assertIsNone(repository.get_by_id(legacy.id).approved_delivery_provenance)

    def test_pdf_provenance_and_legacy_null_round_trip(self) -> None:
        store = PostgreSQLPdfStore(self.session_factory)
        data = b"%PDF-1.4\nTEST"
        record = PdfDeliverable(
            id=str(uuid4()), project_id=self.project_id, method="DESK",
            run_id=self.report_run_id, study_id=None, source_id=self.report_id,
            source_version="approved-v1", status_snapshot="Approved",
            renderer_version="test-renderer", created_at=datetime.now(timezone.utc),
            storage_key=str(uuid4()), checksum=hashlib.sha256(data).hexdigest(),
            byte_size=len(data), filename="approved.pdf",
            approved_delivery_provenance=self.provenance,
        )
        saved = store.complete(record, data)
        self.assertEqual(saved.approved_delivery_provenance, self.provenance)
        legacy = PdfDeliverable(
            id=str(uuid4()), project_id=self.project_id, method="DESK", run_id="legacy-run",
            study_id=None, source_id="legacy-report", source_version="legacy-v1",
            status_snapshot="Draft", renderer_version="test-renderer",
            created_at=datetime.now(timezone.utc), storage_key=str(uuid4()),
            checksum=hashlib.sha256(data).hexdigest(), byte_size=len(data),
            filename="legacy.pdf",
        )
        self.assertIsNone(store.complete(legacy, data).approved_delivery_provenance)

    def test_presentation_job_provenance_legacy_and_split_brain(self) -> None:
        jobs = PostgreSQLPresentationJobs(self.session_factory)
        job = jobs.schedule(
            project_id=self.project_id, method="DESK", run_id=self.report_run_id,
            study_id=None, source_id=self.report_id, source_version="approved-v1",
            status_snapshot="Approved", template_version="test-template",
            renderer_version="test-renderer",
            approved_delivery_provenance=self.provenance,
        )
        self.assertEqual(job.approved_delivery_provenance, self.provenance)
        legacy = jobs.schedule(
            project_id=self.project_id, method="DESK", run_id="legacy-run",
            study_id=None, source_id="legacy-report", source_version="legacy-v1",
            status_snapshot="Draft", template_version="test-template",
            renderer_version="test-renderer",
        )
        self.assertIsNone(legacy.approved_delivery_provenance)
        with self.assertRaisesRegex(ValueError, "revision_number mismatch"):
            jobs.schedule(
                project_id=self.project_id, method="DESK", run_id=self.report_run_id,
                study_id=None, source_id=self.report_id, source_version="invalid-v1",
                status_snapshot="Approved", template_version="test-template",
                renderer_version="test-renderer", report_revision=99,
                approved_delivery_provenance=self.provenance,
            )


if __name__ == "__main__":
    unittest.main()
