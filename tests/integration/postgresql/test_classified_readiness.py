"""E2E-B: real acquisition/extraction, hybrid readiness, Analysis and coverage."""
from dataclasses import replace
from datetime import datetime, timezone
import io
import json
from decimal import Decimal
from uuid import uuid4
from unittest.mock import Mock

from openpyxl import load_workbook
from application.analysis.analysis_factory import build_analysis_service
from application.analysis.analysis_coverage_service import assess_analysis_coverage
from application.config import ApplicationOverrides
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.research_quality.research_quality_factory import build_research_readiness_service
from application.research_quality.authoritative_outcome import derive_authoritative_outcome
from application.runtime.task_result_codec import capture_task_result
from domain.ai.llm_response import LLMResponse
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.planning.research_design import ResearchQuestion
from domain.research_brief import ResearchBrief
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.postgresql.mappers.workflow_template_mapper import workflow_template_to_model
from infrastructure.persistence.postgresql.models.workflow_run_model import WorkflowRunModel
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import PostgreSQLFindingRepository
from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import PostgreSQLInsightRepository
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import PostgreSQLWorkflowRunRepository
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from runtime.workflow_context import WorkflowContext
from tests.application.analysis.test_executable_derivations import derived_design, ProviderFixture
from tests.application.evidence.test_structured_production import workbook_rows
from tests.integration.postgresql import test_capability_acquisition as fixture
from tests.integration.postgresql.helpers import postgresql_application_config


class SufficiencyProvider:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt, **kwargs):
        assert prompt.system.startswith("You evaluate whether existing research evidence")
        self.calls += 1
        return LLMResponse(json.dumps(dict(supported_aspects=["level", "timepoint", "geography"],
            missing_aspects=[], semantic_conflicts=[], confidence=0.99,
            reason="Synthetic observations support all explicit aspects.")))


