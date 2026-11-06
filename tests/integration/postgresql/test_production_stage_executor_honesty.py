"""PostgreSQL integration test for production stage executor honesty."""

from __future__ import annotations

import unittest

from application.composition_root import create_application_container
from application.query.research_run_result import ResearchRunOutcome
from application.research_quality.readiness_result_codec import extract_research_product_outcome
from infrastructure.analysis.deterministic_analysis_engine import DeterministicAnalysisEngine

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
from tests.helpers.dated_desk_integration_fixture import (
    DatedDeskEvidenceExtractor,
    dated_desk_overrides,
)
from tests.integration.postgresql.helpers import (
    assert_structured_finalization_complete,
    configure_structured_finalization_test_boundary,
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


PARTIAL_BRIEF = {
    **BRIEF,
    "objectives": [
        "Evaluate brand awareness.",
        "Evaluate brand consideration.",
    ],
}


class ProductionStageExecutorHonestyPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_production_runtime_completes_desk_research_pipeline(self) -> None:
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
                report_engine="deterministic",
            ),
            overrides=dated_desk_overrides(llm_client=mock_llm),
        )
        configure_structured_finalization_test_boundary(container)
        container._test_llm_client = mock_llm
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        client = AuthenticatedTestClient(raw_client, auth_headers(
            container._test_api_key_plaintext,
        ))

        project_id = client.post("/projects", json={"name": "PG DR-05 Honesty"}).json()["id"]
        run_id = activate_approved_desk_project(container, project_id, BRIEF).id

        drain_background_runs(container)

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        self.assertTrue(terminal["is_terminal"])
        self.assertEqual(terminal["status"], "completed")
        assert_structured_finalization_complete(self, container, run_id)
        self.assertTrue(terminal["sources_available"])
        self.assertGreater(terminal["source_count"], 0)
        self.assertTrue(terminal["evidence_available"])
        self.assertGreater(terminal["evidence_count"], 0)
        self.assertTrue(terminal["findings_available"])
        self.assertGreater(terminal["finding_count"], 0)
        self.assertTrue(terminal["insights_available"])
        self.assertGreater(terminal["insight_count"], 0)
        self.assertTrue(terminal["reports_available"])
        self.assertGreater(terminal["report_count"], 0)
        self.assertTrue(terminal["artifacts_available"])
        self.assertGreater(terminal["artifact_count"], 0)

        persisted_results = container.workflow_service.get_task_results(run_id)
        from application.research_quality.readiness_result_codec import extract_research_product_outcome
        persisted_outcome = extract_research_product_outcome(persisted_results)["outcome"]
        reloaded_result = container.research_run_result_query_service.get_for_run(run_id)
        self.assertEqual(persisted_outcome, "COMPLETED")
        self.assertEqual(reloaded_result.outcome.value, persisted_outcome)

        tasks = {task["definition_id"]: task["status"] for task in terminal["tasks"]}
        self.assertEqual(tasks["task-collect-evidence"], "completed")
        self.assertEqual(tasks["task-extract-evidence"], "completed")
        self.assertEqual(tasks["task-assess-research-readiness"], "completed")
        self.assertEqual(tasks["task-analyze"], "completed")
        self.assertEqual(tasks["task-write-report"], "completed")
        self.assertEqual(tasks["task-review-report"], "completed")

        sources = client.get(f"/projects/{project_id}/sources").json()["items"]
        self.assertGreater(len(sources), 0)
        self.assertTrue(all("provider" not in item.get("metadata", {}) for item in sources))

    def test_production_runtime_persists_partial_outcome_after_reload(self) -> None:
        class PartialEvidenceExtractor(DatedDeskEvidenceExtractor):
            def extract(self, *, source, design, run_context):
                first_need_id = design.information_needs[0].id
                return [
                    candidate
                    for candidate in super().extract(
                        source=source,
                        design=design,
                        run_context=run_context,
                    )
                    if candidate.information_need_refs == (first_need_id,)
                ]

        class PartialAnalysisEngine(DeterministicAnalysisEngine):
            method_name = "deterministic-partial"

            def analyze_findings(self, analysis_input):
                resolved_need_id = analysis_input.design.information_needs[0].id
                return [
                    candidate
                    for candidate in super().analyze_findings(analysis_input)
                    if candidate.information_need_refs == (resolved_need_id,)
                ]

        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
                report_engine="deterministic",
            ),
            overrides=dated_desk_overrides(
                llm_client=mock_llm,
                evidence_extractor=PartialEvidenceExtractor(),
                analysis_engine=PartialAnalysisEngine(),
            ),
        )
        configure_structured_finalization_test_boundary(container)
        container._test_llm_client = mock_llm
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        client = AuthenticatedTestClient(raw_client, auth_headers(
            container._test_api_key_plaintext,
        ))

        project_id = client.post("/projects", json={"name": "PG DR partial outcome"}).json()["id"]
        run_id = activate_approved_desk_project(container, project_id, PARTIAL_BRIEF).id
        drain_background_runs(container)

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        self.assertTrue(terminal["is_terminal"])
        self.assertEqual(terminal["status"], "completed")
        tasks = {task["definition_id"]: task["status"] for task in terminal["tasks"]}
        self.assertEqual(tasks["task-write-report"], "completed")

        task_results = container.workflow_service.get_task_results(run_id)
        persisted = extract_research_product_outcome(task_results)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["outcome"], "PARTIAL")
        workflow_run = container.workflow_service.get_workflow_run(run_id)
        template = container.workflow_service.get_template(
            workflow_run.workflow_template_id,
        )
        design = template.research_design_snapshot
        self.assertIsNotNone(design)
        required_need_ids = tuple(need.id for need in design.information_needs)
        self.assertEqual(len(required_need_ids), 2)
        self.assertIn(required_need_ids[1], persisted["unresolved_information_need_ids"])
        evidence = container.evidence_service.list_evidence_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        findings = container.finding_service.list_findings_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        self.assertGreater(len(evidence), 0)
        self.assertGreater(len(findings), 0)
        self.assertTrue(all(item.research_design_id == design.id for item in evidence))
        self.assertTrue(all(item.research_design_id == design.id for item in findings))

        fresh = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
                report_engine="deterministic",
            ),
        )
        self.addCleanup(fresh.shutdown)
        fresh_run = fresh.workflow_service.get_workflow_run(run_id)
        fresh_template = fresh.workflow_service.get_template(
            fresh_run.workflow_template_id,
        )
        self.assertEqual(fresh_template.research_design_snapshot.id, design.id)
        reloaded = fresh.research_run_result_query_service.get_for_run(run_id)
        self.assertEqual(reloaded.outcome, ResearchRunOutcome.PARTIAL)
        self.assertIn(required_need_ids[1], reloaded.blocking_information_need_ids)
        self.assertNotEqual(reloaded.outcome, ResearchRunOutcome.COMPLETED)


if __name__ == "__main__":
    unittest.main()
