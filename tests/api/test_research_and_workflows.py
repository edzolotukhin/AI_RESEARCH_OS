from __future__ import annotations

import unittest

from tests.api.helpers import ApiTestCase, drain_background_runs

BRIEF = {
    "client": "Purina",
    "project_title": "Brand Health 2026",
    "business_problem": "Assess market position.",
    "research_goal": "Evaluate brand awareness.",
}


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
