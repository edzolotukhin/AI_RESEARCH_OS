from dataclasses import replace
from types import SimpleNamespace as NS
from uuid import uuid4
from unittest.mock import Mock
from application.config import ApplicationConfig, ApplicationOverrides
from application.evidence.evidence_factory import build_evidence_extraction_service

from application.parsers.research_design_parser import ResearchDesignParser
from application.factories.research_design_factory import ResearchDesignFactory
from application.methods.desk.adapter import DeskAdapter, ASSESSMENT
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.deterministic_research_sufficiency_evaluator import DeterministicResearchSufficiencyEvaluator
from domain.factories.project_factory import ProjectFactory
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_template_repository import PostgreSQLWorkflowTemplateRepository
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase
from tests.application.analysis.test_executable_derivations import derived_design, setup_memory
from tests.application.research_quality.test_phase1_qualification_parity import assessment


class Phase1PostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_legacy_unit_omission_survives_reload_and_fails_closed(self):
        from domain.planning.research_design import ResearchDesign
        from domain.workflow_template import WorkflowTemplate
        from runtime.workflow_context import WorkflowContext

        payload = derived_design().to_dict()
        del payload["information_needs"][0]["evidence_coverage"]["required_unit"]
        legacy = ResearchDesign.from_dict(payload)
        project = ProjectFactory().create("Legacy Phase 1")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        template = WorkflowTemplate(str(uuid4()), "Legacy", (), research_design_snapshot=legacy)
        PostgreSQLWorkflowTemplateRepository(self.session_factory).save_snapshot(template, project_id=project.id)
        fresh = DatabaseSessionFactory(self.engine)
        loaded = PostgreSQLWorkflowTemplateRepository(fresh).get_by_id(template.id)
        self.assertEqual(loaded.research_design_snapshot.to_dict(), payload)
        context = WorkflowContext(project=project, workflow_template=loaded, workflow_run=NS(id="run"))
        service = ResearchReadinessService(
            evaluator=DeterministicResearchSufficiencyEvaluator(),
            source_repository=PostgreSQLSourceRepository(fresh),
            evidence_repository=PostgreSQLEvidenceRepository(fresh),
        )
        result = service.qualification_for_context(context)[1].qualifications["in-pop"]
        self.assertFalse(result.available)
        self.assertIn("numeric_requirements_unavailable", result.rejection_reason_counts)

    def test_planner_frozen_reload_and_canonical_parity(self):
        original = derived_design()
        typed = ResearchDesignFactory().create(
            ResearchDesignParser().parse(original.to_dict()), research_subject=original.research_subject,
        )
        typed = replace(typed, id=original.id)
        context, _, _, memory_evidence, memory_sources, _ = setup_memory(model=typed)
        project = ProjectFactory().create("Isolated Phase 1")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        sources = PostgreSQLSourceRepository(self.session_factory)
        evidence = PostgreSQLEvidenceRepository(self.session_factory)
        for source in memory_sources.list_for_project("project"):
            sources.create(replace(source, project_id=project.id))
        context.project = project
        build_evidence_extraction_service(
            config=ApplicationConfig(evidence_extractor="llm"),
            overrides=ApplicationOverrides(), source_repository=sources,
            evidence_repository=evidence, llm_client=Mock(),
        ).extract_for_source_ids(context, ("source",), allow_empty=True)
        expected_ids = {e.id for e in evidence.list_for_project(project.id)}
        self.assertEqual(len(expected_ids), 3)
        before = ResearchReadinessService(
            evaluator=DeterministicResearchSufficiencyEvaluator(),
            source_repository=sources, evidence_repository=evidence,
        ).qualification_for_context(context)
        template = replace(context.workflow_template, id=str(uuid4()))
        PostgreSQLWorkflowTemplateRepository(self.session_factory).save_snapshot(template, project_id=project.id)
        fresh = DatabaseSessionFactory(self.engine)
        loaded = PostgreSQLWorkflowTemplateRepository(fresh).get_by_id(template.id)
        self.assertEqual(loaded.research_design_snapshot.to_dict(), typed.to_dict())
        context.project = project
        context.workflow_template = loaded
        sources = PostgreSQLSourceRepository(fresh)
        evidence = PostgreSQLEvidenceRepository(fresh)
        service = ResearchReadinessService(
            evaluator=DeterministicResearchSufficiencyEvaluator(),
            source_repository=sources, evidence_repository=evidence,
        )
        adapter = DeskAdapter(context, NS(source_acquisition_max_seconds=60),
            NS(initial_queries=lambda: (), extraction=NS(_source_repository=sources)), service, evidence)
        temporal, projection = service.qualification_for_context(context)
        self.assertEqual(dict(temporal.decisions), dict(before[0].decisions))
        self.assertEqual(projection.qualifications["in-pop"].observations,
                         before[1].qualifications["in-pop"].observations)
        print("Reload temporal decisions", sorted(temporal.decisions.values()),
              "numeric rejection counts", dict(projection.qualifications["in-pop"].rejection_reason_counts))
        result = service.evaluate_for_context(context)
        observed = adapter.observe(NS())
        cold = adapter.last_result
        context.shared_state[ASSESSMENT] = {"fingerprint": observed.fingerprint, "result": result.to_dict()}
        adapter.observe(NS())
        warm = adapter.last_result
        terminal = service._finalize_terminal_readiness(context, warm)
        self.assertEqual(tuple(assessment(r).evidence_count for r in (result, cold, warm, terminal)), (3, 3, 3, 3))
        self.assertEqual({e.id for e in adapter.qualified()}, expected_ids)
