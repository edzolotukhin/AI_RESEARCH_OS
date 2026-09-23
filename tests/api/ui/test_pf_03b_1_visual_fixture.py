"""PF-03B.1 product-quality checks for the isolated visual fixture."""

from unittest import TestCase

from fastapi.testclient import TestClient

from tools.pf03_visual_server import app


class Pf03VisualFixtureTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def page(self, run_id: str, page: str) -> str:
        response = self.client.get(f"/ui/research/{run_id}/{page}")
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_completed_design_is_ukrainian_and_substantively_decomposed(self):
        html = self.page("pf03-completed-desk", "design")
        self.assertIn("Як проявляється попит на теплові насоси", html)
        self.assertIn("Які бар’єри входу пов’язані з вартістю", html)
        self.assertIn("Зіставити твердження різних типів джерел", html)
        for legacy in ("What evidence is required", "Desk research sources", "official statistics"):
            self.assertNotIn(legacy, html)

    def test_sources_are_explicitly_synthetic_and_dates_are_human_readable(self):
        html = self.page("pf03-completed-desk", "evidence")
        self.assertIn("синтетичний матеріал", html)
        self.assertIn("18 листопада 2025 р.", html)
        self.assertIn("вересень 2025 р.", html)
        self.assertIn("2025 р.", html)
        self.assertNotIn("T00:00:00", html)
        self.assertNotIn("example.com/market-source", html)

    def test_results_report_and_attention_copy_preserve_fixture_honesty(self):
        results = self.page("pf03-completed-desk", "results")
        report = self.page("pf03-completed-desk", "report")
        attention = self.page("pf03-attention-desk", "overview")
        self.assertIn("Ринковий попит неоднорідний", results)
        self.assertIn("Сервісна екосистема є окремим бар’єром", results)
        self.assertIn("не є верифікованими ринковими даними", report)
        self.assertIn("Переглянути звіт і результати перевірки", attention)
        self.assertIn("не схвалено як фінальний", attention)
