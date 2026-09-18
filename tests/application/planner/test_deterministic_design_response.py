"""Tests for brief-aligned deterministic planner responses."""

from __future__ import annotations

import json
import unittest

from application.planner.deterministic_design_response import (
    build_deterministic_design_response,
)
from application.planner.project_planning_profile import (
    PROJECT_PLANNING_PROFILE_KEY,
    ProjectPlanningProfile,
)
from application.prompts.builders.planner_prompt_builder import PlannerPromptBuilder
from application.prompts.file_template_loader import FileTemplateLoader
from application.prompts.python_format_prompt_renderer import (
    PythonFormatPromptRenderer,
)
from domain.project import Project
from domain.workflow_run import WorkflowRun
from runtime.workflow_context import WorkflowContext
from tests.fixtures.research_brief import sample_research_brief
from tests.helpers.executor_catalog import make_test_executor_catalog


class DeterministicDesignResponseTests(unittest.TestCase):
    def _project_prompt(self, methods, objectives=None):
        brief = sample_research_brief(
            objectives=objectives or ["Оцінити потенціал ринку."],
            geography=["Україна"],
            timeframe="2026",
            language="uk",
        )
        project = Project(id="pf02", name="Проєкт", selected_methods=methods)
        project.research_brief = brief
        context = WorkflowContext(workflow_run=WorkflowRun(id="plan"), project=project)
        context.execution_metadata[PROJECT_PLANNING_PROFILE_KEY] = (
            ProjectPlanningProfile(methods=methods, language="uk").to_metadata()
        )
        return PlannerPromptBuilder(
            template_loader=FileTemplateLoader(),
            prompt_renderer=PythonFormatPromptRenderer(),
            executor_catalog=make_test_executor_catalog(),
        ).build(context)

    def test_objective_refs_match_brief_objectives(self) -> None:
        brief = sample_research_brief(
            objectives=["Identify competitors.", "Estimate market size."],
            geography=["France"],
            timeframe="2024-2025",
        )
        project = Project(id="p1", name="Test")
        project.research_brief = brief
        prompt = PlannerPromptBuilder(
            template_loader=FileTemplateLoader(),
            prompt_renderer=PythonFormatPromptRenderer(),
            executor_catalog=make_test_executor_catalog(),
        ).build(
            WorkflowContext(workflow_run=WorkflowRun(id="plan"), project=project),
        )

        payload = json.loads(build_deterministic_design_response(prompt))
        refs = {
            ref
            for question in payload["research_questions"]
            for ref in question["objective_refs"]
        }
        self.assertEqual(
            refs,
            {"Identify competitors.", "Estimate market size."},
        )
        self.assertEqual(payload["information_needs"][0]["geography"], "France")
        self.assertEqual(payload["information_needs"][0]["timeframe"], "2024-2025")
        for need in payload["information_needs"]:
            expectation = need["evidence_expectation"]
            self.assertTrue(expectation["required_aspects"])
            self.assertIn(expectation["nature"], {"quantitative", "qualitative", "mixed"})

    def test_project_prompt_carries_methods_language_and_high_level_boundary(self):
        prompt = self._project_prompt(("QUANTITATIVE",))
        combined = prompt.system + prompt.user
        self.assertIn("Selected methods: QUANTITATIVE", combined)
        self.assertIn("Required output language: uk", combined)
        self.assertIn("HIGH-LEVEL PROJECT RESEARCH CONTRACT", combined)
        self.assertIn("Detailed target population", combined)
        self.assertIn("Decompose an objective", combined)
        self.assertIn("not wrap or paraphrase", combined)
        self.assertIn("Source strategy must follow those needs", combined)

    def test_quantitative_project_response_is_ukrainian_and_not_desk_centric(self):
        payload = json.loads(build_deterministic_design_response(
            self._project_prompt(("QUANTITATIVE",))
        ))
        rendered = json.dumps(payload, ensure_ascii=False).lower()
        self.assertEqual(payload["language"], "uk")
        self.assertIn("первинні структуровані дані", rendered)
        self.assertNotIn("desk research", rendered)
        self.assertNotIn("publicly available", rendered)
        self.assertNotIn("no primary survey", rendered)
        self.assertNotIn("what evidence is required", rendered)
        self.assertNotIn("derived from brief", rendered)

    def test_desk_and_mixed_project_responses_reflect_selected_methods(self):
        desk = json.loads(build_deterministic_design_response(
            self._project_prompt(("DESK",))
        ))
        mixed = json.loads(build_deterministic_design_response(
            self._project_prompt(("DESK", "QUANTITATIVE"))
        ))
        self.assertIn("відкриті джерела", " ".join(desk["source_strategy"]))
        mixed_sources = " ".join(mixed["source_strategy"])
        self.assertIn("відкриті джерела", mixed_sources)
        self.assertIn("структуровані дані респондентів", mixed_sources)

    def test_multiple_objectives_are_materially_decomposed(self):
        objectives = [
            "Оцінити розмір і динаміку ринку",
            "Визначити драйвери та бар'єри",
        ]
        payload = json.loads(build_deterministic_design_response(
            self._project_prompt(("QUANTITATIVE",), objectives=objectives)
        ))
        questions = payload["research_questions"]
        needs = payload["information_needs"]
        self.assertEqual(len(questions), 6)
        self.assertEqual(len({item["question"] for item in questions}), 6)
        self.assertTrue(all(item["question"] not in objectives for item in questions))
        rendered_questions = " ".join(item["question"] for item in questions)
        self.assertIn("поточний масштаб", rendered_questions)
        self.assertIn("змінювався ринок", rendered_questions)
        self.assertIn("стримують вибір", rendered_questions)
        rendered_needs = " ".join(item["description"] for item in needs)
        self.assertIn("Темпи, напрям", rendered_needs)
        self.assertIn("Поширеність і значущість", rendered_needs)
        self.assertNotIn("необхідні для цілі", rendered_needs)
        self.assertGreaterEqual(len(payload["analysis_plan"]), 2)
        self.assertEqual(len(payload["deliverable_plan"]), 2)

    def test_legacy_desk_response_remains_unchanged_without_project_profile(self):
        brief = sample_research_brief(objectives=["Identify competitors."])
        project = Project(id="legacy", name="Legacy")
        project.research_brief = brief
        prompt = PlannerPromptBuilder(
            template_loader=FileTemplateLoader(),
            prompt_renderer=PythonFormatPromptRenderer(),
            executor_catalog=make_test_executor_catalog(),
        ).build(WorkflowContext(workflow_run=WorkflowRun(id="plan"), project=project))
        payload = json.loads(build_deterministic_design_response(prompt))
        self.assertIn("What evidence is required", payload["research_questions"][0]["question"])
        self.assertIn("Desk research sources", payload["information_needs"][0]["description"])


if __name__ == "__main__":
    unittest.main()
