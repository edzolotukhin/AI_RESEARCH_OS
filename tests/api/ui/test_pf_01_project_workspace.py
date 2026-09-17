from __future__ import annotations

from unittest.mock import patch

from application.quantitative.ui_service import QuantitativeUiError
from tests.api.helpers import ApiTestCase


class Pf01ProjectWorkspaceTests(ApiTestCase):
    @property
    def owner_id(self):
        from api.ui.principal import resolve_ui_principal
        return resolve_ui_principal(self.container).principal_id

    def _project(self, name="Workspace Project"):
        response = self.client.post("/ui/projects", data={"name": name}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        return response.headers["location"].rsplit("/", 1)[-1]

    def test_empty_list_and_explicit_project_creation(self):
        project_list = self.client.get("/ui/projects").text
        self.assertIn("Проєктів ще немає", project_list)
        self.assertIn("Створити проєкт", project_list)
        create_page = self.client.get("/ui/projects/new").text
        self.assertIn("Назва проєкту", create_page)
        self.assertIn("Після створення проєкту ви зможете додати контекст дослідження та обрати методи.", create_page)
        project_id = self._project()
        project = self.container.project_service.get_project(project_id)
        self.assertEqual(project.owner_principal_id, self.owner_id)
        page = self.client.get(f"/ui/projects/{project_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Дослідницький бриф ще не додано", page.text)
        self.assertEqual(page.text.count("Не розпочато"), 2)
        self.assertIn("Розпочати кабінетне дослідження", page.text)
        self.assertIn("Налаштувати кількісне дослідження", page.text)

    def test_foreign_project_is_not_listed_or_disclosed(self):
        foreign = self.container.project_service.create_project("Foreign", owner_principal_id="foreign-owner")
        self.assertNotIn("Foreign", self.client.get("/ui/projects").text)
        self.assertEqual(self.client.get(f"/ui/projects/{foreign.id}").status_code, 404)

    def test_project_bound_quantitative_has_three_distinct_ids_and_return_link(self):
        project_id = self._project()
        response = self.client.post(f"/ui/projects/{project_id}/quantitative", data={
            "title": "Bound study", "description": "Independent identity", "submission_key": "pf-01-key"
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        study_id = response.headers["location"].split("/")[4]
        study = self.container.quantitative_ui_service.get(study_id, owner_id=self.owner_id)
        self.assertEqual(len({study.project_id, study.study_id, study.run_id}), 3)
        self.assertEqual(study.project_id, project_id)
        page = self.client.get(response.headers["location"])
        self.assertIn(f'/ui/projects/{project_id}', page.text)
        workspace = self.client.get(f"/ui/projects/{project_id}").text
        self.assertIn("Відкрити кількісне дослідження", workspace)
        self.assertIn(study_id, workspace)

    def test_workspace_presentation_has_no_pf_01_english_labels_or_raw_states(self):
        project_id = self._project("Український простір")
        pages = "".join((
            self.client.get("/ui/projects").text,
            self.client.get("/ui/projects/new").text,
            self.client.get(f"/ui/projects/{project_id}").text,
            self.client.get(f"/ui/projects/{project_id}/desk/new").text,
            self.client.get(f"/ui/projects/{project_id}/quantitative/new").text,
        ))
        for forbidden in (
            "Project Workspace", "Create Project", "Open project", "Not started",
            "Desk Research", "Quantitative Research", "Research Context",
            "NOT_STARTED", "READY", "RUNNING", "ATTENTION", "COMPLETED", "LIMITED",
        ):
            self.assertNotIn(forbidden, pages)

    def test_project_quantitative_is_idempotent_and_conflicts_safely(self):
        project_id = self._project()
        service = self.container.quantitative_ui_service
        values = dict(project_id=project_id, owner_id=self.owner_id,
                      title="Study", description="same", submission_key="stable")
        first = service.create_quantitative_study_for_project(**values)
        self.assertEqual(service.create_quantitative_study_for_project(**values), first)
        with self.assertRaises(QuantitativeUiError):
            service.create_quantitative_study_for_project(**{**values, "description": "different"})

    def test_failed_project_bound_creation_never_deletes_project(self):
        project_id = self._project()
        service = self.container.quantitative_ui_service
        with patch.object(service.workflows, "create_workflow_run", side_effect=RuntimeError("synthetic")):
            with self.assertRaises(RuntimeError):
                service.create_quantitative_study_for_project(
                    project_id=project_id, owner_id=self.owner_id,
                    title="Study", description="", submission_key="failure")
        self.assertEqual(self.container.project_service.get_project(project_id).id, project_id)

    def test_legacy_standalone_quantitative_still_works(self):
        response = self.client.post("/ui/quantitative/studies", data={
            "title": "Legacy", "description": "compatible", "submission_key": "legacy-pf-01"
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.get(response.headers["location"] + "/overview").status_code, 200)


if __name__ == "__main__":
    import unittest
    unittest.main()
