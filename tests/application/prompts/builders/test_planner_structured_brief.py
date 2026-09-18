from __future__ import annotations

import unittest

from application.prompts.builders.planner_prompt_builder import PlannerPromptBuilder
from application.prompts.python_format_prompt_renderer import PythonFormatPromptRenderer
from application.prompts.file_template_loader import FileTemplateLoader
from domain.project import Project
from domain.research_brief import research_brief_field_names
from runtime.workflow_context import WorkflowContext
from tests.fixtures.research_brief import sample_research_brief
from tests.helpers.executor_catalog import make_test_executor_catalog


class PlannerStructuredBriefTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = PlannerPromptBuilder(
            template_loader=FileTemplateLoader(),
            prompt_renderer=PythonFormatPromptRenderer(),
            executor_catalog=make_test_executor_catalog(),
        )
        self.project = Project(id="p1", name="Test")
        self.project.research_brief = sample_research_brief()
        self.context = WorkflowContext(
            workflow_run=None,
            project=self.project,
        )

    def test_planner_receives_structured_brief(self) -> None:
        prompt = self.builder.build(self.context)
        self.assertIn("Brand Health 2026", prompt.user)
        self.assertIn("Assess market position.", prompt.user)

    def test_all_semantic_fields_in_planner_input(self) -> None:
        prompt = self.builder.build(self.context)
        for field in research_brief_field_names():
            if field == "language":
                self.assertIn("en", prompt.user)
            elif field in {
                "objectives", "geography", "target_entities", "constraints",
                "deliverables", "known_information", "exclusions",
            }:
                value = getattr(self.project.research_brief, field)
                if value:
                    self.assertIn(value[0], prompt.user)
            else:
                value = getattr(self.project.research_brief, field)
                if value:
                    self.assertIn(str(value), prompt.user)


if __name__ == "__main__":
    unittest.main()
