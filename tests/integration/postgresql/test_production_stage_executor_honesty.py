"""PostgreSQL integration test for production stage executor honesty."""

from __future__ import annotations

import unittest

from application.composition_root import create_application_container
from application.query.research_run_result import ResearchRunOutcome
from application.research_quality.readiness_result_codec import (
    extract_research_product_outcome,
    extract_research_readiness,
)
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
    def test_production_runtime_persists_insufficient_outcome_after_reload(self) -> None:
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

        class NoFindingAnalysisEngine(DeterministicAnalysisEngine):
            method_name = "deterministic-no-findings"

            def analyze_findings(self, analysis_input):
                return []

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
                analysis_engine=NoFindingAnalysisEngine(),
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

        project_id = client.post(
            "/projects", json={"name": "PG DR insufficient outcome"},
        ).json()["id"]
        run_id = activate_approved_desk_project(
            container, project_id, PARTIAL_BRIEF,
        ).id
        drain_background_runs(container)

        workflow_run = container.workflow_service.get_workflow_run(run_id)
        template = container.workflow_service.get_template(workflow_run.workflow_template_id)
        required_need_ids = {
            item.id
            for item in template.research_design_snapshot.information_needs
        }
        self.assertTrue(required_need_ids)
        task_results = container.workflow_service.get_task_results(run_id)
        readiness = extract_research_readiness(task_results)
        persisted_outcome = extract_research_product_outcome(task_results)
        coverage_snapshots = [
            snapshot["shared_state"]["analysis_coverage"]
            for snapshot in task_results.values()
            if isinstance(snapshot, dict)
            and "analysis_coverage" in snapshot.get("shared_state", {})
        ]
        self.assertTrue(
            coverage_snapshots,
            f"Persisted analysis_coverage missing; task result keys={tuple(task_results)}",
        )
        analysis_coverage = coverage_snapshots[0]
        self.assertFalse(analysis_coverage["fully_covered"])
        self.assertEqual(
            set(analysis_coverage["missing_information_need_ids"]),
            required_need_ids - {template.research_design_snapshot.information_needs[0].id},
        )
        evidence = container.evidence_service.list_evidence_for_project(project_id, workflow_run_id=run_id)
        findings = container.finding_service.list_findings_for_project(project_id, workflow_run_id=run_id)
        self.assertEqual(findings, [])

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        self.assertTrue(terminal["is_terminal"])
        self.assertEqual(terminal["status"], "completed")
        tasks = {item["definition_id"]: item["status"] for item in terminal["tasks"]}
        self.assertEqual(tasks["task-assess-research-readiness"], "completed")
        self.assertEqual(tasks["task-analyze"], "completed")
        self.assertEqual(tasks["task-write-report"], "skipped")
        self.assertEqual(
            extract_research_product_outcome(
                container.workflow_service.get_task_results(run_id),
            )["outcome"],
            "INSUFFICIENT",
        )
        self.assertEqual(
            container.report_query_service.list_reports_for_project(
                project_id, workflow_run_id=run_id,
            ),
            [],
        )
        self.assertEqual(container.artifact_service.count_for_run(project_id, run_id), 0)

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
        fresh_task_results = fresh.workflow_service.get_task_results(run_id)
        fresh_run = fresh.workflow_service.get_workflow_run(run_id)
        fresh_tasks = {
            task.definition_id: task.status.value for task in fresh_run.tasks
        }
        self.assertEqual(fresh_tasks["task-analyze"], "completed")
        self.assertEqual(fresh_tasks["task-write-report"], "skipped")
        for definition_id in (
            "task-review-report",
            "task-revise-report",
            "task-finalize-deliverables",
        ):
            if definition_id in fresh_tasks:
                self.assertEqual(fresh_tasks[definition_id], "skipped")
        fresh_persisted = extract_research_product_outcome(fresh_task_results)
        self.assertEqual(fresh_persisted["outcome"], "INSUFFICIENT")
        fresh_coverage_snapshots = [
            snapshot["shared_state"]["analysis_coverage"]
            for snapshot in fresh_task_results.values()
            if isinstance(snapshot, dict)
            and "analysis_coverage" in snapshot.get("shared_state", {})
        ]
        self.assertTrue(
            fresh_coverage_snapshots,
            f"Fresh-container analysis_coverage missing; task result keys={tuple(fresh_task_results)}",
        )
        fresh_analysis_coverage = fresh_coverage_snapshots[0]
        self.assertEqual(fresh_analysis_coverage, analysis_coverage)
        self.assertEqual(
            set(fresh_persisted["unresolved_information_need_ids"]),
            required_need_ids,
        )
        self.assertEqual(fresh.artifact_service.count_for_run(project_id, run_id), 0)
        result = fresh.research_run_result_query_service.get_for_run(run_id)
        self.assertEqual(result.outcome, ResearchRunOutcome.INSUFFICIENT)
        self.assertEqual(
            set(result.readiness.blocking_information_need_ids),
            required_need_ids
            - {template.research_design_snapshot.information_needs[0].id},
        )
        self.assertEqual(
            set(persisted_outcome["unresolved_information_need_ids"]),
            required_need_ids,
        )

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

        workflow_run = container.workflow_service.get_workflow_run(run_id)
        template = container.workflow_service.get_template(
            workflow_run.workflow_template_id,
        )
        design = template.research_design_snapshot
        required_need_ids = {
            item.id for item in design.information_needs
        }
        self.assertTrue(required_need_ids)

        def assert_persisted_integrity(findings, evidence):
            finding_ids = [item.id for item in findings]
            evidence_ids = [item.id for item in evidence]
            self.assertEqual(len(finding_ids), len(set(finding_ids)))
            self.assertEqual(len(evidence_ids), len(set(evidence_ids)))
            evidence_by_id = {item.id: item for item in evidence}
            covered_need_ids = set()
            for finding in findings:
                self.assertEqual(finding.project_id, project_id)
                self.assertEqual(finding.workflow_run_id, run_id)
                self.assertEqual(finding.research_design_id, design.id)
                self.assertEqual(
                    finding.metadata.get("validation_status"),
                    "validated",
                )
                self.assertTrue(finding.information_need_refs)
                self.assertTrue(finding.evidence_refs)
                self.assertTrue(
                    set(finding.information_need_refs) <= required_need_ids,
                )
                covered_need_ids.update(finding.information_need_refs)
                for evidence_id in finding.evidence_refs:
                    self.assertIn(evidence_id, evidence_by_id)
                    cited = evidence_by_id[evidence_id]
                    self.assertEqual(cited.project_id, project_id)
                    self.assertEqual(cited.workflow_run_id, run_id)
                    self.assertEqual(cited.research_design_id, design.id)
                    self.assertTrue(
                        set(finding.information_need_refs)
                        & set(cited.information_need_refs),
                    )
            self.assertEqual(covered_need_ids, required_need_ids)

        persisted_findings = container.finding_service.list_findings_for_project(
            project_id, workflow_run_id=run_id,
        )
        persisted_evidence = container.evidence_service.list_evidence_for_project(
            project_id, workflow_run_id=run_id,
        )
        assert_persisted_integrity(persisted_findings, persisted_evidence)

        persisted_results = container.workflow_service.get_task_results(run_id)
        from application.research_quality.readiness_result_codec import extract_research_product_outcome
        persisted_outcome_payload = extract_research_product_outcome(persisted_results)
        persisted_outcome = persisted_outcome_payload["outcome"]
        reloaded_result = container.research_run_result_query_service.get_for_run(run_id)
        self.assertEqual(persisted_outcome, "COMPLETED")
        self.assertEqual(
            set(persisted_outcome_payload["unresolved_information_need_ids"]),
            set(),
        )
        self.assertEqual(reloaded_result.outcome.value, persisted_outcome)

        tasks = {task["definition_id"]: task["status"] for task in terminal["tasks"]}
        self.assertEqual(tasks["task-collect-evidence"], "completed")
        self.assertEqual(tasks["task-extract-evidence"], "completed")
        self.assertEqual(tasks["task-assess-research-readiness"], "completed")
        self.assertEqual(tasks["task-analyze"], "completed")
        self.assertEqual(tasks["task-write-report"], "completed")
        self.assertEqual(tasks["task-review-report"], "completed")

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
        fresh_findings = fresh.finding_service.list_findings_for_project(
            project_id, workflow_run_id=run_id,
        )
        fresh_evidence = fresh.evidence_service.list_evidence_for_project(
            project_id, workflow_run_id=run_id,
        )
        self.assertEqual(
            {item.id for item in fresh_findings},
            {item.id for item in persisted_findings},
        )
        self.assertEqual(
            {item.id for item in fresh_evidence},
            {item.id for item in persisted_evidence},
        )
        assert_persisted_integrity(fresh_findings, fresh_evidence)
        fresh_outcome_payload = extract_research_product_outcome(
            fresh.workflow_service.get_task_results(run_id),
        )
        self.assertEqual(fresh_outcome_payload["outcome"], "COMPLETED")
        self.assertEqual(
            set(fresh_outcome_payload["unresolved_information_need_ids"]),
            set(),
        )
        self.assertEqual(
            fresh.research_run_result_query_service.get_for_run(run_id).outcome,
            ResearchRunOutcome.COMPLETED,
        )

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
        self.assertIn(
            required_need_ids[1],
            reloaded.readiness.blocking_information_need_ids,
        )
        self.assertNotEqual(reloaded.outcome, ResearchRunOutcome.COMPLETED)


if __name__ == "__main__":
    unittest.main()
