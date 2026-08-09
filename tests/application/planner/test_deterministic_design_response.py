"""Tests for brief-aligned deterministic planner responses."""

from __future__ import annotations

import json
import unittest

from application.planner.deterministic_design_response import (
    build_deterministic_design_response,
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


if __name__ == "__main__":
    unittest.main()
