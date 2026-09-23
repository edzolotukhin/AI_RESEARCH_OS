from __future__ import annotations

from unittest.mock import patch

from api.ui.principal import resolve_ui_principal
from application.persistence.exceptions import AccessDeniedError
from application.query.project_outputs_query_service import ProjectOutputsQueryService
from tests.api.helpers import ApiTestCase


class ProjectOutputsTests(ApiTestCase):
    @property
    def owner_id(self):
        return resolve_ui_principal(self.container).principal_id

    def _project(self, methods=("DESK", "QUANTITATIVE")):
        response = self.client.post(
            "/ui/projects", data={"name": "Результати проєкту", "selected_methods": list(methods)},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        return response.headers["location"].rsplit("/", 1)[-1]

    def test_selected_unactivated_methods_have_no_fabricated_outputs_or_links(self):
        project_id = self._project()
        workspace = self.client.get(f"/ui/projects/{project_id}")
        self.assertIn(f"/ui/projects/{project_id}/outputs", workspace.text)
        page = self.client.get(f"/ui/projects/{project_id}/outputs")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.text.count("Не активовано"), 2)
        self.assertEqual(page.text.count("Результатів поки немає"), 2)
        self.assertNotIn("Відкрити дослідження", page.text)
        self.assertIn("Історія активності недоступна", page.text)
        self.assertNotIn("<time", page.text)

    def test_project_access_is_checked_before_output_reads(self):
        foreign = self.container.project_service.create_project(
            "Foreign outputs", owner_principal_id="other-user", selected_methods=("DESK",),
        )
        with patch.object(self.container.workflow_service, "list_workflow_runs_for_project") as runs:
            page = self.client.get(f"/ui/projects/{foreign.id}/outputs")
            self.assertEqual(page.status_code, 404)
            self.assertNotIn("Foreign outputs", page.text)
            runs.assert_not_called()
        self.assertEqual(self.client.get("/ui/projects/unknown/outputs").status_code, 404)

    def test_project_bound_quantitative_link_is_scoped_and_report_unavailable(self):
        project_id = self._project(("QUANTITATIVE",))
        study = self.container.quantitative_ui_service.create_quantitative_study_for_project(
            project_id=project_id, owner_id=self.owner_id, title="Study",
            description="", submission_key="prf04",
        )
        study_id = study.study_id
        page = self.client.get(f"/ui/projects/{project_id}/outputs")
        self.assertEqual(page.status_code, 200)
        self.assertIn(f"/ui/quantitative/studies/{study_id}/overview", page.text)
        self.assertIn("Очікує даних", page.text)
        self.assertIn("Звіт недоступний", page.text)
        other = self._project(("QUANTITATIVE",))
        self.assertNotIn(study_id, self.client.get(f"/ui/projects/{other}/outputs").text)

    def test_historical_project_without_methods_is_readable(self):
        project = self.container.project_service.create_project(
            "Historical", owner_principal_id=self.owner_id,
        )
        page = self.client.get(f"/ui/projects/{project.id}/outputs")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Методи ще не обрано", page.text)
        self.assertIn("Історія активності недоступна", page.text)

    def test_cross_project_run_is_rejected_before_method_output_lookup(self):
        project_id = self._project(("DESK",))
        project = self.container.project_service.get_project(project_id)
        foreign = self.container.project_service.create_project(
            "Foreign", owner_principal_id="other-user",
        )
        from domain.workflow_run import WorkflowRun
        wrong = WorkflowRun(id="foreign-run", project_id=foreign.id)
        with patch.object(self.container.workflow_service, "list_workflow_runs_for_project", return_value=[wrong]):
            with self.assertRaises(AccessDeniedError):
                ProjectOutputsQueryService(container=self.container).get(project, owner_id=self.owner_id)

    def test_desk_run_navigates_to_its_canonical_workbench(self):
        from tools.pf03_visual_server import _create_run
        project, run = _create_run(
            self.container, self.owner_id, project_id="prf04-desk-project",
            run_id="prf04-desk-run", title="Демонстраційний проєкт",
        )
        page = self.client.get(f"/ui/projects/{project.id}/outputs")
        self.assertEqual(page.status_code, 200)
        self.assertIn(f"/ui/research/{run.id}/overview", page.text)
        self.assertIn("Звіт недоступний", page.text)
        self.assertNotIn("Статистичні результати", page.text)

    def test_completed_desk_materials_and_review_are_method_specific(self):
        from tools.pf03_visual_server import _complete, _create_run, _seed_materials, _seed_report
        from domain.reviews.review_verdict import ReviewVerdict
        project, run = _create_run(
            self.container, self.owner_id, project_id="prf04-desk-completed",
            run_id="prf04-desk-completed-run", title="Завершений проєкт",
        )
        _, _, findings, now = _seed_materials(self.container, project, run)
        _seed_report(self.container, project, run, findings, now, verdict=ReviewVerdict.APPROVE)
        _complete(run)
        self.container.workflow_service.save_workflow_run(run)
        page = self.client.get(f"/ui/projects/{project.id}/outputs")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Завершено", page.text)
        self.assertIn("Джерела", page.text)
        self.assertIn("Докази", page.text)
        self.assertIn("Звіт доступний", page.text)
        self.assertIn("Перевірка: Схвалено", page.text)
        self.assertNotIn("Статистичні результати", page.text)
