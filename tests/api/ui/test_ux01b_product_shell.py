import unittest

from fastapi.testclient import TestClient

from api.app import create_fastapi_app
from tests.api.helpers import build_test_container


class Ux01bProductShellTests(unittest.TestCase):
    def setUp(self):
        self.container = build_test_container()
        delattr(self.container, "_test_api_key_plaintext")
        self.owner = self.container.identity_service.create_user(
            "owner@example.com", "Olena Owner", "correct horse battery"
        )
        self.viewer = self.container.identity_service.create_user(
            "viewer@example.com", "Viktor Viewer", "another correct horse"
        )
        self.context = TestClient(create_fastapi_app(container=self.container))
        self.client = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.container.shutdown()

    def login(self, email, password):
        return self.client.post(
            "/ui/login", data={"email": email, "password": password},
            follow_redirects=False,
        )

    def logout(self):
        self.client.post("/ui/logout", follow_redirects=False)

    def test_shell_context_next_action_and_owner_access_are_discoverable(self):
        self.login("owner@example.com", "correct horse battery")
        created = self.client.post(
            "/ui/projects",
            data={"name": "Pilot Journey", "selected_methods": "DESK"},
            follow_redirects=False,
        )
        project_id = created.headers["location"].rsplit("/", 1)[-1]
        listing = self.client.get("/ui/projects").text
        self.assertIn("Наступний крок:", listing)
        self.assertIn("Pilot Journey", listing)
        page = self.client.get(f"/ui/projects/{project_id}").text
        for label in ("Огляд", "Результати", "Активність", "Доступ до проєкту"):
            self.assertIn(label, page)
        self.assertIn("Власник", page)

    def test_viewer_sees_context_without_mutation_or_access_management(self):
        self.login("owner@example.com", "correct horse battery")
        created = self.client.post(
            "/ui/projects",
            data={"name": "Read-only Project", "selected_methods": "DESK"},
            follow_redirects=False,
        )
        project_id = created.headers["location"].rsplit("/", 1)[-1]
        self.client.post(
            f"/ui/projects/{project_id}/members",
            data={"user_id": self.viewer.id, "role": "VIEWER"},
        )
        self.logout()
        self.login("viewer@example.com", "another correct horse")
        page = self.client.get(f"/ui/projects/{project_id}").text
        self.assertIn("Перегляд", page)
        self.assertIn("Переглянути дослідження", page)
        self.assertNotIn("Доступ до проєкту", page)
        self.assertNotIn("+ Додати метод", page)
        self.assertNotIn("Додати бриф", page)
        denied = self.client.post(
            f"/ui/projects/{project_id}/methods", data={"method": "QUALITATIVE"}
        )
        self.assertEqual(denied.status_code, 404)

    def test_key_shell_pages_do_not_expose_architecture_vocabulary(self):
        self.login("owner@example.com", "correct horse battery")
        created = self.client.post(
            "/ui/projects",
            data={"name": "Vocabulary Project", "selected_methods": "DESK"},
            follow_redirects=False,
        )
        project_id = created.headers["location"].rsplit("/", 1)[-1]
        text = " ".join((
            self.client.get("/ui/projects").text,
            self.client.get(f"/ui/projects/{project_id}").text,
            self.client.get(f"/ui/projects/{project_id}/outputs").text,
        )).casefold()
        for forbidden in (
            "canonical authority", "lifecycle envelope", "provenance envelope",
            "execution authority", "materialization", "currentness",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