class ClassifiedReadinessPersistenceTests(fixture.CapabilityAcquisitionTests):
    def prepare(self, *, missing_year=False):
        self.body = workbook_rows()
        if missing_year:
            book = load_workbook(io.BytesIO(self.body))
            book.active.delete_rows(3)
            stream = io.BytesIO()
            book.save(stream)
            self.body = stream.getvalue()
        run_id = self.run_id()
        base = derived_design()
        model = replace(base, research_questions=(ResearchQuestion("rq", "Population"),),
            information_needs=tuple(replace(n, id="in" if n.id == "in-pop" else n.id,
                research_question_id="rq", depends_on_information_need_ids=tuple(
                    "in" if ref == "in-pop" else ref for ref in n.depends_on_information_need_ids))
                for n in base.information_needs))
        brief = ResearchBrief(title="Population", business_question="Population", timeframe="2019–2021")
        template = WorkflowTemplate(str(uuid4()), "Synthetic classified pipeline", (),
            research_design_snapshot=model, research_brief_snapshot=brief)
        with self.session_factory.session() as session:
            session.add(workflow_template_to_model(template, project_id=self.project.id, created_at=datetime.now(timezone.utc)))
            session.get(WorkflowRunModel, run_id).workflow_template_id = template.id
        workflow = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template, run_id=run_id, project_id=self.project.id)
        context = WorkflowContext(project=self.project, workflow_template=template, workflow_run=workflow)
        source = self.acquire(run_id)
        evidence = PostgreSQLEvidenceRepository(self.session_factory)
        findings = PostgreSQLFindingRepository(self.session_factory)
        insights = PostgreSQLInsightRepository(self.session_factory)
        config = postgresql_application_config(evidence_extractor="llm", analysis_engine="llm", research_sufficiency_assessor="llm")
        forbidden = Mock()
        forbidden.generate.side_effect = AssertionError("No LLM Evidence extraction")
        build_evidence_extraction_service(config=config, overrides=ApplicationOverrides(), evidence_repository=evidence,
            source_repository=self.repo, llm_client=forbidden).extract_for_source_ids(context, (source.id,), allow_empty=True)
        provider = SufficiencyProvider()
        readiness = build_research_readiness_service(config=config, overrides=ApplicationOverrides(),
            evidence_repository=evidence, source_repository=self.repo, llm_client=provider)
        return context, evidence, findings, insights, config, readiness, provider, forbidden

    def durable_reload(self, context):
        repo = PostgreSQLWorkflowRunRepository(self.session_factory)
        snapshot = capture_task_result(context, "fixture-checkpoint")
        repo.atomic_update_task_results(context.workflow_run.id, lambda state: ({**state, "fixture-checkpoint": snapshot}, None))
        fresh = DatabaseSessionFactory(self.engine)
        stored = PostgreSQLWorkflowRunRepository(fresh).get_task_results(context.workflow_run.id)
        state = stored["fixture-checkpoint"]["shared_state"]
        self.assertEqual(state, snapshot["shared_state"])
        return state

    def test_e2e_b_hybrid_readiness_analysis_coverage_and_reload(self):
        context, evidence, findings, insights, config, readiness, provider, forbidden = self.prepare()
        before = [e.to_dict() for e in evidence.list_for_project(self.project.id)]
        result = readiness.assess_and_apply(context)
        self.assertTrue(result.ready_for_analysis, result.to_dict())
        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(result.analysis_eligible_information_need_ids), 5)
        self.assertNotIn("table", result.analysis_eligible_information_need_ids)
        analysis = build_analysis_service(config=config, overrides=ApplicationOverrides(), evidence_repository=evidence,
            finding_repository=findings, insight_repository=insights, source_repository=self.repo, llm_client=ProviderFixture("in"))
        summary = analysis.analyze_for_context(context)
        self.assertEqual((len(summary.finding_ids), len(summary.insight_ids)), (7, 1))
        rows = findings.list_for_project(self.project.id, workflow_run_id=context.workflow_run.id)
        values = evidence.list_for_project(self.project.id)
        model = context.workflow_template.research_design_snapshot
        assessment = assess_analysis_coverage(project_id=self.project.id, design=model, findings=rows, evidence=values,
            brief=context.workflow_template.research_brief_snapshot, source_repository=self.repo)
        self.assertTrue(assessment.fully_covered, assessment.to_dict())
        self.assertEqual(assessment.missing_information_need_ids, ())
        context.write_shared("analysis_coverage", assessment.to_dict())
        self.assertEqual(derive_authoritative_outcome(required_information_need_ids=[n.id for n in model.information_needs],
            readiness_payload=context.read_shared("research_readiness"), findings=rows, evidence=values,
            project_id=self.project.id, workflow_run_id=context.workflow_run.id, research_design_id=model.id,
            coverage_missing_information_need_ids=assessment.missing_information_need_ids), ("COMPLETED", ()))
        proofs = [f.metadata["derivation"] for f in rows if f.metadata.get("derivation")]
        self.assertEqual(len(proofs), 6)
        actual = {(p["operation_type"], p["parameters"]["to_period"]): Decimal(p["rounded_result"]) for p in proofs}
        self.assertEqual(actual[("YEAR_OVER_YEAR_ABSOLUTE_CHANGE", "2020")], -50)
        self.assertEqual(actual[("YEAR_OVER_YEAR_ABSOLUTE_CHANGE", "2021")], -50)
        self.assertEqual(actual[("YEAR_OVER_YEAR_PERCENT_CHANGE", "2020")], -5)
        self.assertEqual(actual[("YEAR_OVER_YEAR_PERCENT_CHANGE", "2021")], Decimal("-5.263158"))
        self.assertEqual(actual[("CUMULATIVE_ABSOLUTE_CHANGE", "2021")], -100)
        self.assertEqual(actual[("CUMULATIVE_PERCENT_CHANGE", "2021")], -10)
        self.assertTrue(all(p["source_revision_lineage"] and p["dependency_finding_ids"] for p in proofs))
        state = self.durable_reload(context)
        self.assertEqual(ResearchReadinessResult.from_dict(state["research_readiness"]).to_dict(), result.to_dict())
        fresh_rows = PostgreSQLFindingRepository(DatabaseSessionFactory(self.engine)).list_for_project(self.project.id)
        self.assertEqual({f.id for f in fresh_rows}, set(summary.finding_ids))
        self.assertEqual(analysis.analyze_for_context(context).finding_ids, summary.finding_ids)
        self.assertEqual([e.to_dict() for e in evidence.list_for_project(self.project.id)], before)
        forbidden.generate.assert_not_called()

    def test_missing_observation_reasons_survive_postgresql_reload(self):
        context, evidence, findings, insights, config, readiness, provider, forbidden = self.prepare(missing_year=True)
        result = readiness.evaluate_for_context(context)  # Assessment only: no targeted acquisition.
        self.assertFalse(result.ready_for_analysis)
        self.assertTrue(all(d["status"] == "not_ready" for d in result.to_dict()["derived_prerequisites"].values()))
        readiness._persist(context, result, None)
        state = self.durable_reload(context)
        restored = ResearchReadinessResult.from_dict(state["research_readiness"])
        self.assertEqual(restored.to_dict(), result.to_dict())
        self.assertIn("unavailable_required_observations", json.dumps(state))
        self.assertEqual(findings.list_for_project(self.project.id), [])
        forbidden.generate.assert_not_called()
