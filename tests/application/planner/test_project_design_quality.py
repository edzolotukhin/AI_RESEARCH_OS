from __future__ import annotations

import unittest

from application.planner.project_design_quality import (
    ProjectDesignQualityError,
    validate_project_design_depth,
)
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_brief import ResearchBrief


class ProjectDesignQualityTests(unittest.TestCase):
    def setUp(self):
        self.brief = ResearchBrief(
            title="Ринок", business_question="Який потенціал ринку?",
            objectives=("Оцінити розмір і динаміку ринку",), language="uk",
        )

    def _design(self, question, need):
        return ResearchDesign(
            id="design", language="uk",
            research_questions=(ResearchQuestion(
                id="rq", question=question,
                objective_refs=(self.brief.objectives[0],),
            ),),
            information_needs=(InformationNeed(
                id="need", research_question_id="rq", description=need,
                evidence_expectation=EvidenceExpectation(
                    nature="quantitative", required_aspects=("market_scale",),
                ),
            ),),
            source_strategy=("Первинні структуровані дані",),
            analysis_plan=("Оцінити масштаб і зміну",),
            deliverable_plan=("Оцінка ринку",),
        )

    def test_rejects_mechanical_question_and_need_without_exact_phrase_filter(self):
        design = self._design(
            "Які відомості необхідні щодо оцінки розміру і динаміки ринку?",
            "Дані щодо оцінки розміру і динаміки ринку.",
        )
        with self.assertRaises(ProjectDesignQualityError) as raised:
            validate_project_design_depth(self.brief, design)
        self.assertEqual(len(raised.exception.issues), 2)

    def test_accepts_substantive_question_and_information_need(self):
        design = self._design(
            "Як змінювався обсяг ринку та які сегменти формують його структуру?",
            "Річний обсяг, темп зміни та частки релевантних сегментів.",
        )
        validate_project_design_depth(self.brief, design)

    def test_quantitative_only_rejects_desk_sources_and_qz_detail(self):
        design = self._design(
            "Як змінювався обсяг ринку та які сегменти формують його структуру?",
            "Річний обсяг, темп зміни та частки релевантних сегментів.",
        )
        design = ResearchDesign(
            **{
                **design.__dict__,
                "source_strategy": ("Офіційна статистика та компанійні звіти",),
                "analysis_plan": ("Розрахувати TAM/SAM/SOM і CAGR",),
            }
        )
        with self.assertRaises(ProjectDesignQualityError) as raised:
            validate_project_design_depth(
                self.brief, design, methods=("QUANTITATIVE",),
            )
        fields = {item.field for item in raised.exception.issues}
        self.assertIn("source_strategy", fields)
        self.assertIn("method_boundary", fields)

    def test_quantitative_only_rejects_localized_provider_reports_and_qz_detail(self):
        design = self._design(
            "Як змінювався обсяг ринку та які сегменти формують його структуру?",
            "Річний обсяг, темп зміни та частки релевантних сегментів.",
        )
        design = ResearchDesign(
            **{
                **design.__dict__,
                "source_strategy": (
                    "Агреговані звіти від провайдерів сервісів",
                    "Ціновий модуль Gabor-Granger та вагування вибірки",
                ),
                "analysis_plan": (
                    "TAM/SAM/SOM, регресія та SEM із перевіркою статистичної значущості",
                ),
                "limitations": ("Потрібні коригувальні ваги вибірки",),
            }
        )
        with self.assertRaises(ProjectDesignQualityError) as raised:
            validate_project_design_depth(
                self.brief, design, methods=("QUANTITATIVE",),
            )
        fields = {item.field for item in raised.exception.issues}
        self.assertIn("source_strategy", fields)
        self.assertIn("method_boundary", fields)
