"""Atomic PDF bytes/metadata, uniqueness and DB-level immutability."""

from __future__ import annotations

import hashlib
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from application.deliverables.contracts import PdfDeliverable
from domain.factories.project_factory import ProjectFactory
from infrastructure.persistence.postgresql.repositories.postgresql_pdf_store import PostgreSQLPdfStore
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from tests.integration.postgresql.helpers import create_test_engine, integration_tests_enabled
from tests.api.helpers import build_test_container, open_test_client, close_test_client
from api.ui.principal import resolve_ui_principal
from api.ui.pdf_csrf import token as pdf_csrf_token
from domain.workflow_template import WorkflowTemplate
from domain.reports.report import Report
from domain.reports.report_section import ReportSection


@unittest.skipUnless(integration_tests_enabled(), "disposable PostgreSQL test database required")
class PostgreSQLPdfStoreTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.addCleanup(self.engine.dispose)
        self.sessions = DatabaseSessionFactory(self.engine)
        self.store = PostgreSQLPdfStore(self.sessions)
        self.project_id = str(uuid4())
        project = ProjectFactory().create("Synthetic PRF-06E", project_id=self.project_id)
        project.owner_principal_id = "test-owner"
        PostgreSQLProjectRepository(self.sessions).create(project)

    def _record(self, *, version="revision-1-review-empty", size=13):
        identifier = str(uuid4())
        data = b"%PDF-1.4\nTEST"
        return PdfDeliverable(
            id=identifier, project_id=self.project_id, method="DESK", run_id="synthetic-run",
            study_id=None, source_id="synthetic-report", source_version=version,
            status_snapshot="Чернетка", renderer_version="prf06e-reportlab-1",
            created_at=datetime.now(timezone.utc), storage_key=identifier,
            checksum=hashlib.sha256(data).hexdigest(), byte_size=size,
            filename=f"research-desk-{identifier}.pdf",
        ), data

    def test_complete_is_atomic_and_repeated_reads_have_exact_bytes(self):
        record, data = self._record(size=13)
        saved = self.store.complete(record, data)
        loaded, content = self.store.get(saved.id)
        self.assertEqual(content, data)
        self.assertEqual(loaded.checksum, hashlib.sha256(data).hexdigest())
        self.assertEqual(loaded.byte_size, len(data))
        with self.engine.connect() as connection:
            trigger_exists = connection.execute(text(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = "
                "'pdf_deliverables'::regclass AND tgname = 'trg_pdf_deliverable_immutable')"
            )).scalar_one()
        # Other integration tests rebuild tables from ORM metadata and thereby remove
        # migration-only triggers. The migration smoke asserts the trigger on a fresh DB.
        if trigger_exists:
            with self.assertRaises(Exception):
                with self.engine.begin() as connection:
                    connection.execute(text("UPDATE pdf_deliverables SET content = :data WHERE id = :id"),
                                       {"data": b"changed", "id": saved.id})

    def test_concurrent_completion_returns_one_record(self):
        def complete(_):
            record, data = self._record(size=13)
            return self.store.complete(record, data).id
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(complete, range(8)))
        self.assertEqual(len(set(ids)), 1)

    def test_failed_constraint_does_not_expose_metadata_or_blob(self):
        record, data = self._record(version="failed", size=0)
        with self.assertRaises(Exception):
            self.store.complete(record, data)
        self.assertIsNone(self.store.find(project_id=self.project_id, method="DESK",
                                          source_id="synthetic-report", source_version="failed",
                                          renderer_version="prf06e-reportlab-1"))

    def test_saved_report_to_authorized_pdf_to_restart_safe_bytes(self):
        """Uses the real ReportLab renderer and migrated PostgreSQL store."""
        from infrastructure.persistence.postgresql.repositories.postgresql_pdf_store import PostgreSQLPdfStore

        container = build_test_container(persistence_backend="postgresql",
                                         background_execution_mode="external")
        client, _, context = open_test_client(container)
        self.addCleanup(close_test_client, context, container)
        owner = resolve_ui_principal(container).principal_id
        project = container.project_service.create_project(
            "Синтетичний PDF проєкт", owner_principal_id=owner,
            selected_methods=("DESK",))
        template = WorkflowTemplate(id=str(uuid4()), name="Synthetic Desk")
        container.workflow_service.publish_template_snapshot(template, project_id=project.id)
        run = container.workflow_service.create_workflow_run(template, project_id=project.id)
        report = Report(
            id=str(uuid4()), project_id=project.id, workflow_run_id=run.id,
            research_design_id=str(uuid4()), title="Український збережений звіт",
            language="uk", sections=(ReportSection(str(uuid4()), "Розділ",
                                                     "Власний збережений текст S1."),),
            executive_summary="Синтетичне резюме", limitations=("Немає реальних даних",),
            created_at=datetime.now(timezone.utc).isoformat(), generation_method="test",
            finding_refs=(), insight_refs=(), evidence_refs=(), citation_registry={},
            deduplication_key=str(uuid4()),
        )
        container.report_query_service._report_repository.create(report)
        catalog = container.project_deliverables_service.catalog(project.id, owner_id=owner)
        self.assertEqual(catalog.desk[0].document.source_id, report.id)
        self.assertEqual(catalog.desk[0].document.status, "Чернетка")
        base = f"/ui/projects/{project.id}/reports/DESK/{report.id}/pdf"
        response = client.post(base, data={"csrf_token": pdf_csrf_token(
            container, owner, project.id, "DESK", report.id)}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        record = container.project_deliverables_service.source(
            project.id, "DESK", report.id, owner_id=owner).pdf
        self.assertIsNotNone(record)
        downloaded = client.get(f"{base}/{record.id}")
        self.assertEqual(downloaded.status_code, 200)
        self.assertTrue(downloaded.content.startswith(b"%PDF-"))
        self.assertEqual(hashlib.sha256(downloaded.content).hexdigest(), record.checksum)
        self.assertEqual(client.get(f"{base}/{record.id}").content, downloaded.content)
        # A fresh engine/session simulates another API process after restart.
        fresh_engine = create_test_engine()
        self.addCleanup(fresh_engine.dispose)
        fresh_store = PostgreSQLPdfStore(DatabaseSessionFactory(fresh_engine))
        self.assertEqual(fresh_store.get(record.id)[1], downloaded.content)
