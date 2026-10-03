"""Authenticated Project Outputs flow for canonical Quant deliverables."""

from api.ui.pdf_csrf import token
from api.ui.principal import resolve_ui_principal
from application.methods.quantitative.pin import REVIEW_PIN, REVIEW_VERSION
from application.quantitative.workflow import build_quantitative_workflow_template
from domain.quantitative.workflow import QuantitativeStudyProjection
from tests.api.helpers import ApiTestCase
from tests.api.ui import test_prf06f_presentation_ui as presentation_fixture
from tests.application.quantitative import test_qnt04_review as qnt04_fixture


class _PdfRenderer:
    def render(self, document):
        return b"%PDF-1.4\n" + document.source_id.encode() + document.source_version.encode()


class QuantitativeDeliverableUiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.owner = resolve_ui_principal(self.container).principal_id
        fixture = qnt04_fixture.Qnt04ReviewTests(
            methodName="test_approved_revision_binds_exact_sources_and_replay_is_idempotent")
        fixture.setUp()
        _, self.revision = fixture.service.review(
            project_id=fixture.project_id, run_id=fixture.run_id, state=fixture.state)
        self.project = self.container.agency.create_project(
            "QNT-05 canonical outputs", owner_principal_id=self.owner,
            project_id=fixture.project_id)
        template = build_quantitative_workflow_template(cmf=True)
        self.container.workflow_service.publish_template_snapshot(
            template, project_id=self.project.id)
        self.run = self.container.workflow_service.create_workflow_run(
            template, project_id=self.project.id, run_id=fixture.run_id)
        repository = self.container.workflow_service._workflow_run_repository
        repository._task_results[self.run.id] = {REVIEW_PIN: REVIEW_VERSION}
        target = self.container.quantitative_ui_service.state
        for record in fixture.state_service._repository.list_for_run(
                fixture.run_id, project_id=fixture.project_id):
            value = fixture.state_service.load(record.record_id,
                                               project_id=fixture.project_id)
            target.persist(value, record_id=record.record_id,
                           project_id=self.project.id, run_id=self.run.id,
                           dataset_version_id=record.dataset_version_id,
                           parent_record_id=record.parent_record_id,
                           accepted=record.accepted)
        target.persist(
            QuantitativeStudyProjection(
                "study-qnt05-ui", self.project.id, self.run.id,
                "QNT-05 UI study", "offline", "COMPLETED",
                revision=1, fingerprint="study-qnt05-ui-fp"),
            record_id="study-qnt05-ui", project_id=self.project.id,
            run_id=self.run.id)
        service = self.container.project_deliverables_service
        service.renderer = _PdfRenderer()
        service.presentation_jobs = presentation_fixture._Jobs()
        service.pptx_renderer = presentation_fixture._Renderer()

    def test_authenticated_outputs_pdf_and_worker_pptx_flow(self):
        source_id = self.revision.revision_id
        outputs_url = f"/ui/projects/{self.project.id}/outputs"
        page = self.client.get(outputs_url)
        self.assertEqual(page.status_code, 200)
        self.assertIn(source_id, page.text)
        self.assertIn("Схвалено", page.text)
        self.assertIn("Створити PDF", page.text)
        self.assertIn("Створити презентацію", page.text)
        pdf_url = f"/ui/projects/{self.project.id}/reports/QUANTITATIVE/{source_id}/pdf"
        response = self.client.post(
            pdf_url, data={"csrf_token": token(
                self.container, self.owner, self.project.id,
                "QUANTITATIVE", source_id)}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        service = self.container.project_deliverables_service
        item = service.source(self.project.id, "QUANTITATIVE", source_id,
                              owner_id=self.owner)
        first_pdf = self.client.get(f"{pdf_url}/{item.pdf.id}")
        second_pdf = self.client.get(f"{pdf_url}/{item.pdf.id}")
        self.assertEqual(first_pdf.status_code, 200)
        self.assertEqual(first_pdf.content, second_pdf.content)
        pptx_url = f"/ui/projects/{self.project.id}/reports/QUANTITATIVE/{source_id}/pptx"
        response = self.client.post(
            pptx_url, data={"csrf_token": token(
                self.container, self.owner, self.project.id,
                "QUANTITATIVE", source_id, "pptx")}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(service.process_next_presentation("qnt05-ui-worker"))
        item = service.source(self.project.id, "QUANTITATIVE", source_id,
                              owner_id=self.owner)
        download = f"{pptx_url}/{item.pptx.id}"
        first_pptx = self.client.get(download)
        second_pptx = self.client.get(download)
        self.assertEqual(first_pptx.status_code, 200)
        self.assertEqual(first_pptx.content, second_pptx.content)
        self.assertIn("Завантажити PPTX", self.client.get(outputs_url).text)

    def test_unknown_revision_and_foreign_owner_are_not_disclosed(self):
        unknown = self.client.get(
            f"/ui/projects/{self.project.id}/reports/QUANTITATIVE/unknown")
        self.assertEqual(unknown.status_code, 404)
        self.project.owner_principal_id = "foreign-owner"
        self.container.project_service.save_project(self.project)
        hidden = self.client.get(f"/ui/projects/{self.project.id}/outputs")
        self.assertEqual(hidden.status_code, 404)


if __name__ == "__main__":
    import unittest
    unittest.main()
