"""Explicit PPTX action, truthful lifecycle, identity, status, and authorization."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import uuid4

from api.ui.pdf_csrf import token
from api.ui.principal import resolve_ui_principal
from application.deliverables.presentation_jobs import PresentationJob
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from tests.api.helpers import ApiTestCase
from tools.pf03_visual_server import _create_run


class _Jobs:
    def __init__(self):
        self.lock = Lock()
        self.jobs = {}

    @staticmethod
    def key(values):
        return tuple(values[name] for name in (
            "project_id", "method", "source_id", "source_version",
            "template_version", "renderer_version"))

    def find(self, **kwargs):
        with self.lock:
            return self.jobs.get(self.key(kwargs))

    def schedule(self, **kwargs):
        with self.lock:
            key = self.key(kwargs)
            if key not in self.jobs:
                now = datetime.now(timezone.utc)
                self.jobs[key] = PresentationJob(
                    id=str(uuid4()), state="pending", attempts=0, lease_until=None,
                    claimed_by=None, created_at=now, updated_at=now,
                    completed_deliverable_id=None, failure_code=None, **kwargs)
            return self.jobs[key]

    def _replace(self, job, **kwargs):
        new = replace(job, **kwargs)
        self.jobs[self.key(vars(new))] = new
        return new

    def retry(self, job_id):
        with self.lock:
            job = next((value for value in self.jobs.values() if value.id == job_id), None)
            return self._replace(job, state="pending", failure_code=None) if job and job.state == "failed" else job

    def claim_next(self, worker_id):
        with self.lock:
            job = next((item for item in self.jobs.values() if item.state == "pending"), None)
            if job is None:
                return None
            return self._replace(job, state="processing", attempts=job.attempts + 1,
                                 claimed_by=worker_id, lease_until=datetime.now(timezone.utc) + timedelta(seconds=120))

    def complete(self, job_id, worker_id, deliverable_id):
        with self.lock:
            job = next(value for value in self.jobs.values() if value.id == job_id)
            self._replace(job, state="completed", claimed_by=None,
                          lease_until=None, completed_deliverable_id=deliverable_id)
            return True

    def fail(self, job_id, worker_id, failure_code):
        with self.lock:
            job = next(value for value in self.jobs.values() if value.id == job_id)
            self._replace(job, state="failed", claimed_by=None, lease_until=None,
                          failure_code=failure_code)
            return True


class _Renderer:
    version = "pptx-test-v1"
    template_version = "corporate-test-v1"
    media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    def __init__(self):
        self.calls = 0
        self.fail_next = False

    def render(self, document):
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("synthetic failure")
        return b"PK\x03\x04" + document.source_id.encode() + document.status.encode() + \
            " ".join(p for section in document.sections for p in section.paragraphs).encode()


class PresentationUiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.owner = resolve_ui_principal(self.container).principal_id
        self.jobs = _Jobs()
        self.renderer = _Renderer()
        service = self.container.project_deliverables_service
        service.presentation_jobs = self.jobs
        service.pptx_renderer = self.renderer

    def _desk(self):
        return _create_run(self.container, self.owner, project_id="prf06f-test-project",
                           run_id="prf06f-test-run", title="Синтетичне дослідження")

    def _report(self, project, run, revision=1, status="draft"):
        report = Report(
            id=f"{run.id}-report-{revision}", project_id=project.id,
            workflow_run_id=run.id, research_design_id="design-1",
            title=f"Український звіт {revision}", language="uk",
            sections=(ReportSection(f"section-{revision}", "Розділ",
                                    f"Тільки збережений текст {revision}"),),
            executive_summary="Збережене резюме", limitations=("Обмеження",),
            created_at=f"2026-09-{revision:02}T00:00:00Z", generation_method="test",
            finding_refs=(), insight_refs=(), evidence_refs=(), citation_registry={},
            revision_number=revision,
            previous_report_id=None if revision == 1 else f"{run.id}-report-{revision-1}",
            approval_status=status, deduplication_key=f"{run.id}-{revision}",
        )
        self.container.report_query_service._report_repository.create(report)
        return report

    def _post(self, project_id, source_id, csrf=None):
        return self.client.post(f"/ui/projects/{project_id}/reports/DESK/{source_id}/pptx",
            data={"csrf_token": csrf if csrf is not None else token(
                self.container, self.owner, project_id, "DESK", source_id, "pptx")},
            follow_redirects=False)

    def test_explicit_async_action_idempotent_completion_and_repeated_download(self):
        project, run = self._desk()
        report = self._report(project, run)
        outputs = f"/ui/projects/{project.id}/outputs"
        self.assertIn("Створити презентацію", self.client.get(outputs).text)
        self.assertEqual(self._post(project.id, report.id, "bad").status_code, 403)
        self.assertEqual(self._post(project.id, report.id).status_code, 303)
        self.assertEqual(self._post(project.id, report.id).status_code, 303)
        self.assertEqual(len(self.jobs.jobs), 1)
        self.assertIn("Презентація створюється", self.client.get(outputs).text)
        self.assertTrue(self.container.project_deliverables_service.process_next_presentation("worker"))
        item = self.container.project_deliverables_service.source(
            project.id, "DESK", report.id, owner_id=self.owner)
        self.assertEqual(item.presentation_job.state, "completed")
        self.assertEqual(item.pptx.status_snapshot, "Чернетка")
        url = f"/ui/projects/{project.id}/reports/DESK/{report.id}/pptx/{item.pptx.id}"
        first = self.client.get(url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.content, self.client.get(url).content)
        self.assertEqual(first.headers["cache-control"], "private, no-store")
        self.assertEqual(self.renderer.calls, 1)
        self.assertIn("Завантажити PPTX", self.client.get(outputs).text)
        self.assertIn("Попередній перегляд недоступний", self.client.get(outputs).text)

    def test_exact_revision_status_and_historical_content(self):
        project, run = self._desk()
        approved = self._report(project, run, 1)
        self.container.review_query_service._review_repository.create(ReviewResult(
            id="prf06f-review", project_id=project.id, workflow_run_id=run.id,
            research_design_id=approved.research_design_id, report_id=approved.id,
            review_attempt=1, verdict=ReviewVerdict.APPROVE,
            quality_dimensions=(), issues=(), summary="Тест", review_method="test",
            created_at=datetime.now(timezone.utc).isoformat(), deduplication_key="prf06f-review"))
        draft = self._report(project, run, 2)
        for report in (approved, draft):
            self._post(project.id, report.id)
            self.container.project_deliverables_service.process_next_presentation("worker")
        service = self.container.project_deliverables_service
        old = service.source(project.id, "DESK", approved.id, owner_id=self.owner)
        latest = service.source(project.id, "DESK", draft.id, owner_id=self.owner)
        self.assertEqual(old.pptx.status_snapshot, "Схвалено")
        self.assertEqual(latest.pptx.status_snapshot, "Чернетка")
        self.assertNotEqual(old.pptx.id, latest.pptx.id)
        self.assertIn(b"1", service.download_presentation(project.id, "DESK", approved.id,
                        old.pptx.id, owner_id=self.owner)[1])
        self.assertIn(b"2", service.download_presentation(project.id, "DESK", draft.id,
                        latest.pptx.id, owner_id=self.owner)[1])

    def test_failure_retry_and_no_incomplete_download(self):
        project, run = self._desk()
        report = self._report(project, run)
        self._post(project.id, report.id)
        self.renderer.fail_next = True
        service = self.container.project_deliverables_service
        service.process_next_presentation("worker")
        failed = service.source(project.id, "DESK", report.id, owner_id=self.owner)
        self.assertEqual(failed.presentation_job.state, "failed")
        self.assertIsNone(failed.pptx)
        self.assertEqual(self.client.get(f"/ui/projects/{project.id}/reports/DESK/{report.id}/pptx/none").status_code, 404)
        self.assertIn("Повторити створення презентації",
                      self.client.get(f"/ui/projects/{project.id}/outputs").text)
        self._post(project.id, report.id)
        service.process_next_presentation("worker")
        self.assertEqual(service.source(project.id, "DESK", report.id,
                                        owner_id=self.owner).presentation_job.state, "completed")

    def test_foreign_project_and_revocation_fail_closed(self):
        project, run = self._desk()
        report = self._report(project, run)
        self._post(project.id, report.id)
        self.container.project_deliverables_service.process_next_presentation("worker")
        item = self.container.project_deliverables_service.source(
            project.id, "DESK", report.id, owner_id=self.owner)
        url = f"/ui/projects/{project.id}/reports/DESK/{report.id}/pptx/{item.pptx.id}"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url.replace(project.id, "foreign-project")).status_code, 404)
        project.owner_principal_id = "revoked-owner"
        self.container.project_service.save_project(project)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_template_version_creates_distinct_immutable_output(self):
        project, run = self._desk()
        report = self._report(project, run)
        self._post(project.id, report.id)
        service = self.container.project_deliverables_service
        service.process_next_presentation("worker")
        first = service.source(project.id, "DESK", report.id, owner_id=self.owner).pptx
        self.renderer.template_version = "corporate-test-v2"
        self._post(project.id, report.id)
        service.process_next_presentation("worker")
        second = service.source(project.id, "DESK", report.id, owner_id=self.owner).pptx
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(service.download_presentation(project.id, "DESK", report.id,
                                                       first.id, owner_id=self.owner)[0].id, first.id)

    def test_quantitative_accepted_reports_are_separate_without_desk_revisions(self):
        from domain.quantitative.report import (
            QuantitativeReport, QuantitativeReportCompositionResult,
            QuantitativeReportSection, QuantitativeReportSectionType,
            QuantitativeReportValidationStatus,
        )
        project = self.container.project_service.create_project(
            "Кількісний проєкт", owner_principal_id=self.owner,
            selected_methods=("QUANTITATIVE",))
        study = self.container.quantitative_ui_service.create_quantitative_study_for_project(
            project_id=project.id, owner_id=self.owner, title="Тестова студія",
            description="", submission_key="prf06f-quant-study")
        service = self.container.project_deliverables_service
        self.assertFalse(service.catalog(project.id, owner_id=self.owner).quantitative)
        self.assertNotIn("Створити презентацію",
                         self.client.get(f"/ui/projects/{project.id}/outputs").text)
        for index in (1, 2):
            report = QuantitativeReport(
                report_id=f"accepted-report-{index}", title=f"Звіт {index}",
                sections=(QuantitativeReportSection(
                    section_id=f"section-{index}", section_type=QuantitativeReportSectionType.KPI_RESULTS,
                    title="Показник", narrative=f"Збережене значення {index} шт.",
                    referenced_display_values=(str(index),), base_definition="40 учасників",
                ),), supporting_finding_refs=(), supporting_insight_refs=(),
                validation_status=QuantitativeReportValidationStatus.SUPPORTED,
            )
            composition = QuantitativeReportCompositionResult(
                composition_id=f"composition-{index}", input_support_bundle_fingerprint=f"bundle-{index}",
                generator_identity="test", prompt_version="1", prompt_fingerprint=f"prompt-{index}",
                proposed_report=report, accepted_report=report, rejected_reports=(),
                composition_metadata={}, composition_fingerprint=f"fingerprint-{index}",
            )
            self.container.quantitative_ui_service.state.persist(
                composition, record_id=f"composition-record-{index}",
                project_id=project.id, run_id=study.run_id, accepted=True)
        ids = []
        for index in (1, 2):
            source_id = f"accepted-report-{index}"
            response = self.client.post(
                f"/ui/projects/{project.id}/reports/QUANTITATIVE/{source_id}/pptx",
                data={"csrf_token": token(self.container, self.owner, project.id,
                                          "QUANTITATIVE", source_id, "pptx")},
                follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            service.process_next_presentation("worker")
            item = service.source(project.id, "QUANTITATIVE", source_id, owner_id=self.owner)
            self.assertEqual(item.document.status, "Прийнято")
            self.assertIsNone(item.document.revision_number)
            self.assertEqual(item.pptx.status_snapshot, "Прийнято")
            self.assertEqual(item.pptx.source_version, f"composition-{index}")
            ids.append(item.pptx.id)
        self.assertEqual(len(set(ids)), 2)


if __name__ == "__main__":
    import unittest
    unittest.main()
