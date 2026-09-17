from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from api.ui.quantitative_presentation import (
    finding_statement,
    format_base,
    format_statistic,
    humanize,
    present_quantitative_status,
)
from application.query.quantitative_study_views import (
    AnalysisItemView,
    FindingView,
    InsightView,
    MetricView,
    ResultItemView,
)
from tests.api.helpers import ApiTestCase


class Ui02PresentationHelpersTests(unittest.TestCase):
    def test_humanizes_canonical_quantitative_values(self):
        self.assertEqual(humanize("ONE_WAY"), "Одновимірний розподіл")
        self.assertEqual(humanize("GROUPED_CATEGORY_PERCENTAGE"), "Частка об’єднаних категорій")
        self.assertEqual(humanize("UNWEIGHTED"), "Без зважування")
        self.assertEqual(humanize("QUANTITATIVE"), "Кількісне дослідження")
        self.assertEqual(humanize("VALID_RESPONSES"), "Валідні відповіді")

    def test_formats_percentages_counts_means_and_bases_without_recomputing(self):
        self.assertEqual(format_statistic("77.847309136420525", "GROUPED_CATEGORY_PERCENTAGE"), "77,8%")
        self.assertEqual(format_statistic("622", "CATEGORY_COUNT"), "622")
        self.assertEqual(format_statistic("7.384230287", "NUMERIC_MEAN"), "7,38")
        self.assertEqual(format_base("799"), "n = 799")
        self.assertEqual(format_base(None), "n = —")

    def test_finding_statement_removes_only_system_owned_context_trailer(self):
        text = "77.8% agree with the statement. [Canonical quantitative context: context=abc; denominator=799.]"
        self.assertEqual(finding_statement(text), "77.8% agree with the statement.")
        self.assertEqual(finding_statement("Ordinary prose [with brackets]."), "Ordinary prose [with brackets].")


class Ui02ProductFidelityRoutesTests(ApiTestCase):
    def _create(self, title="UI-02 дослідження"):
        response = self.client.post(
            "/ui/quantitative/studies",
            data={"title": title, "description": "Перевірка продуктового представлення", "submission_key": "ui-02-" + title},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        return response.headers["location"].rsplit("/", 1)[-1]

    def test_sparse_study_renders_all_routes_without_fake_data(self):
        study_id = self._create("Порожній стан")
        for section in ("overview", "data", "analysis", "results", "report"):
            with self.subTest(section=section):
                page = self.client.get(f"/ui/quantitative/studies/{study_id}/{section}")
                self.assertEqual(page.status_code, 200)
                self.assertNotIn("None", page.text)
                self.assertNotIn("Traceback", page.text)
        self.assertIn("Дані ще не завантажено", self.client.get(f"/ui/quantitative/studies/{study_id}/data").text)
        self.assertIn("Підтверджених висновків поки немає", self.client.get(f"/ui/quantitative/studies/{study_id}/results").text)
        self.assertIn("Автоматичний звіт не сформовано", self.client.get(f"/ui/quantitative/studies/{study_id}/report").text)

    def test_study3_shaped_results_are_human_facing_and_context_is_collapsed(self):
        study_id = self._create("Study 3 presentation")
        facade_module = __import__("api.ui.quantitative_facade", fromlist=["build_quantitative_ui_facade"])
        base = facade_module.build_quantitative_ui_facade(self.container).view(study_id, active="results")
        findings = tuple(
            FindingView(
                f"Підтверджений висновок {index}", 1, "Підтверджено", "77,8%",
                "Ability to solve tasks", "qualified power-tool users", "Валідні відповіді",
                "n = 799", "Без зважування", "Позитивні категорії 4–5",
            )
            for index in range(1, 11)
        )
        results = tuple(
            ResultItemView("SL73R5", "Частка об’єднаних категорій", "77,8%", "622", "n = 799", "qualified power-tool users", "Валідні відповіді", "Усі респонденти", "Без зважування", "4, 5", "77.8")
            for _ in range(70)
        )
        analyses = tuple(
            AnalysisItemView("Одновимірний розподіл", present_quantitative_status("completed"), "qualified power-tool users", "Без зважування", 14)
            for _ in range(5)
        )
        shaped = replace(
            base,
            respondent_count=811,
            variable_count=1178,
            results=results,
            analyses=analyses,
            findings=findings,
            insights=(),
            metrics=(MetricView("Респонденти", "811"), MetricView("Результати", "70")),
            result_count=70,
            completed_analysis_count=5,
            finding_count=10,
            insight_count=0,
            status=present_quantitative_status("completed", terminal_outcome="COMPLETED_WITH_NO_SUPPORTED_INSIGHTS"),
            report_status=present_quantitative_status("completed", terminal_outcome="COMPLETED_WITH_NO_SUPPORTED_INSIGHTS", scope="report"),
        )
        with patch("api.ui.quantitative_facade.QuantitativeUiFacade.view", return_value=shaped):
            results_page = self.client.get(f"/ui/quantitative/studies/{study_id}/results").text
            report_page = self.client.get(f"/ui/quantitative/studies/{study_id}/report").text
            analysis_page = self.client.get(f"/ui/quantitative/studies/{study_id}/analysis").text
        self.assertEqual(results_page.count('class="finding"'), 10)
        self.assertIn("77,8%", results_page)
        self.assertIn("n = 799", results_page)
        self.assertIn("Недостатньо підтверджень", results_page)
        self.assertIn("10", report_page)
        self.assertIn("70", analysis_page)
        combined = results_page + report_page + analysis_page
        for forbidden in (
            "Canonical quantitative context", "context=", "semantic_context", "provider",
            "AUTHORIZED", "CONSUMED", "QI", "QJ", "QK", "qk-", "protected-dataset://",
        ):
            self.assertNotIn(forbidden, combined)

    def test_primary_pages_do_not_leak_uuid_or_raw_precision(self):
        study_id = self._create("Без витоків")
        combined = "".join(self.client.get(f"/ui/quantitative/studies/{study_id}/{section}").text for section in ("overview", "data", "analysis", "results", "report"))
        self.assertNotIn(f">{study_id}<", combined)
        self.assertNotIn("77.847309136420525", combined)
        self.assertNotIn("GROUPED_CATEGORY_PERCENTAGE", combined)
        self.assertNotIn("UNWEIGHTED", combined)

    def test_xss_remains_escaped(self):
        study_id = self._create('<img src=x onerror=alert(1)>')
        page = self.client.get(f"/ui/quantitative/studies/{study_id}/overview").text
        self.assertNotIn('<img src=x onerror=alert(1)>', page)
        self.assertIn("&lt;img", page)


if __name__ == "__main__":
    unittest.main()