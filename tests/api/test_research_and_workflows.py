from __future__ import annotations

import unittest

from tests.api.helpers import ApiTestCase, drain_background_runs

from application.exceptions.capability_not_implemented_error import (
    CapabilityNotImplementedError,
)

from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF


class ResearchEndpointTests(ApiTestCase):

    def setUp(self) -> None:
        super().setUp()
        project = self.client.post("/projects", json={"name": "Brand Health 2026"}).json()
        self.project_id = project["id"]

    def test_start_research_returns_202_accepted(self) -> None:
        response = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": BRIEF},
        )
        self.assertEqual(response.status_code, 202)
        self.assertIn("/workflow-runs/", response.headers.get("location", ""))
        payload = response.json()
        self.assertTrue(payload["run_id"])
        self.assertEqual(payload["project_id"], self.project_id)
        self.assertEqual(payload["status"], "created")

    def test_start_research_persists_durable_run(self) -> None:
        response = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": BRIEF},
        )
        run_id = response.json()["run_id"]
        reloaded = self.container.workflow_service.get_workflow_run(run_id)
        self.assertEqual(reloaded.project_id, self.project_id)

    def test_start_research_uses_injected_llm_client(self) -> None:
        self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": BRIEF},
        )
        self.container._test_llm_client.generate.assert_called()

    def test_background_worker_completes_run(self) -> None:
        response = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": BRIEF},
        )
        run_id = response.json()["run_id"]
        drain_background_runs(self.container)
        terminal = self.client.get(f"/workflow-runs/{run_id}").json()
        self.assertTrue(terminal["is_terminal"])
        self.assertEqual(terminal["status"], "completed")

    def test_production_mode_fails_on_unimplemented_report_stage(self) -> None:
        with self.subTest("honest failure after analysis completes"):
            from application.composition_root import create_application_container
            from application.config import ApplicationConfig, ApplicationOverrides
            from tests.api.helpers import close_test_client, open_test_client
            from tests.helpers.brief_aligned_planner_llm import (
                create_brief_aligned_llm_mock,
            )
            import tempfile

            with tempfile.TemporaryDirectory() as temp_dir:
                container = create_application_container(
                    config=ApplicationConfig(
                        projects_root=temp_dir,
                        persistence_backend="memory",
                        background_execution_mode="embedded",
                        deterministic_stage_executors=False,
                        search_provider="deterministic",
                        evidence_extractor="deterministic",
                        analysis_engine="deterministic",
                    ),
                    overrides=ApplicationOverrides(
                        llm_client=create_brief_aligned_llm_mock(),
                    ),
                )
                raw, _, context = open_test_client(container)
                try:
                    from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key

                    bootstrap_test_api_key(container)
                    headers = auth_headers(container._test_api_key_plaintext)
                    from tests.api.helpers import AuthenticatedTestClient

                    client = AuthenticatedTestClient(raw, headers)
                    project_id = client.post(
                        "/projects",
                        json={"name": "Honest Failure Project"},
                    ).json()["id"]
                    run_id = client.post(
                        f"/projects/{project_id}/research",
                        json={"brief": BRIEF},
                    ).json()["run_id"]
                    try:
                        drain_background_runs(container)
                    except CapabilityNotImplementedError as exc:
                        self.assertEqual(exc.capability, "report")
                    else:
                        self.fail("Expected report CapabilityNotImplementedError")
                    terminal = client.get(f"/workflow-runs/{run_id}").json()
                    self.assertTrue(terminal["is_terminal"])
                    self.assertEqual(terminal["status"], "failed")
                    tasks = {
                        task["definition_id"]: task["status"]
                        for task in terminal["tasks"]
                    }
                    self.assertEqual(tasks["task-collect-evidence"], "completed")
                    self.assertEqual(tasks["task-extract-evidence"], "completed")
                    self.assertEqual(tasks["task-analyze"], "completed")
                    self.assertEqual(tasks["task-write-report"], "failed")
                    self.assertTrue(terminal["findings_available"])
                    self.assertGreater(terminal["finding_count"], 0)
                    self.assertTrue(terminal["insights_available"])
                    self.assertGreater(terminal["insight_count"], 0)
                finally:
                    close_test_client(context, container)
                    container.shutdown()


class WorkflowRunEndpointTests(ApiTestCase):

    def setUp(self) -> None:
        super().setUp()
        project = self.client.post("/projects", json={"name": "Workflow Project"}).json()
        self.project_id = project["id"]
        started = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": BRIEF},
        ).json()
        self.run_id = started["run_id"]
        drain_background_runs(self.container)

    def test_get_workflow_run(self) -> None:
        response = self.client.get(f"/workflow-runs/{self.run_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.run_id)

    def test_get_missing_workflow_run_returns_404(self) -> None:
        response = self.client.get("/workflow-runs/missing-run")
        self.assertEqual(response.status_code, 404)

    def test_get_task_results(self) -> None:
        response = self.client.get(f"/workflow-runs/{self.run_id}/results")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run_id"], self.run_id)

    def test_get_logs_in_append_order(self) -> None:
        response = self.client.get(f"/workflow-runs/{self.run_id}/logs")
        self.assertEqual(response.status_code, 200)
        logs = response.json()["items"]
        expected = self.container.execution_log_service.list_logs_for_run(self.run_id)
        self.assertEqual(
            [entry["event_id"] for entry in logs],
            [entry.event_id for entry in expected[: len(logs)]],
        )

    def test_terminal_resume_returns_200_current_state(self) -> None:
        first_status = self.client.get(f"/workflow-runs/{self.run_id}").json()["status"]
        resumed = self.client.post(f"/workflow-runs/{self.run_id}/resume")
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["status"], first_status)

    def test_list_workflow_runs_for_project(self) -> None:
        response = self.client.get(f"/projects/{self.project_id}/workflow-runs")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.json()["count"], 1)


if __name__ == "__main__":
    unittest.main()
