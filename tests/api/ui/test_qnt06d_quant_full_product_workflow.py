"""QNT-06D provider-free canonical product journey through persisted documents."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from api.ui.pdf_csrf import token
from api.ui.principal import resolve_ui_principal
from domain.quantitative.analysis import StatisticalResult
from domain.quantitative.review import QuantitativeApprovedRevision
from domain.quantitative.report import QuantitativeReportCompositionResult
from tests.api.helpers import ApiTestCase
from tests.api.ui.test_prf06f_presentation_ui import _Jobs, _Renderer


class _PdfRenderer:
    def __init__(self):
        self.calls = 0

    def render(self, document):
        self.calls += 1
        return b"%PDF-1.4\n" + document.source_id.encode() + document.source_version.encode()


class Qnt06dQuantFullProductWorkflowTests(ApiTestCase):
    @property
    def owner(self):
        return resolve_ui_principal(self.container).principal_id

    def _project_and_study(self):
        created = self.client.post(
            "/ui/projects",
            data={"name": "QNT-06D known-answer project",
                  "selected_methods": ["QUANTITATIVE"]},
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303, created.text)
        project_id = created.headers["location"].rsplit("/", 1)[-1]
        self.assertEqual(self.client.post(
            f"/ui/projects/{project_id}/brief",
            data={
                "title": "Known-answer quantitative study",
                "business_question": "How is the synthetic choice distributed?",
                "objectives": "Measure choice distribution",
                "geography": "Synthetic market", "market": "Synthetic category",
                "timeframe": "2026", "language": "en",
            }, follow_redirects=False,
        ).status_code, 303)
        self.assertEqual(self.client.post(
            f"/ui/projects/{project_id}/design/generate",
            follow_redirects=False,
        ).status_code, 303)
        project = self.container.project_service.get_project(project_id)
        self.assertEqual(self.client.post(
            f"/ui/projects/{project_id}/design/approve",
            data={"design_id": project.current_research_design.id},
            follow_redirects=False,
        ).status_code, 303)
        activated = self.client.post(
            f"/ui/projects/{project_id}/methods/QUANTITATIVE/activate",
            follow_redirects=False,
        )
        self.assertEqual(activated.status_code, 303, activated.text)
        study_id = activated.headers["location"].split("/studies/", 1)[1].split("/", 1)[0]
        return project_id, study_id

    def _approved_design(self, study_id):
        uploaded = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": (
                "known.sav",
                Path("tests/fixtures/quantitative/rb_reconciliation.sav").read_bytes(),
                "application/octet-stream",
            )}, follow_redirects=False,
        )
        self.assertEqual(uploaded.status_code, 303, uploaded.text)
        self.assertEqual(self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc",
            follow_redirects=False,
        ).status_code, 303)
        data_page = self.client.get(f"/ui/quantitative/studies/{study_id}/data")
        fingerprint = re.search(r'name="fingerprint" value="([^"]+)"', data_page.text)
        self.assertIsNotNone(fingerprint)
        self.assertEqual(self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc-approval",
            data={"fingerprint": fingerprint.group(1), "decision": "APPROVED",
                  "rationale": "Known-answer QC reviewed"},
            follow_redirects=False,
        ).status_code, 303)
        study = self.container.quantitative_ui_service.get(study_id, owner_id=self.owner)
        _, codebook = self.container.quantitative_ui_service._dataset(study)
        variable = next(item for item in codebook.variables if item.name == "categorical")
        group = next(item for item in codebook.variables if item.name == "region")
        self.assertEqual(self.client.post(
            f"/ui/quantitative/studies/{study_id}/design",
            data={
                "title": "Choice distribution",
                "research_question": "How is choice distributed?",
                "population": "Synthetic respondents", "procedure": "CROSS_TAB",
                "primary_variable_id": variable.variable_id,
                "group_variable_id": group.variable_id,
                "weighting_mode": "UNWEIGHTED",
            }, follow_redirects=False,
        ).status_code, 303)
        analysis = self.client.get(f"/ui/quantitative/studies/{study_id}/analysis")
        version = re.search(r'name="plan_version_id" value="([^"]+)"', analysis.text)
        plan_fp = re.search(r'name="expected_fingerprint" value="([^"]+)"', analysis.text)
        self.assertIsNotNone(version)
        self.assertIsNotNone(plan_fp)
        self.assertEqual(self.client.post(
            f"/ui/quantitative/studies/{study_id}/design/approve",
            data={"plan_version_id": version.group(1),
                  "expected_fingerprint": plan_fp.group(1),
                  "rationale": "Exact plan approved"},
            follow_redirects=False,
        ).status_code, 303)

    def test_project_to_approved_revision_report_pdf_pptx_and_downloads(self):
        project_id, study_id = self._project_and_study()
        self._approved_design(study_id)
        self.assertEqual(self.client.post(
            f"/ui/quantitative/studies/{study_id}/analysis/execute",
            follow_redirects=False,
        ).status_code, 303)
        authority = self.container.quantitative_authority_product_service.projection(
            study_id, owner_id=self.owner)
        self.assertTrue(authority["semantic_authorization_required"])
        self.assertEqual(self.client.post(
            f"/ui/quantitative/studies/{study_id}/analysis/authorize-semantics",
            data={"expected_authority_fingerprint": authority["semantic_authorization_token"],
                  "rationale": "Exact deterministic results reviewed"},
            follow_redirects=False,
        ).status_code, 303)

        study = self.container.quantitative_ui_service.get(study_id, owner_id=self.owner)
        records = self.container.quantitative_ui_service.state.list_for_run(
            study.run_id, project_id=project_id)
        results = tuple(item for item in records if isinstance(item, StatisticalResult))
        revision = next(item for item in records
                        if isinstance(item, QuantitativeApprovedRevision))
        composition = next(item for item in records
                           if isinstance(item, QuantitativeReportCompositionResult))
        self.assertTrue(results)
        self.assertEqual(revision.report_id, composition.accepted_report.report_id)
        self.assertEqual(revision.report_validation_fingerprint,
                         composition.accepted_report.validation_fingerprint)
        result_ids = {item.result_id for item in results}
        referenced = {value for section in composition.accepted_report.sections
                      for value in section.authoritative_result_refs}
        self.assertTrue(referenced)
        self.assertTrue(referenced.issubset(result_ids))

        results_page = self.client.get(f"/ui/quantitative/studies/{study_id}/results")
        self.assertIn("Відкрити звіт і документи", results_page.text)
        service = self.container.project_deliverables_service
        pdf_renderer = _PdfRenderer()
        pptx_renderer = _Renderer()
        service.renderer = pdf_renderer
        service.presentation_jobs = _Jobs()
        service.pptx_renderer = pptx_renderer
        outputs_url = f"/ui/projects/{project_id}/outputs"
        outputs = self.client.get(outputs_url)
        self.assertEqual(outputs.status_code, 200)
        self.assertIn(revision.revision_id, outputs.text)
        self.assertIn(revision.fingerprint, outputs.text)
        self.assertIn("Створити PDF", outputs.text)
        self.assertIn("Створити презентацію", outputs.text)
        report_url = f"/ui/projects/{project_id}/reports/QUANTITATIVE/{revision.revision_id}"
        report_page = self.client.get(report_url)
        self.assertEqual(report_page.status_code, 200)
        self.assertIn(composition.accepted_report.title, report_page.text)

        pdf_action = report_url + "/pdf"
        self.assertEqual(self.client.post(
            pdf_action,
            data={"csrf_token": token(self.container, self.owner, project_id,
                                      "QUANTITATIVE", revision.revision_id)},
            follow_redirects=False,
        ).status_code, 303)
        item = service.source(project_id, "QUANTITATIVE", revision.revision_id,
                              owner_id=self.owner)
        self.assertEqual(item.document.source_version, revision.fingerprint)
        self.assertEqual(item.pdf.source_version, revision.fingerprint)
        pdf_url = f"{pdf_action}/{item.pdf.id}"
        pdf_one = self.client.get(pdf_url)
        pdf_two = self.client.get(pdf_url)
        self.assertEqual(pdf_one.status_code, 200)
        self.assertEqual(hashlib.sha256(pdf_one.content).hexdigest(), item.pdf.checksum)
        self.assertEqual(pdf_one.content, pdf_two.content)
        self.assertEqual(pdf_renderer.calls, 1)

        pptx_action = report_url + "/pptx"
        self.assertEqual(self.client.post(
            pptx_action,
            data={"csrf_token": token(self.container, self.owner, project_id,
                                      "QUANTITATIVE", revision.revision_id, "pptx")},
            follow_redirects=False,
        ).status_code, 303)
        self.assertIn("Презентація створюється", self.client.get(outputs_url).text)
        self.assertTrue(service.process_next_presentation("qnt06d-worker"))
        item = service.source(project_id, "QUANTITATIVE", revision.revision_id,
                              owner_id=self.owner)
        self.assertEqual(item.pptx.source_version, revision.fingerprint)
        pptx_url = f"{pptx_action}/{item.pptx.id}"
        pptx_one = self.client.get(pptx_url)
        pptx_two = self.client.get(pptx_url)
        self.assertEqual(pptx_one.status_code, 200)
        self.assertEqual(hashlib.sha256(pptx_one.content).hexdigest(), item.pptx.checksum)
        self.assertEqual(pptx_one.content, pptx_two.content)
        self.assertEqual(pptx_renderer.calls, 1)
        final_outputs = self.client.get(outputs_url).text
        self.assertIn("PDF збережено", final_outputs)
        self.assertIn("PPTX збережено", final_outputs)
        self.assertIn("Завантажити PPTX", final_outputs)

        # Cross-project and unknown artifact identities remain undisclosed.
        foreign = self.client.post(
            "/ui/projects",
            data={"name": "Foreign", "selected_methods": ["QUANTITATIVE"]},
            follow_redirects=False,
        ).headers["location"].rsplit("/", 1)[-1]
        self.assertEqual(self.client.get(pdf_url.replace(project_id, foreign)).status_code, 404)
        self.assertEqual(self.client.get(pptx_url.replace(project_id, foreign)).status_code, 404)
        self.assertEqual(self.client.get(pdf_url.rsplit("/", 1)[0] + "/unknown").status_code, 404)


if __name__ == "__main__":
    import unittest
    unittest.main()
