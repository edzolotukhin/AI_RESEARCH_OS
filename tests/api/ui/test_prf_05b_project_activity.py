"""Synthetic Activity read states; no canonical project is altered."""

from __future__ import annotations

from unittest.mock import Mock

from application.query.project_activity_views import ActivityEventView, ActivityTimeline
from tests.api.helpers import ApiTestCase


class ProjectActivityUiTests(ApiTestCase):
    def _project(self):
        from api.ui.principal import resolve_ui_principal
        owner = resolve_ui_principal(self.container).principal_id
        return self.container.project_service.create_project(
            "Синтетичний UI сценарій", owner_principal_id=owner,
            selected_methods=("DESK",),
        )

    def test_supported_authoritatively_complete_empty_read_model(self):
        project = self._project()
        # Intentionally synthetic: a real newly created project has PROJECT_CREATED.
        self.container.activity_reader = Mock(list_for_project=Mock(return_value=ActivityTimeline()))
        page = self.client.get(f"/ui/projects/{project.id}/outputs")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Подій поки немає", page.text)
        self.assertNotIn("Історія за попередній період недоступна", page.text)

    def test_timeline_and_historical_gap_hide_internal_identifiers(self):
        project = self._project()
        event = ActivityEventView("Перевірка звіту виявила зауваження", "23.09.2026 12:00 UTC", "Кабінетне дослідження")
        self.container.activity_reader = Mock(list_for_project=Mock(return_value=ActivityTimeline((event,), True)))
        page = self.client.get(f"/ui/projects/{project.id}/outputs")
        self.assertEqual(page.status_code, 200)
        self.assertIn(event.label, page.text)
        self.assertIn(event.date_time, page.text)
        self.assertIn("Історія за попередній період недоступна", page.text)
        self.assertNotIn("run_id", page.text)
        self.assertNotIn("actor_id", page.text)

    def test_read_failure_leaves_project_outputs_usable(self):
        project = self._project()
        self.container.activity_reader = Mock(list_for_project=Mock(side_effect=RuntimeError("private detail")))
        page = self.client.get(f"/ui/projects/{project.id}/outputs")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Не вдалося завантажити активність", page.text)
        self.assertIn("Не активовано", page.text)
        self.assertNotIn("private detail", page.text)

    def test_unsupported_storage_and_authorization_before_read(self):
        project = self._project()
        page = self.client.get(f"/ui/projects/{project.id}/outputs")
        self.assertIn("Активність недоступна в поточному режимі зберігання", page.text)
        foreign = self.container.project_service.create_project("Чужий", owner_principal_id="foreign")
        reader = Mock(list_for_project=Mock(return_value=ActivityTimeline()))
        self.container.activity_reader = reader
        self.assertEqual(self.client.get(f"/ui/projects/{foreign.id}/outputs").status_code, 404)
        self.assertEqual(self.client.get("/ui/projects/unknown/outputs").status_code, 404)
        reader.list_for_project.assert_not_called()
