from __future__ import annotations

from application.composition_root import create_application_container
from domain.research_brief import ResearchBrief
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class PostgreSQLDesignTemplateIdTests(PostgreSQLIntegrationTestCase):
    def test_design_generation_persists_bounded_template_and_reuses_active_run(self):
        container = create_application_container(config=postgresql_application_config())
        self.addCleanup(container.shutdown)
        project = container.project_service.create_project(
            "Long design identity",
            owner_principal_id="owner",
            project_id="18effb16-cc82-4c9d-92eb-d2da3312e5a6",
            selected_methods=("DESK",),
        )
        container.project_planning_service.save_brief(
            project,
            ResearchBrief(
                title="Population",
                business_question="How did population change?",
            ),
        )

        first = container.project_planning_service.schedule_design_generation(project)
        self.assertLessEqual(len(first.workflow_template_id), 64)
        self.assertTrue(first.workflow_template_id.startswith("project-design:"))
        self.assertIsNotNone(
            container.workflow_service.get_template(first.workflow_template_id)
        )

        reloaded = container.project_service.get_project(project.id)
        second = container.project_planning_service.schedule_design_generation(reloaded)
        self.assertEqual(second.id, first.id)
        self.assertEqual(
            len(container.workflow_service.list_workflow_runs_for_project(project.id)),
            1,
        )
