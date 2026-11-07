"""DR-05 end-to-end deterministic analysis test."""

from __future__ import annotations

import unittest

from application.composition_root import create_application_container
from application.exceptions.capability_not_implemented_error import (
    CapabilityNotImplementedError,
)
from application.executors.stage_executors import UnimplementedCapabilityExecutor
from application.query.research_run_result import ResearchRunOutcome
from application.research_quality.readiness_result_codec import extract_research_product_outcome
from application.report.exceptions import ReportError

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import (
    activate_approved_desk_project,
    AuthenticatedTestClient,
    close_test_client,
    drain_background_runs,
    open_test_client,
)
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.helpers.dated_desk_integration_fixture import dated_desk_overrides
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class Dr05EndToEndPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_deterministic_pipeline_persists_findings_before_report_failure(self) -> None:
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
            ),
            overrides=dated_desk_overrides(
                llm_client=mock_llm,
                report_executor=UnimplementedCapabilityExecutor(
                    capability="report",
                    stage="write_report",
                ),
            ),
        )
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        client = AuthenticatedTestClient(raw_client, auth_headers(
            container._test_api_key_plaintext,
        ))

        project_id = client.post("/projects", json={"name": "DR-05 E2E"}).json()["id"]
        run_id = activate_approved_desk_project(container, project_id, BRIEF).id

        with self.assertRaises(CapabilityNotImplementedError) as exc:
            drain_background_runs(container)
        self.assertEqual(exc.exception.capability, "report")

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        tasks = {task["definition_id"]: task["status"] for task in terminal["tasks"]}
        self.assertEqual(tasks["task-collect-evidence"], "completed")
        self.assertEqual(tasks["task-extract-evidence"], "completed")
        self.assertEqual(tasks["task-assess-research-readiness"], "completed")
        self.assertEqual(tasks["task-analyze"], "completed")
        self.assertEqual(tasks["task-write-report"], "failed")
        self.assertEqual(terminal["status"], "failed")
        self.assertTrue(terminal["findings_available"])
        self.assertGreater(terminal["finding_count"], 0)
        self.assertTrue(terminal["insights_available"])
        self.assertGreater(terminal["insight_count"], 0)
        self.assertFalse(terminal["artifacts_available"])

        findings = client.get(
            f"/projects/{project_id}/findings",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        insights = client.get(
            f"/projects/{project_id}/insights",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        evidence = client.get(
            f"/projects/{project_id}/evidence",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        sources = client.get(
            f"/projects/{project_id}/sources",
            params={"workflow_run_id": run_id},
        ).json()["items"]

        self.assertGreater(len(findings), 0)
        self.assertGreater(len(insights), 0)
        for finding in findings:
            self.assertEqual(finding["workflow_run_id"], run_id)
            self.assertTrue(finding["evidence_refs"])
            for evidence_id in finding["evidence_refs"]:
                self.assertTrue(any(item["id"] == evidence_id for item in evidence))
        for insight in insights:
            self.assertEqual(insight["workflow_run_id"], run_id)
            self.assertTrue(insight["finding_refs"])
            for finding_id in insight["finding_refs"]:
                self.assertTrue(any(item["id"] == finding_id for item in findings))
        for item in evidence:
            self.assertTrue(any(source["id"] == item["source_id"] for source in sources))

    def test_real_report_executor_failure_persists_failed_outcome_after_reload(self) -> None:
        class RaisingReportEngine:
            method_name = "deterministic-raising"

            def generate_claim_candidates(self, request):
                raise RuntimeError("synthetic report generation failure")

        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
            ),
            overrides=dated_desk_overrides(
                llm_client=mock_llm,
                report_engine=RaisingReportEngine(),
            ),
        )
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        client = AuthenticatedTestClient(raw_client, auth_headers(
            container._test_api_key_plaintext,
        ))

        project_id = client.post("/projects", json={"name": "DR-05 real failure"}).json()["id"]
        run_id = activate_approved_desk_project(container, project_id, BRIEF).id
        with self.assertRaises(ReportError):
            drain_background_runs(container)

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        self.assertEqual(terminal["status"], "failed")
        self.assertGreater(terminal["finding_count"], 0)
        self.assertGreater(terminal["evidence_count"], 0)
        task_results = container.workflow_service.get_task_results(run_id)
        persisted = extract_research_product_outcome(task_results)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["outcome"], "FAILED")

        fresh = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
            ),
        )
        self.addCleanup(fresh.shutdown)
        fresh_task_results = fresh.workflow_service.get_task_results(run_id)
        failed_report_snapshots = [
            snapshot
            for snapshot in fresh_task_results.values()
            if isinstance(snapshot, dict)
            and snapshot.get("definition_id") == "task-write-report"
        ]
        self.assertEqual(len(failed_report_snapshots), 1)
        failed_report = failed_report_snapshots[0]
        fresh_run = fresh.workflow_service.get_workflow_run(run_id)
        failed_report_tasks = [
            task for task in fresh_run.tasks
            if task.definition_id == "task-write-report"
        ]
        self.assertEqual(len(failed_report_tasks), 1)
        self.assertEqual(failed_report_tasks[0].status.value, "failed")
        diagnostics = failed_report.get("shared_state", {}).get(
            "report_generation_diagnostics",
        )
        self.assertIsInstance(diagnostics, dict)
        self.assertTrue(diagnostics)
        self.assertEqual(diagnostics.get("status"), "failed")
        self.assertEqual(diagnostics.get("phase"), "claim_first_validation")
        self.assertEqual(diagnostics.get("category"), "ClaimGenerationError")
        self.assertIn("version", diagnostics)
        self.assertIn("workflow_run_id", diagnostics)
        self.assertEqual(
            failed_report["shared_state"]["research_product_outcome"]["outcome"],
            "FAILED",
        )
        self.assertEqual(
            fresh.report_query_service.list_reports_for_project(
                project_id, workflow_run_id=run_id,
            ),
            [],
        )
        self.assertEqual(fresh.artifact_service.count_for_run(project_id, run_id), 0)
        reloaded = fresh.research_run_result_query_service.get_for_run(run_id)
        self.assertEqual(reloaded.outcome, ResearchRunOutcome.FAILED)


if __name__ == "__main__":
    unittest.main()
