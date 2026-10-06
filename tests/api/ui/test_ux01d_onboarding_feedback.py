import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_fastapi_app
from application.pilot_feedback import FeedbackValidationError, build_feedback
from tests.api.helpers import build_test_container


class PilotFeedbackValidationTests(unittest.TestCase):
    def test_bounds_route_and_secret_protection(self):
        value = build_feedback(user_id="u", category="suggestion", message="  Корисна пропозиція для наступного кроку.  ", route="https://bad.example")
        self.assertEqual(value.route, "/ui/projects")
        self.assertNotIn("\n", value.message)
        with self.assertRaises(FeedbackValidationError):
            build_feedback(user_id="u", category="broken", message="password=do-not-store-this-value", route="/ui/projects")


class Ux01dOnboardingFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.container = build_test_container()
        delattr(self.container, "_test_api_key_plaintext")
        self.owner = self.container.identity_service.create_user("owner@example.com", "Owner", "correct horse battery")
        self.viewer = self.container.identity_service.create_user("viewer@example.com", "Viewer", "another correct horse")
        self.context = TestClient(create_fastapi_app(container=self.container)); self.client = self.context.__enter__()
        self.client.post("/ui/login", data={"email": "owner@example.com", "password": "correct horse battery"})
        created = self.client.post("/ui/projects", data={"name": "Pilot help", "selected_methods": "DESK"}, follow_redirects=False)
        self.project_id = created.headers["location"].rsplit("/", 1)[-1]

    def tearDown(self):
        self.context.__exit__(None, None, None); self.container.shutdown()

    def test_orientation_help_and_contextual_guidance_are_visible(self):
        listing = self.client.get("/ui/projects").text
        self.assertIn("ПЕРШИЙ КРОК", listing); self.assertIn("Як це працює", listing)
        help_page = self.client.get("/ui/help").text
        for label in ("Кабінетне дослідження", "Кількісне дослідження", "Глибинні інтерв’ю", "Чернетка", "Схвалена версія"):
            self.assertIn(label, help_page)
        project = self.client.get(f"/ui/projects/{self.project_id}").text
        self.assertIn("Надіслати відгук", project); self.assertIn("відкритих джерел", project)

    def test_viewer_gets_explicit_read_only_explanation(self):
        self.client.post(f"/ui/projects/{self.project_id}/members", data={"user_id": self.viewer.id, "role": "VIEWER"})
        self.client.post("/ui/logout"); self.client.post("/ui/login", data={"email": "viewer@example.com", "password": "another correct horse"})
        page = self.client.get(f"/ui/projects/{self.project_id}").text
        self.assertIn("Режим перегляду", page); self.assertIn("не змінювати", page)

    @patch("api.routers.ui_identity.record_feedback")
    def test_authenticated_feedback_captures_only_bounded_context(self, record):
        response = self.client.post("/ui/feedback", data={"category": "broken", "message": "Не зрозуміло, який наступний крок обрати.", "from_route": f"/ui/projects/{self.project_id}", "project_id": self.project_id})
        self.assertEqual(response.status_code, 200); self.assertIn("відгук надіслано", response.text)
        value = record.call_args.args[0]
        self.assertEqual(value.project_id, self.project_id); self.assertEqual(value.role, "OWNER")
        self.assertFalse(hasattr(value, "research_payload"))

    @patch("api.routers.ui_identity.record_feedback", side_effect=RuntimeError("sink unavailable"))
    def test_feedback_failure_is_recoverable_and_preserves_message(self, _record):
        message = "Збережіть цей текст для повторної спроби."
        response = self.client.post("/ui/feedback", data={"category": "broken", "message": message, "from_route": "/ui/projects"})
        self.assertEqual(response.status_code, 503); self.assertIn("Спробуйте ще раз", response.text); self.assertIn(message, response.text)

    def test_foreign_project_context_is_rejected(self):
        other = self.container.identity_service.create_user("other@example.com", "Other", "other correct horse")
        foreign = self.container.project_service.create_project("Foreign", owner_principal_id=other.id, selected_methods=("DESK",))
        response = self.client.post("/ui/feedback", data={"category": "unclear", "message": "Потрібна допомога з цим чужим проєктом.", "project_id": foreign.id})
        self.assertEqual(response.status_code, 400); self.assertIn("Контекст проєкту недоступний", response.text)

    def test_unauthenticated_feedback_redirects_to_login(self):
        self.client.post("/ui/logout")
        response = self.client.post("/ui/feedback", data={"category": "unclear", "message": "Це повідомлення не повинно бути прийняте."}, follow_redirects=False)
        self.assertEqual(response.status_code, 303); self.assertTrue(response.headers["location"].startswith("/ui/login"))

    @patch("api.routers.ui_identity.record_feedback")
    def test_viewer_can_submit_feedback_without_gaining_mutation(self, record):
        self.client.post(f"/ui/projects/{self.project_id}/members", data={"user_id": self.viewer.id, "role": "VIEWER"})
        self.client.post("/ui/logout"); self.client.post("/ui/login", data={"email": "viewer@example.com", "password": "another correct horse"})
        response = self.client.post("/ui/feedback", data={"category": "suggestion", "message": "Додайте коротше пояснення наступного кроку.", "project_id": self.project_id})
        self.assertEqual(response.status_code, 200); self.assertEqual(record.call_args.args[0].role, "VIEWER")
        denied = self.client.post(f"/ui/projects/{self.project_id}/methods", data={"method": "QUANTITATIVE"})
        self.assertEqual(denied.status_code, 404)


if __name__ == "__main__": unittest.main()
