from __future__ import annotations
import unittest
from dataclasses import replace
from unittest.mock import patch
from application.query.quantitative_study_views import FindingView
from api.ui.quantitative_presentation import present_quantitative_status
from tests.api.helpers import ApiTestCase

class Ui01BStatusPresentationTests(unittest.TestCase):
    def test_central_statuses_are_human_facing(self):
        self.assertEqual(present_quantitative_status("running").label,"Виконується")
        self.assertEqual(present_quantitative_status("completed").label,"Завершено")
        self.assertEqual(present_quantitative_status("failed").label,"Потребує уваги")
    def test_no_supported_insights_is_controlled_outcome(self):
        study=present_quantitative_status("completed",terminal_outcome="COMPLETED_WITH_NO_SUPPORTED_INSIGHTS")
        report=present_quantitative_status("completed",terminal_outcome="COMPLETED_WITH_NO_SUPPORTED_INSIGHTS",scope="report")
        self.assertEqual(study.label,"Частково підтверджено")
        self.assertEqual(report.label,"Не сформовано")
        self.assertEqual(study.severity,"warning")

class Ui01BQuantitativeProductRoutesTests(ApiTestCase):
    def _create(self,title="UI-01B дослідження"):
        response=self.client.post("/ui/quantitative/studies",data={"title":title,"description":"Перевірка продуктового інтерфейсу","submission_key":"ui-01b-"+title},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        return response.headers["location"].rsplit("/",1)[-1]
    def test_legacy_detail_redirects_to_overview(self):
        study_id=self._create()
        response=self.client.get(f"/ui/quantitative/studies/{study_id}",follow_redirects=False)
        self.assertEqual(response.status_code,303)
        self.assertEqual(response.headers["location"],f"/ui/quantitative/studies/{study_id}/overview")
    def test_all_five_product_routes_render_shared_shell_and_active_navigation(self):
        study_id=self._create("Маршрути")
        expected={"overview":"Огляд дослідження","data":"Дані дослідження","analysis":"Аналіз даних","results":"Результати дослідження","report":"Звіт дослідження"}
        for section,heading in expected.items():
            with self.subTest(section=section):
                page=self.client.get(f"/ui/quantitative/studies/{study_id}/{section}")
                self.assertEqual(page.status_code,200)
                self.assertIn("AI RESEARCH OS",page.text)
                self.assertIn(heading,page.text)
                self.assertIn(f'href="/ui/quantitative/studies/{study_id}/{section}"',page.text)
    def test_empty_states_are_designed_and_exports_are_honest(self):
        study_id=self._create("Порожні стани")
        self.assertIn("Дані ще не завантажено",self.client.get(f"/ui/quantitative/studies/{study_id}/data").text)
        report=self.client.get(f"/ui/quantitative/studies/{study_id}/report").text
        self.assertIn("Автоматичний звіт не сформовано",report)
        self.assertIn("Експорт кількісного звіту поки недоступний",report)
        self.assertNotIn("Завантажити PDF",report)
    def test_xss_is_escaped_and_internal_or_sensitive_terms_are_absent(self):
        study_id=self._create('<script>alert("x")</script>')
        page=self.client.get(f"/ui/quantitative/studies/{study_id}/overview").text
        self.assertNotIn('<script>alert("x")</script>',page)
        for forbidden in ("semantic authorization","AUTHORIZED","CONSUMED","provider ledger","persistence version","protected-dataset://","respondent_identity_kind"):
            self.assertNotIn(forbidden,page)
    def test_p1_39_shaped_outcome_is_completed_with_limitations(self):
        study_id=self._create("Контрольований результат")
        facade=__import__("api.ui.quantitative_facade",fromlist=["build_quantitative_ui_facade"]).build_quantitative_ui_facade(self.container)
        base=facade.view(study_id,active="report")
        findings=tuple(FindingView(f"Підтверджений висновок {i}",1,"Підтверджено") for i in range(1,11))
        partial=present_quantitative_status("completed",terminal_outcome="COMPLETED_WITH_NO_SUPPORTED_INSIGHTS")
        report_status=present_quantitative_status("completed",terminal_outcome="COMPLETED_WITH_NO_SUPPORTED_INSIGHTS",scope="report")
        controlled=replace(base,status=partial,findings=findings,insights=(),report_sections=(),report_status=report_status)
        with patch("api.ui.quantitative_facade.QuantitativeUiFacade.view",return_value=controlled):
            results=self.client.get(f"/ui/quantitative/studies/{study_id}/results").text
            report=self.client.get(f"/ui/quantitative/studies/{study_id}/report").text
        self.assertEqual(results.count('class="finding"'),10)
        self.assertIn("Недостатньо підтверджень",results)
        self.assertIn("Не сформовано",report)
        self.assertIn("контрольований результат",results.casefold())
        self.assertNotIn("Traceback",results+report)
    def test_no_operational_rearm_or_provider_controls_in_product_pages(self):
        study_id=self._create("Безпечні дії")
        combined="".join(self.client.get(f"/ui/quantitative/studies/{study_id}/{section}").text for section in ("overview","data","analysis","results","report"))
        self.assertNotIn(f"/ui/quantitative/studies/{study_id}/rearm",combined)
        self.assertNotIn("provider",combined.casefold())

if __name__ == "__main__": unittest.main()