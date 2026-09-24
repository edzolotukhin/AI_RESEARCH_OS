"""Saved-source PDF catalog, authorization and immutable download regression."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from api.ui.principal import resolve_ui_principal
from api.ui.pdf_csrf import token as pdf_csrf_token
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from tests.api.helpers import ApiTestCase
from tools.pf03_visual_server import _create_run


class _PdfRenderer:
    calls = 0

    def render(self, document):
        self.calls += 1
        return b"%PDF-1.4\n" + document.source_id.encode() + b"\n" + document.status.encode()


class DeliverableUiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.owner = resolve_ui_principal(self.container).principal_id
        self.renderer = _PdfRenderer()
        self.container.project_deliverables_service.renderer = self.renderer

    def _desk(self, project_id="prf06e-project", run_id="prf06e-run"):
        return _create_run(self.container, self.owner, project_id=project_id,
                           run_id=run_id, title="Синтетичне дослідження")

    def _report(self, project, run, revision=1, status="draft", report_id=None):
        report = Report(
            id=report_id or f"{run.id}-report-{revision}", project_id=project.id,
            workflow_run_id=run.id, research_design_id="design-1",
            title=f"Український звіт {revision}", language="uk",
            sections=(ReportSection(f"section-{revision}", "Висновки", f"Збережений текст {revision}"),),
            executive_summary="Точне резюме", limitations=("Обмеження доказів",),
            created_at=f"2026-09-{revision:02}T00:00:00Z", generation_method="test",
            finding_refs=(), insight_refs=(), evidence_refs=(), citation_registry={},
            revision_number=revision, previous_report_id=None if revision == 1 else f"{run.id}-report-{revision-1}",
            approval_status=status, deduplication_key=f"{run.id}-{revision}",
        )
        self.container.report_query_service._report_repository.create(report)
        return report

    def _review(self, report, verdict, suffix):
        review = ReviewResult(
            id=f"{report.id}-review-{suffix}", project_id=report.project_id,
            workflow_run_id=report.workflow_run_id, research_design_id=report.research_design_id,
            report_id=report.id, review_attempt=suffix, verdict=verdict,
            quality_dimensions=(), issues=(), summary="Тест", review_method="test",
            created_at=datetime.now(timezone.utc).isoformat(), deduplication_key=f"{report.id}-{suffix}",
        )
        self.container.review_query_service._review_repository.create(review)

    def _post_pdf(self, project_id, method, source_id):
        return self.client.post(f"/ui/projects/{project_id}/reports/{method}/{source_id}/pdf",
                                data={"csrf_token": pdf_csrf_token(
                                    self.container, self.owner, project_id, method, source_id)},
                                follow_redirects=False)

    def test_draft_catalog_generation_and_repeated_identical_download(self):
        project, run = self._desk()
        report = self._report(project, run)
        page = self.client.get(f"/ui/projects/{project.id}/outputs")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Чернетка", page.text)
        self.assertIn(report.id, page.text)
        url = f"/ui/projects/{project.id}/reports/DESK/{report.id}/pdf"
        self.assertEqual(self._post_pdf(project.id, "DESK", report.id).status_code, 303)
        self.assertEqual(self._post_pdf(project.id, "DESK", report.id).status_code, 303)
        self.assertEqual(self.renderer.calls, 1)
        item = self.container.project_deliverables_service.source(
            project.id, "DESK", report.id, owner_id=self.owner)
        self.assertEqual(item.pdf.status_snapshot, "Чернетка")
        download = f"{url}/{item.pdf.id}"
        first = self.client.get(download)
        second = self.client.get(download)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.content, second.content)
        self.assertEqual(hashlib.sha256(first.content).hexdigest(), item.pdf.checksum)
        self.assertEqual(first.headers["cache-control"], "private, no-store")
        self.assertIn("attachment", first.headers["content-disposition"])
        self.assertIn("Збережений текст 1", self.client.get(
            f"/ui/projects/{project.id}/reports/DESK/{report.id}").text)
        self.assertEqual(self.container.report_query_service.get_report(report.id).sections[0].content,
                         "Збережений текст 1")

    def test_review_after_draft_export_keeps_old_snapshot_downloadable(self):
        project, run = self._desk()
        report = self._report(project, run)
        service = self.container.project_deliverables_service
        draft = service.generate(project.id, "DESK", report.id, owner_id=self.owner)
        self._review(report, ReviewVerdict.APPROVE, 1)
        current = service.source(project.id, "DESK", report.id, owner_id=self.owner)
        self.assertEqual(current.document.status, "Схвалено")
        self.assertIsNone(current.pdf)
        old, data = service.download(project.id, "DESK", report.id, draft.id, owner_id=self.owner)
        self.assertEqual(old.status_snapshot, "Чернетка")
        self.assertIn("Чернетка".encode(), data)
        approved = service.generate(project.id, "DESK", report.id, owner_id=self.owner)
        self.assertNotEqual(draft.id, approved.id)
        self.assertEqual(approved.status_snapshot, "Схвалено")

    def test_latest_created_differs_from_approved_and_ambiguity_is_not_approved(self):
        project, run = self._desk()
        first = self._report(project, run, status="approved")
        latest = self._report(project, run, revision=2)
        self._review(first, ReviewVerdict.APPROVE, 1)
        self._review(latest, ReviewVerdict.APPROVE, 1)
        self._review(latest, ReviewVerdict.REVISE, 2)
        catalog = self.container.project_deliverables_service.catalog(project.id, owner_id=self.owner)
        self.assertEqual(catalog.latest_created_desk_id, latest.id)
        self.assertEqual(catalog.latest_approved_desk_id, first.id)
        self.assertEqual(catalog.desk[0].document.status, "Статус перевірки не підтверджено")
        self.assertEqual(catalog.desk[0].document.sections[0].paragraphs, ("Збережений текст 2",))

    def test_approval_field_without_review_is_not_approval(self):
        project, run = self._desk()
        report = self._report(project, run, status="approved")
        item = self.container.project_deliverables_service.source(project.id, "DESK", report.id, owner_id=self.owner)
        self.assertEqual(item.document.status, "Статус перевірки не підтверджено")

    def test_foreign_unknown_and_wrong_method_are_safe_404(self):
        project, run = self._desk()
        report = self._report(project, run)
        foreign, _ = self._desk("prf06e-foreign", "prf06e-foreign-run")
        for url in (
            f"/ui/projects/{foreign.id}/reports/DESK/{report.id}/pdf",
            f"/ui/projects/{project.id}/reports/QUANTITATIVE/{report.id}/pdf",
            f"/ui/projects/{project.id}/reports/DESK/unknown/pdf",
        ):
            parts = url.split("/")
            self.assertEqual(self._post_pdf(parts[3], parts[5], parts[6]).status_code, 404)

    def test_generation_failure_has_no_completed_record(self):
        project, run = self._desk()
        report = self._report(project, run)
        self.container.project_deliverables_service.renderer = type("Fail", (), {
            "render": lambda _self, _doc: (_ for _ in ()).throw(ValueError("secret content"))})()
        response = self._post_pdf(project.id, "DESK", report.id)
        self.assertEqual(response.status_code, 303)
        self.assertNotIn("secret content", response.headers["location"])
        item = self.container.project_deliverables_service.source(project.id, "DESK", report.id, owner_id=self.owner)
        self.assertIsNone(item.pdf)
        self.container.project_deliverables_service.renderer = self.renderer
        self.assertEqual(self._post_pdf(project.id, "DESK", report.id).status_code, 303)
        self.assertIsNotNone(self.container.project_deliverables_service.source(
            project.id, "DESK", report.id, owner_id=self.owner).pdf)

    def test_pdf_generation_requires_action_bound_csrf(self):
        project, run = self._desk()
        report = self._report(project, run)
        url = f"/ui/projects/{project.id}/reports/DESK/{report.id}/pdf"
        self.assertEqual(self.client.post(url, follow_redirects=False).status_code, 403)
        self.assertEqual(self.client.post(url, data={"csrf_token": "wrong"},
                                          follow_redirects=False).status_code, 403)

    def test_memory_store_concurrent_generation_has_one_record(self):
        project, run = self._desk()
        report = self._report(project, run)
        service = self.container.project_deliverables_service
        def generate(_):
            return service.generate(project.id, "DESK", report.id, owner_id=self.owner).id
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(generate, range(8)))
        self.assertEqual(len(set(ids)), 1)

    def test_revoked_project_access_blocks_subsequent_download(self):
        project, run = self._desk()
        report = self._report(project, run)
        service = self.container.project_deliverables_service
        pdf = service.generate(project.id, "DESK", report.id, owner_id=self.owner)
        project = self.container.project_service.get_project(project.id)
        project.owner_principal_id = "revoked-owner"
        self.container.project_service.save_project(project)
        url = f"/ui/projects/{project.id}/reports/DESK/{report.id}/pdf/{pdf.id}"
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_saved_quantitative_compositions_are_separate_and_no_report_is_not_fabricated(self):
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
            description="", submission_key="prf06e-quant-study")
        service = self.container.project_deliverables_service
        self.assertFalse(service.catalog(project.id, owner_id=self.owner).quantitative)
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
        catalog = service.catalog(project.id, owner_id=self.owner)
        self.assertEqual(len(catalog.quantitative), 2)
        self.assertEqual({item.document.source_version for item in catalog.quantitative},
                         {"composition-1", "composition-2"})
        self.assertTrue(all(item.document.revision_number is None for item in catalog.quantitative))
        self.assertTrue(all(item.document.status == "Прийнято" for item in catalog.quantitative))
