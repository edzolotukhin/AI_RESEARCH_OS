"""Tests for deterministic ResearchDesign → WorkflowTemplate mapping."""

from __future__ import annotations

import unittest

from application.factories.research_design_factory import ResearchDesignFactory
from application.parsers.research_design_parser import ResearchDesignParser
from application.planner.research_design_workflow_mapper import (
    ResearchDesignWorkflowMapper,
)

from domain.project import Project

from tests.fixtures.planner_responses import VALID_RESEARCH_DESIGN_RESPONSE
from tests.fixtures.research_brief import sample_research_brief


class ResearchDesignWorkflowMapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mapper = ResearchDesignWorkflowMapper()
        self.project = Project(id="project-1", name="Brand Health 2026")
        self.project.research_brief = sample_research_brief()
        parser = ResearchDesignParser()
        factory = ResearchDesignFactory()
        dto = parser.parse(VALID_RESEARCH_DESIGN_RESPONSE)
        self.design = factory.create(dto)

    def test_maps_to_six_task_pipeline(self) -> None:
        template = self.mapper.from_research_design(self.design, self.project)
        self.assertEqual(len(template.task_definitions), 6)
        task_ids = [task.id for task in template.task_definitions]
        self.assertEqual(
            task_ids,
            [
                "task-collect-evidence",
                "task-extract-evidence",
                "task-assess-research-readiness",
                "task-analyze",
                "task-write-report",
                "task-review-report",
            ],
        )

    def test_template_name_from_brief_title(self) -> None:
        template = self.mapper.from_research_design(self.design, self.project)
        self.assertEqual(template.name, "Brand Health 2026")

    def test_snapshots_brief_and_design(self) -> None:
        template = self.mapper.from_research_design(self.design, self.project)
        self.assertIsNotNone(template.research_brief_snapshot)
        self.assertIsNotNone(template.research_design_snapshot)
        assert template.research_design_snapshot is not None
        self.assertEqual(
            len(template.research_design_snapshot.research_questions),
            2,
        )

    def test_task_metadata_links_design(self) -> None:
        template = self.mapper.from_research_design(self.design, self.project)
        for task in template.task_definitions:
            self.assertEqual(
                task.metadata.get("research_design_id"),
                self.design.id,
            )


if __name__ == "__main__":
    unittest.main()
