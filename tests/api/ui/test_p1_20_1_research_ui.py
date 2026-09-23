"""Desk UI compatibility and five-page workbench acceptance."""
from unittest.mock import MagicMock, patch
from pathlib import Path
from application.persistence.exceptions import AccessDeniedError, EntityNotFoundError
from tests.api.helpers import ApiTestCase
from tests.api.ui.desk_workbench_views import workbench_view
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF

class ResearchUiTests(ApiTestCase):
    def setUp(self):
        super().setUp(); self.ui = self._raw_client
    @staticmethod
    def facade(view=None):
        facade=MagicMock(); facade.get_status.return_value={"research_id":"run-a","execution_status":"TERMINAL","phase":"COMPLETED","product_outcome":"APPROVED","result_available":True,"workflow_status":"completed"}; facade.get_workbench.return_value=view or workbench_view(); return facade
    def page(self,name,view=None):
        with patch("api.routers.ui_research.build_research_ui_facade",return_value=self.facade(view)):
            return self.ui.get(f"/ui/research/run-a/{name}")
    def test_legacy_new_form_and_submission_remain_available(self):
        self.assertEqual(self.ui.get("/ui/research/new").status_code,200)
        response=self.ui.post("/ui/research",data={"title":BRIEF["title"],"business_question":BRIEF["business_question"],"objectives":"\n".join(BRIEF["objectives"]),"geography":", ".join(BRIEF["geography"]),"timeframe":BRIEF["timeframe"]},follow_redirects=False)
        self.assertEqual(response.status_code,303); self.assertIn("/ui/research/",response.headers["location"])
    def test_legacy_run_url_redirects_to_overview(self):
        with patch("api.routers.ui_research.build_research_ui_facade",return_value=self.facade()): response=self.ui.get("/ui/research/run-a",follow_redirects=False)
        self.assertEqual(response.status_code,302); self.assertEqual(response.headers["location"],"/ui/research/run-a/overview")
    def test_five_pages_render_ukrainian_product_shell(self):
        expected={"overview":"Стан дослідження","design":"Контекст цього запуску","evidence":"Матеріали дослідження","results":"Висновки та інсайти","report":"Структурований результат"}
        for page,text in expected.items():
            with self.subTest(page=page):
                response=self.page(page); self.assertEqual(response.status_code,200); self.assertIn(text,response.text); self.assertIn("Кабінетне дослідження",response.text); self.assertIn("Проєкт А",response.text); self.assertIn("До проєкту",response.text)
    def test_overview_has_real_counts_and_no_fake_progress(self):
        html=self.page("overview").text; self.assertIn(">181<",html); self.assertNotIn("%",html); self.assertNotIn("ETA",html); self.assertNotIn("run-a</",html)
    def test_running_overview_polls_without_resubmission(self):
        html=self.page("overview",workbench_view(outcome="RUNNING",execution="RUNNING")).text; self.assertIn("Виконується",html); self.assertIn("desk-workbench.js",html)
        script=(Path(__file__).resolve().parents[3]/"api"/"static"/"desk-workbench.js").read_text(encoding="utf-8"); self.assertIn("status.json",script); self.assertNotIn('method: "POST"',script)
    def test_outcome_states_are_distinct(self):
        for outcome,label in {"APPROVED":"Завершено","NOT_READY":"Завершено з обмеженнями","QUALITY_REJECTED":"Потребує уваги","EXECUTION_FAILED":"Помилка"}.items():
            with self.subTest(outcome=outcome): self.assertIn(label,self.page("overview",workbench_view(outcome=outcome)).text)
    def test_attention_next_step_does_not_imply_report_approval(self):
        html=self.page("overview",workbench_view(outcome="QUALITY_REJECTED")).text
        self.assertIn("Переглянути звіт і результати перевірки",html); self.assertIn("не схвалено як фінальний",html); self.assertNotIn("<h2>Звіт доступний</h2>",html)
    def test_evidence_traceability_and_truncation_are_visible(self):
        html=self.page("evidence").text; self.assertIn("Показано 1 із 181 доказів",html); self.assertIn("Джерело доказу",html); self.assertIn("https://example.com/source",html); self.assertIn('rel="noopener noreferrer"',html)
    def test_results_keep_findings_and_insights_distinct(self):
        html=self.page("results").text; self.assertIn("Підтверджені результати",html); self.assertIn("Значення результатів",html); self.assertNotIn("Рекомендації",html)
    def test_report_renders_review_without_internal_payload(self):
        html=self.page("report").text; self.assertIn("Резюме",html); self.assertIn("ПЕРЕВІРКА ЯКОСТІ",html); self.assertIn("Бракує посилання",html)
        for leaked in ("review_attempt","report_id","fingerprint","deduplication_key"): self.assertNotIn(leaked,html)
    def test_unknown_and_foreign_runs_are_non_disclosing(self):
        for error in (EntityNotFoundError("missing"),AccessDeniedError("foreign")):
            for page in ("overview", "design", "evidence", "results", "report"):
                with self.subTest(error=type(error).__name__, page=page):
                    facade=self.facade(); facade.get_workbench.side_effect=error
                    with patch("api.routers.ui_research.build_research_ui_facade",return_value=facade): response=self.ui.get(f"/ui/research/hidden/{page}")
                    self.assertEqual(response.status_code,404); self.assertIn("Дослідження не знайдено",response.text); self.assertNotIn(str(error),response.text)
    def test_status_and_detail_json_contracts_remain(self):
        facade=self.facade(); facade.get_result_detail.return_value={"outcome":"APPROVED"}
        with patch("api.routers.ui_research.build_research_ui_facade",return_value=facade):
            self.assertEqual(self.ui.get("/ui/research/run-a/status.json").status_code,200); self.assertEqual(self.ui.get("/ui/research/run-a/detail.json").status_code,200)
