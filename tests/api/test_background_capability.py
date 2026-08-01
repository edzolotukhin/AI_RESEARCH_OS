from __future__ import annotations

import unittest
from unittest.mock import patch

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from tests.api.helpers import ApiTestCase, build_test_container, close_test_client, drain_background_runs, open_test_client

BRIEF = {
    "client": "Purina",
    "project_title": "Brand Health 2026",
    "business_problem": "Assess market position.",
    "research_goal": "Evaluate brand awareness.",
}


class HttpBackgroundCapabilityTests(ApiTestCase):

    def test_memory_embedded_execution_returns_202(self) -> None:
        project = self.client.post("/projects", json={"name": "Embedded"}).json()
        response = self.client.post(
            f"/projects/{project['id']}/research",
            json={"brief": BRIEF},
        )
        self.assertEqual(response.status_code, 202)

    def test_memory_without_embedded_execution_returns_409(self) -> None:
        container = build_test_container(
            persistence_backend="memory",
            background_execution_mode="disabled",
        )
        client, _, context = open_test_client(container)
        try:
            project = client.post("/projects", json={"name": "No Consumer"}).json()
            response = client.post(
                f"/projects/{project['id']}/research",
                json={"brief": BRIEF},
            )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.json()["error"]["code"],
                "durable_execution_unavailable",
            )
        finally:
            close_test_client(context, container)

    def test_file_backend_research_returns_409(self) -> None:
        container = build_test_container(persistence_backend="file")
        client, _, context = open_test_client(container)
        try:
            project = client.post("/projects", json={"name": "File Backend"}).json()
            response = client.post(
                f"/projects/{project['id']}/research",
                json={"brief": BRIEF},
            )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.json()["error"]["code"],
                "durable_execution_unavailable",
            )
        finally:
            close_test_client(context, container)

    def test_research_does_not_invoke_workflow_engine_in_request(self) -> None:
        project = self.client.post("/projects", json={"name": "No Engine"}).json()
        with patch.object(
            self.container.agency._workflow_engine,
            "run",
            wraps=self.container.agency._workflow_engine.run,
        ) as run_mock:
            response = self.client.post(
                f"/projects/{project['id']}/research",
                json={"brief": BRIEF},
            )
            self.assertEqual(response.status_code, 202)
            run_mock.assert_not_called()
            drain_background_runs(self.container)
            run_mock.assert_called()

    def test_memory_without_embedded_does_not_invoke_workflow_engine(self) -> None:
        container = build_test_container(
            persistence_backend="memory",
            background_execution_mode="disabled",
        )
        client, _, context = open_test_client(container)
        try:
            project = client.post("/projects", json={"name": "No Engine"}).json()
            with patch.object(
                container.agency._workflow_engine,
                "run",
                wraps=container.agency._workflow_engine.run,
            ) as run_mock:
                response = client.post(
                    f"/projects/{project['id']}/research",
                    json={"brief": BRIEF},
                )
                self.assertEqual(response.status_code, 409)
                run_mock.assert_not_called()
        finally:
            close_test_client(context, container)


class WorkerStartupCapabilityTests(unittest.TestCase):

    def test_worker_refuses_memory_backend(self) -> None:
        container = create_application_container(
            config=ApplicationConfig(
                persistence_backend="memory",
                background_execution_mode="embedded",
            ),
            overrides=ApplicationOverrides(),
        )
        try:
            self.assertIsNotNone(container.background_execution)
            assert container.background_execution is not None
            self.assertFalse(container.background_execution.multi_process_worker)
        finally:
            container.shutdown()


if __name__ == "__main__":
    unittest.main()
