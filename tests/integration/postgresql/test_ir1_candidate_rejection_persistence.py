import unittest

from application.composition_root import create_application_container
from application.evidence.evidence_extraction_diagnostics import EvidenceExtractionDiagnostics
from application.evidence.evidence_result_codec import extract_candidate_rejection_diagnostics
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from application.config import ApplicationOverrides
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion

from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class IR1CandidateRejectionPersistencePostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_candidate_rejections_reload_and_deduplicate_from_task_snapshots(self) -> None:
        config = postgresql_application_config()
        container = create_application_container(config=config, overrides=ApplicationOverrides())

        project = container.project_service.create_project("IR1 diagnostics")
        design = ResearchDesign(
            id="ir1-diagnostics-design",
            research_questions=(ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),),
            information_needs=(InformationNeed(id="in-1", research_question_id="rq-1", description="N1"),),
        )
        template = ResearchDesignWorkflowMapper().from_research_design(design, project)
        container.workflow_service.publish_template_snapshot(template, project_id=project.id)
        run = container.workflow_service.create_workflow_run(
            template,
            project_id=project.id,
            run_id="ir1-diagnostics-persistence",
        )

        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id=run.id)
        for index in range(5):
            diagnostics.record_candidate_rejection(
                source_id="source-1",
                information_need_id="in-1",
                operation_id=f"operation-{index}",
                candidate_index=index,
                validation_phase="provenance",
                rejection_code="semantic_excerpt_mismatch",
                contract_version="desk_evidence_candidate_v2",
            )
        payload = {"diagnostics": diagnostics.to_dict()}

        def update(task_results):
            task_results["task-a"] = {"shared_state": {"evidence_extraction": payload}}
            task_results["task-b"] = {"shared_state": {"evidence_extraction": payload}}
            return task_results, None

        try:
            container.workflow_service.atomic_update_task_results(run.id, update)
        finally:
            container.shutdown()

        fresh = create_application_container(config=config, overrides=ApplicationOverrides())
        self.addCleanup(fresh.shutdown)
        reloaded = fresh.workflow_service.get_task_results(run.id)
        records = extract_candidate_rejection_diagnostics(reloaded)
        self.assertEqual(len(records), 5)
        self.assertEqual([item["candidate_index"] for item in records], list(range(5)))
        self.assertTrue(all("source_excerpt" not in item and "statement" not in item for item in records))


if __name__ == "__main__":
    unittest.main()
