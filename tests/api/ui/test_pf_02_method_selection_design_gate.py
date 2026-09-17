from __future__ import annotations

from unittest.mock import patch

from application.services.project_planning_service import ProjectPlanningError
from application.persistence.exceptions import ConcurrentModificationError
from domain.research_brief import ResearchBrief
from tests.api.helpers import ApiTestCase


class Pf02MethodSelectionDesignGateTests(ApiTestCase):
    @property
    def owner_id(self):
        from api.ui.principal import resolve_ui_principal
        return resolve_ui_principal(self.container).principal_id

    def create(self, methods=("DESK",), name="PF-02 Project"):
        response = self.client.post(
            "/ui/projects",
            data={"name": name, "selected_methods": list(methods)},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        return response.headers["location"].rsplit("/", 1)[-1]

    def save_brief(self, project_id):
        response = self.client.post(
            f"/ui/projects/{project_id}/brief",
            data={
                "title": "Ринкове дослідження",
                "business_question": "Яка можливість виходу на ринок?",
                "objectives": "Оцінити попит\nВизначити бар’єри",
                "geography": "Україна",
                "market": "B2B",
                "timeframe": "2026",
                "language": "uk",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def approve(self, project_id):
        self.save_brief(project_id)
        response = self.client.post(
            f"/ui/projects/{project_id}/design/generate",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        project = self.container.project_service.get_project(project_id)
        self.assertIsNotNone(project.current_research_design)
        self.assertEqual(
            self.container.workflow_service.list_workflow_runs_for_project(project_id),
            [],
        )
        response = self.client.post(
            f"/ui/projects/{project_id}/design/approve",
            data={"design_id": project.current_research_design.id},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_create_requires_supported_explicit_selection_and_hides_unselected(self):
        self.assertEqual(
            self.client.post("/ui/projects", data={"name": "No method"}).status_code,
            422,
        )
        quant = self.create(("QUANTITATIVE",), "Quant only")
        project = self.container.project_service.get_project(quant)
        self.assertEqual(project.selected_methods, ("QUANTITATIVE",))
        page = self.client.get(f"/ui/projects/{quant}").text
        self.assertIn("Кількісне дослідження", page)
        self.assertNotIn("<h3>Кабінетне дослідження</h3>", page)
        listing = self.client.get("/ui/projects").text
        self.assertIn("Кількісне дослідження", listing)
        self.assertNotIn("<div class=\"method-state\"><span>Кабінетне дослідження", listing)

    def test_domain_rejects_duplicate_and_unsupported_selection(self):
        service = self.container.project_service
        with self.assertRaises(ValueError):
            service.create_project("Duplicate", selected_methods=["DESK", "DESK"])
        with self.assertRaises(ValueError):
            service.create_project("Unknown", selected_methods=["FIELD"])

    def test_historical_empty_has_no_false_pending_method(self):
        project = self.container.project_service.create_project(
            "Historical", owner_principal_id=self.owner_id,
        )
        page = self.client.get(f"/ui/projects/{project.id}").text
        self.assertIn("Методи ще не обрано", page)
        self.assertNotIn("Очікує затвердження дизайну", page)

    def test_add_remove_and_activation_removal_guard(self):
        project_id = self.create(("DESK",))
        self.client.post(
            f"/ui/projects/{project_id}/methods",
            data={"method": "QUANTITATIVE"},
        )
        project = self.container.project_service.get_project(project_id)
        self.assertEqual(project.selected_methods, ("DESK", "QUANTITATIVE"))
        self.client.post(f"/ui/projects/{project_id}/methods/QUANTITATIVE/remove")
        project = self.container.project_service.get_project(project_id)
        self.assertEqual(project.selected_methods, ("DESK",))
        self.approve(project_id)
        self.client.post(f"/ui/projects/{project_id}/methods/DESK/activate")
        project = self.container.project_service.get_project(project_id)
        with self.assertRaises(ProjectPlanningError):
            self.container.project_planning_service.remove_method(project, "DESK")

    def test_stale_project_method_mutation_is_rejected(self):
        project_id = self.create(("DESK",))
        first = self.container.project_service.get_project(project_id)
        stale = self.container.project_service.get_project(project_id)
        self.container.project_planning_service.add_method(first, "QUANTITATIVE")
        with self.assertRaises(ConcurrentModificationError):
            self.container.project_planning_service.add_method(stale, "QUANTITATIVE")

    def test_brief_and_design_persist_without_execution_and_generation_is_idempotent(self):
        project_id = self.create(("DESK",))
        self.save_brief(project_id)
        self.assertEqual(self.container.workflow_service.list_workflow_runs_for_project(project_id), [])
        service = self.container.project_planning_service
        project = self.container.project_service.get_project(project_id)
        first = service.generate_design(project)
        second = service.generate_design(self.container.project_service.get_project(project_id))
        self.assertEqual(first, second)
        self.assertEqual(self.container.workflow_service.list_workflow_runs_for_project(project_id), [])

    def test_approval_is_idempotent_and_stale_design_is_rejected(self):
        project_id = self.create(("DESK",))
        self.save_brief(project_id)
        service = self.container.project_planning_service
        project = self.container.project_service.get_project(project_id)
        design = service.generate_design(project)
        approved = service.approve_design(
            self.container.project_service.get_project(project_id),
            actor_id=self.owner_id,
            expected_design_id=design.id,
        )
        again = service.approve_design(
            self.container.project_service.get_project(project_id),
            actor_id=self.owner_id,
            expected_design_id=design.id,
        )
        self.assertEqual(approved.research_design_approved_at, again.research_design_approved_at)
        with self.assertRaises(ProjectPlanningError):
            service.approve_design(again, actor_id=self.owner_id, expected_design_id="stale")

    def test_method_change_invalidates_design_and_brief_change_is_blocked_after_activation(self):
        project_id = self.create(("DESK",))
        self.approve(project_id)
        service = self.container.project_planning_service
        service.add_method(self.container.project_service.get_project(project_id), "QUANTITATIVE")
        changed = self.container.project_service.get_project(project_id)
        self.assertIsNone(changed.current_research_design)
        self.approve(project_id)
        self.client.post(f"/ui/projects/{project_id}/methods/DESK/activate")
        changed_brief = ResearchBrief(
            title="Змінений", business_question="Інше питання?", objectives=("Інша ціль",)
        )
        with self.assertRaises(ProjectPlanningError):
            service.save_brief(self.container.project_service.get_project(project_id), changed_brief)

    def test_method_can_be_added_and_design_refreshed_after_first_activation(self):
        project_id = self.create(("DESK",))
        self.approve(project_id)
        service = self.container.project_planning_service
        desk_run = service.activate_desk(self.container.project_service.get_project(project_id))
        service.add_method(
            self.container.project_service.get_project(project_id), "QUANTITATIVE"
        )
        refreshed = service.generate_design(
            self.container.project_service.get_project(project_id)
        )
        self.assertIsNotNone(refreshed)
        self.assertEqual(
            service._desk_run(project_id).id,
            desk_run.id,
        )
        self.assertEqual(
            service.generate_design(self.container.project_service.get_project(project_id)),
            refreshed,
        )

    def test_desk_activation_reuses_approved_design_without_planner_and_is_idempotent(self):
        project_id = self.create(("DESK",))
        self.approve(project_id)
        service = self.container.project_planning_service
        with patch.object(service.planner, "run", side_effect=AssertionError("Planner rerun")):
            first = service.activate_desk(self.container.project_service.get_project(project_id))
            second = service.activate_desk(self.container.project_service.get_project(project_id))
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.container.workflow_service.list_workflow_runs_for_project(project_id)), 1)
        template = self.container.workflow_service.get_template(first.workflow_template_id)
        project = self.container.project_service.get_project(project_id)
        self.assertEqual(template.research_design_snapshot, project.current_research_design)

    def test_quantitative_activation_is_project_bound_paused_and_idempotent(self):
        project_id = self.create(("QUANTITATIVE",))
        self.approve(project_id)
        service = self.container.project_planning_service
        first = service.activate_quantitative(
            self.container.project_service.get_project(project_id), owner_id=self.owner_id,
        )
        second = service.activate_quantitative(
            self.container.project_service.get_project(project_id), owner_id=self.owner_id,
        )
        self.assertEqual(first, second)
        self.assertEqual(len({first.project_id, first.study_id, first.run_id}), 3)
        self.assertEqual(self.container.workflow_service.get_workflow_run(first.run_id).status.value, "paused")


if __name__ == "__main__":
    import unittest
    unittest.main()
