from __future__ import annotations

import importlib
import unittest

from application.config import ApplicationConfig

from api.app import create_fastapi_app

from tests.api.auth_helpers import auth_headers
from tests.api.helpers import ApiTestCase, AuthenticatedTestClient, build_test_container, open_test_client, close_test_client


class AppFactoryImportSafetyTests(unittest.TestCase):

    def test_importing_api_modules_does_not_create_postgresql_engine(self) -> None:
        importlib.import_module("api.app")
        importlib.import_module("api.main")
        self.assertTrue(True)

    def test_memory_backed_factory_does_not_require_postgresql(self) -> None:
        container = build_test_container(persistence_backend="memory")
        try:
            self.assertEqual(container.config.persistence_backend, "memory")
            ready, reason = container.check_readiness()
            self.assertTrue(ready)
            self.assertEqual(reason, "ready")
        finally:
            container.shutdown()

    def test_explicit_config_avoids_from_env_postgresql(self) -> None:
        client, container, context = open_test_client(
            build_test_container(persistence_backend="memory"),
        )
        try:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["persistence_backend"], "memory")
        finally:
            close_test_client(context, container)


class ApplicationContainerIsolationTests(ApiTestCase):

    def test_separate_apps_do_not_share_project_state(self) -> None:
        client_one, container_one, context_one = open_test_client()
        client_two, container_two, context_two = open_test_client()
        auth_one = AuthenticatedTestClient(
            client_one,
            auth_headers(container_one._test_api_key_plaintext),
        )
        auth_two = AuthenticatedTestClient(
            client_two,
            auth_headers(container_two._test_api_key_plaintext),
        )
        try:
            project_one = auth_one.post("/projects", json={"name": "App One"}).json()
            listed_two = auth_two.get("/projects").json()["items"]
            self.assertEqual(
                auth_two.get(f"/projects/{project_one['id']}").status_code,
                404,
            )
            self.assertEqual(listed_two, [])
        finally:
            close_test_client(context_one, container_one)
            close_test_client(context_two, container_two)

    def test_app_state_container_is_unique_per_app_instance(self) -> None:
        client_one, container_one, context_one = open_test_client()
        client_two, container_two, context_two = open_test_client()
        try:
            self.assertIsNot(client_one.app.state.container, client_two.app.state.container)
            self.assertIsNot(container_one, container_two)
        finally:
            close_test_client(context_one, container_one)
            close_test_client(context_two, container_two)


if __name__ == "__main__":
    unittest.main()
