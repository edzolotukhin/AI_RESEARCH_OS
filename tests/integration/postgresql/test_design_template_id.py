from __future__ import annotations

from application.composition_root import create_application_container
from api.ui.project_workspace_facade import ProjectWorkspaceFacade
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

    def test_completed_design_run_is_not_desk_and_first_activation_is_ready(self):
        from tests.api.helpers import build_test_container, drain_background_runs

        container = build_test_container(persistence_backend="postgresql")
        self.addCleanup(container.shutdown)
        project = container.project_service.create_project(
            "Workspace classification",
            owner_principal_id="owner",
            project_id="uat03-workspace-classification",
            selected_methods=("DESK",),
        )
        container.project_planning_service.save_brief(
            project,
            ResearchBrief(
                title="Population",
                business_question="How did population change?",
            ),
        )
        design_run = container.project_planning_service.schedule_design_generation(
            container.project_service.get_project(project.id)
        )
        drain_background_runs(container)

        facade = ProjectWorkspaceFacade(container)
        draft_view = facade.query.get(project.id, owner_id="owner")
        self.assertNotEqual(draft_view.desk.state.value, "COMPLETED")
        self.assertIsNone(draft_view.desk.run_id)
        self.assertNotIn("/methods/DESK/retry", draft_view.desk.primary_action.href)

        current = container.project_service.get_project(project.id)
        container.project_planning_service.approve_design(
            current,
            actor_id="owner",
            expected_design_id=current.current_research_design.id,
        )
        ready_view = facade.query.get(project.id, owner_id="owner")
        self.assertEqual(ready_view.desk.state.value, "READY")
        self.assertIn("/methods/DESK/activate", ready_view.desk.primary_action.href)

        desk_run = container.project_planning_service.activate_desk(
            container.project_service.get_project(project.id)
        )
        activated_view = facade.query.get(project.id, owner_id="owner")
        self.assertEqual(activated_view.desk.run_id, desk_run.id)
        self.assertNotEqual(activated_view.desk.run_id, design_run.id)
        self.assertEqual(
            len(container.workflow_service.list_workflow_runs_for_project(project.id)),
            2,
        )
