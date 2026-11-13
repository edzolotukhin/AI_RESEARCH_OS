from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

from application.analysis.analysis_factory import build_analysis_service
from application.config import ApplicationOverrides
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.evidence.citation_integrity import citation_is_valid
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.planning.research_design import ResearchQuestion
from domain.research_brief import ResearchBrief
from domain.workflow_template import WorkflowTemplate
from runtime.workflow_context import WorkflowContext
from infrastructure.persistence.postgresql.mappers.workflow_template_mapper import workflow_template_to_model, workflow_template_from_model
from infrastructure.persistence.postgresql.models.workflow_template_model import WorkflowTemplateModel
from infrastructure.persistence.postgresql.models.workflow_run_model import WorkflowRunModel
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import PostgreSQLFindingRepository
from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import PostgreSQLInsightRepository
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from tests.integration.postgresql import test_capability_acquisition as acquisition_fixture
from tests.integration.postgresql.helpers import postgresql_application_config
from tests.application.analysis.test_executable_derivations import derived_design, ProviderFixture
from tests.application.evidence.test_structured_production import workbook_rows


class DerivedAnalysisPersistenceTests(acquisition_fixture.CapabilityAcquisitionTests):
    def test_production_analysis_derivations_persist_reload_and_repeat(self):
        self.body=workbook_rows()
        run_id=self.run_id()
        base=derived_design()
        needs=tuple(replace(n,id="in" if n.id=="in-pop" else n.id,research_question_id="rq",
            depends_on_information_need_ids=tuple("in" if ref=="in-pop" else ref for ref in n.depends_on_information_need_ids)) for n in base.information_needs)
        model=replace(base,research_questions=(ResearchQuestion("rq","Population"),),information_needs=needs)
        brief=ResearchBrief(title="Population",business_question="Population",timeframe="2019–2021")
        template=WorkflowTemplate(str(uuid4()),"Synthetic derived Analysis",(),research_design_snapshot=model,research_brief_snapshot=brief)
        with self.session_factory.session() as session:
            session.add(workflow_template_to_model(template,project_id=self.project.id,created_at=datetime.now(timezone.utc)))
            session.get(WorkflowRunModel,run_id).workflow_template_id=template.id
        workflow=WorkflowRunFactory(task_factory=TaskFactory()).create(template=template,run_id=run_id,project_id=self.project.id)
        context=WorkflowContext(project=self.project,workflow_template=template,workflow_run=workflow)
        source=self.acquire(run_id)
        evidence=PostgreSQLEvidenceRepository(self.session_factory)
        findings=PostgreSQLFindingRepository(self.session_factory)
        insights=PostgreSQLInsightRepository(self.session_factory)
        config=postgresql_application_config(evidence_extractor="llm",analysis_engine="llm")
        no_provider=Mock()
        no_provider.generate.side_effect=AssertionError("Numeric Evidence must be deterministic")
        build_evidence_extraction_service(config=config,overrides=ApplicationOverrides(),evidence_repository=evidence,source_repository=self.repo,llm_client=no_provider).extract_for_source_ids(context,(source.id,),allow_empty=True)
        source_before=self.repo.get_by_id(source.id).to_dict()
        evidence_before={e.id:e.to_dict() for e in evidence.list_for_project(self.project.id,workflow_run_id=run_id)}
        provider=ProviderFixture(acquired_id="in")
        service=build_analysis_service(config=config,overrides=ApplicationOverrides(),evidence_repository=evidence,finding_repository=findings,insight_repository=insights,source_repository=self.repo,llm_client=provider)
        first=service.analyze_for_context(context)
        self.assertEqual(len(first.finding_ids),7)
        self.assertEqual(len(first.insight_ids),1)
        self.assertEqual(len(provider.calls),3)  # ACQUIRED, independent entailment, Insights.
        fresh=DatabaseSessionFactory(self.engine)
        fresh_findings=PostgreSQLFindingRepository(fresh)
        fresh_evidence=PostgreSQLEvidenceRepository(fresh)
        fresh_sources=PostgreSQLSourceRepository(fresh)
        rows=[fresh_findings.get_by_id(fid) for fid in first.finding_ids]
        derived=[f for f in rows if f.metadata.get("derivation")]
        self.assertEqual(len(derived),6)
        results={(f.metadata["derivation"]["operation_type"],f.metadata["derivation"]["parameters"]["to_period"]):f.metadata["derivation"] for f in derived}
        self.assertEqual(Decimal(results[("YEAR_OVER_YEAR_ABSOLUTE_CHANGE","2020")]["raw_result"]),-50)
        self.assertEqual(Decimal(results[("YEAR_OVER_YEAR_PERCENT_CHANGE","2020")]["raw_result"]),-5)
        self.assertEqual(results[("YEAR_OVER_YEAR_PERCENT_CHANGE","2021")]["rounded_result"],"-5.263158")
        self.assertEqual(Decimal(results[("CUMULATIVE_ABSOLUTE_CHANGE","2021")]["raw_result"]),-100)
        self.assertEqual(Decimal(results[("CUMULATIVE_PERCENT_CHANGE","2021")]["raw_result"]),-10)
        evidence_ids={e.id for e in evidence.list_for_project(self.project.id,workflow_run_id=run_id)}
        for finding in derived:
            self.assertEqual(set(finding.evidence_refs),evidence_ids)
            self.assertEqual(finding.metadata["validation_status"],"validated")
            self.assertEqual(finding.analysis_method,"deterministic-derivation-v1")
            self.assertTrue(finding.metadata["derivation"]["dependency_finding_ids"])
            self.assertTrue(all(line["source_id"]==source.id and line["extraction_revision"]==source.extraction_revision for line in finding.metadata["derivation"]["source_revision_lineage"]))
            self.assertTrue(all(citation_is_valid(fresh_evidence.get_by_id(eid),fresh_sources.get_by_id(source.id)) for eid in finding.evidence_refs))
        with fresh.session() as session:
            reloaded=workflow_template_from_model(session.get(WorkflowTemplateModel,template.id))
        self.assertEqual(reloaded.research_design_snapshot.to_dict(),model.to_dict())
        context.workflow_template=reloaded
        second=service.analyze_for_context(context)
        self.assertEqual(first.finding_ids,second.finding_ids)
        self.assertEqual(len(findings.list_for_project(self.project.id,workflow_run_id=run_id)),7)
        self.assertEqual(fresh_sources.get_by_id(source.id).to_dict(),source_before)
        self.assertEqual({e.id:e.to_dict() for e in fresh_evidence.list_for_project(self.project.id,workflow_run_id=run_id)},evidence_before)
        no_provider.generate.assert_not_called()
