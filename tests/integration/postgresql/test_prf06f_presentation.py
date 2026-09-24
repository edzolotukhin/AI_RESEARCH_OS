"""PRF-06F production-shaped PostgreSQL/API/worker integration."""

from __future__ import annotations

import hashlib
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

from api.ui.pdf_csrf import token
from api.ui.principal import resolve_ui_principal
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.workflow_template import WorkflowTemplate
from tests.api.helpers import build_test_container, close_test_client, open_test_client
from tests.integration.postgresql.helpers import integration_tests_enabled
from worker.loop import WorkerLoop


@unittest.skipUnless(integration_tests_enabled(), "disposable PostgreSQL test database required")
class PresentationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.container = build_test_container(persistence_backend="postgresql",
                                              background_execution_mode="external")
        self.client, _, context = open_test_client(self.container)
        self.addCleanup(close_test_client, context, self.container)
        self.owner = resolve_ui_principal(self.container).principal_id
        self.project = self.container.project_service.create_project(
            "Синтетичний PRF-06F", owner_principal_id=self.owner,
            selected_methods=("DESK",))
        template = WorkflowTemplate(id=str(uuid4()), name="Synthetic Desk")
        self.container.workflow_service.publish_template_snapshot(template, project_id=self.project.id)
        self.run = self.container.workflow_service.create_workflow_run(template, project_id=self.project.id)
        self.report = Report(
            id=str(uuid4()), project_id=self.project.id, workflow_run_id=self.run.id,
            research_design_id=str(uuid4()), title="Синтетичний український звіт",
            language="uk", sections=(ReportSection(str(uuid4()), "Розділ",
                                                     "Збережений текст без нового висновку."),),
            executive_summary="Тільки синтетичне резюме", limitations=("Синтетичне обмеження",),
            created_at=datetime.now(timezone.utc).isoformat(), generation_method="test",
            finding_refs=(), insight_refs=(), evidence_refs=(), citation_registry={},
            deduplication_key=str(uuid4()),
        )
        self.container.report_query_service._report_repository.create(self.report)
        self.base = f"/ui/projects/{self.project.id}/reports/DESK/{self.report.id}"

    def test_explicit_schedule_worker_download_and_pdf_regression(self):
        page = self.client.get(f"/ui/projects/{self.project.id}/outputs")
        self.assertIn("Створити презентацію", page.text)
        self.assertEqual(self.client.get(f"{self.base}/pptx/not-found").status_code, 404)
        csrf = token(self.container, self.owner, self.project.id, "DESK", self.report.id, "pptx")
        response = self.client.post(f"{self.base}/pptx", data={"csrf_token": csrf},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        jobs = self.container.project_deliverables_service.presentation_jobs
        doc = self.container.project_deliverables_service.source(
            self.project.id, "DESK", self.report.id, owner_id=self.owner).document
        find = dict(project_id=self.project.id, method="DESK", source_id=self.report.id,
                    source_version=doc.source_version,
                    template_version=self.container.project_deliverables_service.pptx_renderer.template_version,
                    renderer_version=self.container.project_deliverables_service.pptx_renderer.version)
        pending = jobs.find(**find)
        self.assertEqual(pending.state, "pending")
        self.assertIn("Презентація створюється",
                      self.client.get(f"/ui/projects/{self.project.id}/outputs").text)
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: self.container.project_deliverables_service.schedule_presentation(
                self.project.id, "DESK", self.report.id, owner_id=self.owner).id, range(8)))
        self.assertEqual(set(ids), {pending.id})
        worker_container = build_test_container(persistence_backend="postgresql",
                                                background_execution_mode="external")
        self.addCleanup(worker_container.shutdown)
        self.assertGreaterEqual(WorkerLoop(worker_container, worker_id="test-worker")
                                .run_until_idle(max_iterations=1), 1)
        completed = jobs.find(**find)
        self.assertEqual(completed.state, "completed")
        self.assertEqual(completed.attempts, 1)
        url = f"{self.base}/pptx/{completed.completed_deliverable_id}"
        first = self.client.get(url)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.content.startswith(b"PK\x03\x04"))
        self.assertEqual(self.client.get(url).content, first.content)
        self.assertIn("private, no-store", first.headers["cache-control"])
        self.assertIn("Завантажити PPTX",
                      self.client.get(f"/ui/projects/{self.project.id}/outputs").text)
        other = self.container.project_service.create_project(
            "Foreign", owner_principal_id=self.owner, selected_methods=("DESK",))
        foreign = self.client.get(url.replace(self.project.id, other.id))
        self.assertEqual(foreign.status_code, 404)
        pdf_response = self.client.post(f"{self.base}/pdf", data={"csrf_token": token(
            self.container, self.owner, self.project.id, "DESK", self.report.id)},
            follow_redirects=False)
        self.assertEqual(pdf_response.status_code, 303)
        pdf = self.container.project_deliverables_service.source(
            self.project.id, "DESK", self.report.id, owner_id=self.owner).pdf
        pdf_url = f"{self.base}/pdf/{pdf.id}"
        self.assertEqual(self.client.get(pdf_url).content, self.client.get(pdf_url).content)
        self.assertEqual(hashlib.sha256(first.content).hexdigest(),
                         self.container.project_deliverables_service.store.get(
                             completed.completed_deliverable_id)[0].checksum)

    def test_foreign_schedule_and_csrf_rejected(self):
        self.assertEqual(self.client.post(f"{self.base}/pptx", data={"csrf_token": "bad"}).status_code, 403)
        other = self.container.project_service.create_project(
            "Foreign", owner_principal_id="another-owner", selected_methods=("DESK",))
        url = self.base.replace(self.project.id, other.id)
        csrf = token(self.container, self.owner, other.id, "DESK", self.report.id, "pptx")
        self.assertEqual(self.client.post(f"{url}/pptx", data={"csrf_token": csrf}).status_code, 404)

    def test_expired_worker_lease_retries_are_bounded_and_durable(self):
        service = self.container.project_deliverables_service
        jobs = service.presentation_jobs
        scheduled = service.schedule_presentation(
            self.project.id, "DESK", self.report.id, owner_id=self.owner)
        self.assertEqual(scheduled.state, "pending")
        for attempt in range(1, 4):
            claimed = jobs.claim_next(f"worker-{attempt}", lease_seconds=-1)
            self.assertEqual(claimed.id, scheduled.id)
            self.assertEqual(claimed.state, "processing")
            self.assertEqual(claimed.attempts, attempt)
        self.assertIsNone(jobs.claim_next("worker-4"))
        current = jobs.find(
            project_id=self.project.id, method="DESK", source_id=self.report.id,
            source_version=scheduled.source_version,
            template_version=scheduled.template_version,
            renderer_version=scheduled.renderer_version)
        self.assertEqual(current.state, "failed")
        self.assertEqual(current.attempts, 3)
        self.assertEqual(current.failure_code, "lease_exhausted")
        self.assertIsNone(current.completed_deliverable_id)
        self.assertEqual(jobs.retry(current.id).state, "failed")
