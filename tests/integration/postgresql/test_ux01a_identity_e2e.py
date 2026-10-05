import unittest

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.app import create_fastapi_app
from application.composition_root import create_application_container
from application.identity import ProjectMembership, ProjectRole
from application.persistence.exceptions import EntityNotFoundError
from datetime import UTC, datetime
from infrastructure.persistence.postgresql.models.project_activity_model import ProjectActivityModel
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class UX01AIdentityPostgreSQLE2E(PostgreSQLIntegrationTestCase):
    def _container(self):
        return create_application_container(config=postgresql_application_config())

    def test_browser_identity_membership_attribution_and_restart(self):
        container = self._container()
        alice = container.identity_service.create_user(
            "ux01a-alice@example.test", "Alice Pilot", "correct horse battery"
        )
        bob = container.identity_service.create_user(
            "ux01a-bob@example.test", "Bob Researcher", "another correct horse"
        )
        with TestClient(create_fastapi_app(container=container)) as client:
            self.assertEqual(client.post("/ui/login", data={
                "email": alice.email, "password": "correct horse battery"
            }, follow_redirects=False).status_code, 303)
            created = client.post("/ui/projects", data={
                "name": "UX-01A PostgreSQL Project", "selected_methods": "DESK"
            }, follow_redirects=False)
            self.assertEqual(created.status_code, 303)
            project_id = created.headers["location"].rsplit("/", 1)[-1]
            self.assertEqual(
                container.identity_service.store.get_membership(project_id, alice.id).role.value,
                "OWNER",
            )
            client.post(f"/ui/projects/{project_id}/members", data={
                "user_id": bob.id, "role": "RESEARCHER"
            })
            alice_token = client.cookies.get("ai_research_os_session")
            client.post("/ui/logout")
            client.post("/ui/login", data={
                "email": bob.email, "password": "another correct horse"
            })
            self.assertIn("UX-01A PostgreSQL Project", client.get("/ui/projects").text)
            self.assertEqual(client.post(f"/ui/projects/{project_id}/methods", data={
                "method": "QUALITATIVE"
            }, follow_redirects=False).status_code, 303)
            self.assertEqual(client.post(
                f"/ui/projects/{project_id}/methods/QUALITATIVE/activate",
                follow_redirects=False,
            ).status_code, 303)
            with self.session_factory.session() as session:
                event = session.scalar(select(ProjectActivityModel).where(
                    ProjectActivityModel.project_id == project_id,
                    ProjectActivityModel.event_type == "QUAL_RUN_CREATED",
                ))
                self.assertIsNotNone(event)
                self.assertEqual(event.actor_id, bob.id)
            client.post("/ui/logout")
            client.post("/ui/login", data={
                "email": alice.email, "password": "correct horse battery"
            })
            client.post(f"/ui/projects/{project_id}/members/{bob.id}/role", data={"role": "VIEWER"})
            client.post("/ui/logout")
            client.post("/ui/login", data={
                "email": bob.email, "password": "another correct horse"
            })
            self.assertEqual(client.post(f"/ui/projects/{project_id}/methods", data={
                "method": "QUANTITATIVE"
            }).status_code, 404)
            client.post("/ui/logout")
            client.post("/ui/login", data={
                "email": alice.email, "password": "correct horse battery"
            })
            client.post(f"/ui/projects/{project_id}/members/{bob.id}/remove")
            client.post("/ui/logout")
            client.post("/ui/login", data={
                "email": bob.email, "password": "another correct horse"
            })
            self.assertEqual(client.get(f"/ui/projects/{project_id}").status_code, 404)

        container.shutdown()
        restarted = self._container()
        try:
            with TestClient(create_fastapi_app(container=restarted)) as client:
                client.cookies.set("ai_research_os_session", alice_token, path="/ui")
                self.assertEqual(client.get(f"/ui/projects/{project_id}").status_code, 200)
                self.assertIsNone(restarted.identity_service.store.get_membership(project_id, bob.id))
        finally:
            restarted.shutdown()

    def test_project_and_first_owner_are_one_transaction(self):
        container = self._container()
        try:
            project = container.project_service.build_project(
                "Atomic owner", owner_principal_id="missing-user",
                selected_methods=("DESK",),
            )
            membership = ProjectMembership(
                project.id, "missing-user", ProjectRole.OWNER,
                datetime.now(UTC), "missing-user",
            )
            with self.assertRaises(IntegrityError):
                container.identity_service.store.create_owned_project(project, membership)
            with self.assertRaises(EntityNotFoundError):
                container.project_service.get_project(project.id)
        finally:
            container.shutdown()


if __name__ == "__main__":
    unittest.main()
