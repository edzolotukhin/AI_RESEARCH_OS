"""Desk workbench content-safety and bounded-presentation acceptance."""
from unittest.mock import MagicMock,patch
from pathlib import Path
from application.query.desk_workbench_query_service import DeskSourceView
from tests.api.helpers import ApiTestCase
from tests.api.ui.desk_workbench_views import workbench_view

class ResearchUiHardeningTests(ApiTestCase):
    def render(self,page,view):
        facade=MagicMock(); facade.get_workbench.return_value=view
        with patch("api.routers.ui_research.build_research_ui_facade",return_value=facade): return self._raw_client.get(f"/ui/research/run-a/{page}").text
    def test_research_content_is_escaped_on_all_content_pages(self):
        payload="<script>alert(1)</script>"; view=workbench_view(malicious=payload)
        for page in ("evidence","report"):
            html=self.render(page,view); self.assertNotIn(payload,html); self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;",html)
    def test_unsafe_source_scheme_is_not_linked(self):
        view=workbench_view(); unsafe=DeskSourceView("source-x","Небезпечне","","","web",None,"",None,"javascript:alert(1)",None)
        view=view.__class__(view.header,view.design,(unsafe,),1,view.evidence,view.evidence_total,view.findings,view.findings_total,view.insights,view.insights_total,view.report,view.limitations)
        html=self.render("evidence",view); self.assertNotIn('href="javascript:',html); self.assertIn("Посилання недоступне",html)
    def test_normal_pages_do_not_expose_internal_identifiers_or_scores(self):
        for page in ("overview","design","evidence","results","report"):
            html=self.render(page,workbench_view())
            for forbidden in ("source-1</","evidence-1</","run-a</","fingerprint","confidence","deduplication","policy_code","content_text"): self.assertNotIn(forbidden,html)
    def test_bounded_text_discloses_truncation(self):
        html=self.render("evidence",workbench_view()); self.assertIn("Текст скорочено для перегляду",html); self.assertIn("Показано 1 із 181 доказів",html)
    def test_not_ready_does_not_fabricate_downstream_output(self):
        view=workbench_view(outcome="NOT_READY"); results=self.render("results",view); report=self.render("report",view)
        self.assertIn("Недостатньо доказів",results); self.assertIn("Підтриманий доказами звіт не сформовано",report); self.assertNotIn(">Інсайт<",results)
    def test_ui_owned_workbench_copy_has_no_legacy_english_labels(self):
        html=self.render("overview",workbench_view())
        for legacy in ("Research progress","Research in progress","Planning the research","Execution failed","Quality not approved"): self.assertNotIn(legacy,html)
    def test_no_credentials_in_templates_or_script(self):
        root=Path(__file__).resolve().parents[3]; paths=[root/"api"/"templates"/"research"/"workbench_base.html",root/"api"/"static"/"desk-workbench.js"]
        text="\n".join(path.read_text(encoding="utf-8") for path in paths); self.assertNotIn("Authorization",text); self.assertNotIn("Bearer",text); self.assertNotIn("UI_API_KEY",text)
