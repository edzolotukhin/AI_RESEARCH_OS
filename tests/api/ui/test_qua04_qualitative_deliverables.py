import hashlib

from api.ui.pdf_csrf import token
from tests.api.test_qua03_post_analysis import Qua03PostAnalysisTests
from tests.api.ui import test_prf06f_presentation_ui as presentation_fixture


class _PdfRenderer:
    def render(self, document):
        content = "\n".join((document.title, document.summary or "", *(s.title for s in document.sections)))
        return b"%PDF-1.4\n" + content.encode("utf-8")


class Qua04QualitativeDeliverableTests(Qua03PostAnalysisTests):
    def _approved(self):
        f1=self.finding("Guidance trust",["onboarding"])
        f2=self.finding("Automation tension",["automation"])
        insight=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/insights",json={
            "thematic_id":self.thematic["thematic_revision_id"],"title":"Interpretation gap",
            "statement":"The Findings indicate tension between convenience and trusted interpretation.",
            "implication":"Guidance should preserve agency.","finding_ids":[f1["finding_id"],f2["finding_id"]],
            "status":"accepted"}).json()
        revision=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/revisions",json={
            "thematic_id":self.thematic["thematic_revision_id"],"finding_ids":[f1["finding_id"],f2["finding_id"]],
            "insight_ids":[insight["insight_id"]]}).json()
        return self.client.post(
            f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/revisions/{revision['revision_id']}/review",
            json={"decision":"approved"}).json()["approved_revision"]

    def _final_report(self):
        approved=self._approved()
        service=self.container.qualitative_report_service
        draft=service.create_draft(self.project.id,self.run,approved["approved_revision_id"],
                                   owner_id=self.owner,title="Qualitative known-answer report")
        revised=service.revise(self.project.id,self.run,draft.record_id,owner_id=self.owner,
            title="Qualitative known-answer report",executive_summary="Across the interview corpus, accepted patterns remained bounded.",
            methodology="In-Depth Interviews with three pseudonymous participants; accepted coding and thematic review.",
            limitations="Small qualitative corpus; prepared transcripts have no fabricated timestamps.",
            conclusion="The accepted Findings support a bounded design implication.")
        final=service.finalize(self.project.id,self.run,revised.record_id,owner_id=self.owner)
        return approved, final

    def test_report_exact_authority_revisioning_structure_and_source_binding(self):
        approved, final=self._final_report()
        payload=final.payload
        self.assertEqual(payload["approved_revision_id"],approved["approved_revision_id"])
        self.assertEqual(payload["status"],"final")
        self.assertEqual(len(payload["finding_ids"]),2)
        self.assertEqual(len(payload["insight_ids"]),1)
        self.assertTrue(payload["deviant_cases"])
        self.assertTrue(payload["evidence_excerpts"])
        self.assertTrue(all(x["timestamp"] is None for x in payload["evidence_excerpts"]))
        self.assertTrue(all(x["label"].startswith(("P","I","Participant")) for x in payload["evidence_excerpts"]))
        document=self.container.project_deliverables_service.source(
            self.project.id,"QUALITATIVE",final.record_id,owner_id=self.owner).document
        self.assertEqual(document.source_version,final.checksum)
        # A later Approved Revision cannot move the immutable Report source.
        later_f=self.finding("Later bounded pattern",["onboarding"])
        later_i=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/insights",json={
            "thematic_id":self.thematic["thematic_revision_id"],"title":"Later interpretation",
            "statement":"The later accepted Finding remains separately versioned.",
            "implication":"Existing deliverables remain historical.","finding_ids":[later_f["finding_id"]],
            "status":"accepted"}).json()
        later_r=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/revisions",json={
            "thematic_id":self.thematic["thematic_revision_id"],"finding_ids":[later_f["finding_id"]],
            "insight_ids":[later_i["insight_id"]]}).json()
        later_a=self.client.post(
            f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/revisions/{later_r['revision_id']}/review",
            json={"decision":"approved"}).json()["approved_revision"]
        self.assertNotEqual(later_a["approved_revision_id"],approved["approved_revision_id"])
        historical=self.container.project_deliverables_service.source(
            self.project.id,"QUALITATIVE",final.record_id,owner_id=self.owner).document
        self.assertEqual((historical.source_id,historical.source_version),(final.record_id,final.checksum))

    def test_ui_pdf_pptx_immutable_downloads_and_authorization(self):
        approved, final=self._final_report()
        service=self.container.project_deliverables_service
        service.renderer=_PdfRenderer(); service.presentation_jobs=presentation_fixture._Jobs()
        service.pptx_renderer=presentation_fixture._Renderer()
        page=self.client.get(f"/ui/projects/{self.project.id}/outputs")
        self.assertIn("Якісні звіти",page.text); self.assertIn(final.record_id,page.text)
        pdf_base=f"/ui/projects/{self.project.id}/reports/QUALITATIVE/{final.record_id}/pdf"
        response=self.client.post(pdf_base,data={"csrf_token":token(
            self.container,self.owner,self.project.id,"QUALITATIVE",final.record_id)},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        item=service.source(self.project.id,"QUALITATIVE",final.record_id,owner_id=self.owner)
        first=self.client.get(f"{pdf_base}/{item.pdf.id}"); second=self.client.get(f"{pdf_base}/{item.pdf.id}")
        self.assertEqual(first.content,second.content); self.assertEqual(hashlib.sha256(first.content).hexdigest(),item.pdf.checksum)
        pptx_base=f"/ui/projects/{self.project.id}/reports/QUALITATIVE/{final.record_id}/pptx"
        self.client.post(pptx_base,data={"csrf_token":token(
            self.container,self.owner,self.project.id,"QUALITATIVE",final.record_id,"pptx")})
        self.assertTrue(service.process_next_presentation("qua04-worker"))
        item=service.source(self.project.id,"QUALITATIVE",final.record_id,owner_id=self.owner)
        first=self.client.get(f"{pptx_base}/{item.pptx.id}"); second=self.client.get(f"{pptx_base}/{item.pptx.id}")
        self.assertEqual(first.content,second.content); self.assertEqual(hashlib.sha256(first.content).hexdigest(),item.pptx.checksum)
        self.assertEqual(self.client.get(f"/ui/projects/{self.project.id}/reports/QUALITATIVE/unknown").status_code,404)
        self.project.owner_principal_id="foreign"; self.container.project_service.save_project(self.project)
        self.assertEqual(self.client.get(f"/ui/projects/{self.project.id}/outputs").status_code,404)

    def test_product_report_draft_edit_finalize_flow_is_visible(self):
        approved=self._approved()
        workspace=f"/ui/projects/{self.project.id}/qualitative/{self.run}"
        self.assertIn("Створити Report draft",self.client.get(workspace).text)
        created=self.client.post(f"{workspace}/deliverables/reports",data={
            "approved_revision_id":approved["approved_revision_id"],"title":"UI Report"},follow_redirects=False)
        self.assertEqual(created.status_code,303)
        draft=self.container.qualitative_report_service.repository.list_for_run(
            self.run,project_id=self.project.id,record_type="qualitative_report_revision")[0]
        page=self.client.get(workspace); self.assertIn("Фіналізувати Report",page.text)
        finalized=self.client.post(f"{workspace}/deliverables/reports/{draft.record_id}/finalize",follow_redirects=False)
        self.assertEqual(finalized.status_code,303)
        self.assertIn("Якісні звіти",self.client.get(finalized.headers["location"]).text)
