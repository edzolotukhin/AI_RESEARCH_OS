from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from unittest.mock import Mock
from uuid import uuid4

from application.config import ApplicationOverrides
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.evidence.citation_integrity import citation_is_valid
from application.evidence.grounding import verify_grounding
from application.evidence.temporal_scope import qualifying_evidence
from application.research_quality.deterministic_sufficiency_evaluator import DeterministicSufficiencyEvaluator
from domain.evidence.evidence import Evidence
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.planning.research_design import ResearchQuestion
from domain.research_brief import ResearchBrief
from domain.sources.source import Source
from domain.workflow_template import WorkflowTemplate
from runtime.workflow_context import WorkflowContext
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from tests.integration.postgresql.test_capability_acquisition import CapabilityAcquisitionTests
from tests.integration.postgresql.helpers import postgresql_application_config
from tests.application.evidence.test_structured_production import design, workbook_rows


class StructuredEvidencePipelineTests(CapabilityAcquisitionTests):
    def setup_pipeline(self):
        self.body=workbook_rows()
        run=self.run_id()
        base=design()
        design_snapshot=replace(base,research_questions=(ResearchQuestion("rq","Population"),),information_needs=(replace(base.information_needs[0],id="in",research_question_id="rq"),))
        brief=ResearchBrief(title="Population",business_question="Population",timeframe="2019–2021")
        template=WorkflowTemplate(id="fixture",name="Synthetic Evidence",task_definitions=(),research_design_snapshot=design_snapshot,research_brief_snapshot=brief)
        workflow=WorkflowRunFactory(task_factory=TaskFactory()).create(template=template,run_id=run,project_id=self.project.id)
        context=WorkflowContext(project=self.project,workflow_template=template,workflow_run=workflow)
        provider=Mock()
        provider.generate.side_effect=AssertionError("Structured observations must not call an LLM")
        evidence=PostgreSQLEvidenceRepository(self.session_factory)
        service=build_evidence_extraction_service(config=postgresql_application_config(evidence_extractor="llm"),overrides=ApplicationOverrides(),evidence_repository=evidence,source_repository=self.repo,llm_client=provider)
        return run,context,service,evidence,provider,design_snapshot,brief

    def test_e2e_a_real_navigation_production_extractor_persistence_reload(self):
        run,context,service,evidence,provider,design_snapshot,brief=self.setup_pipeline()
        legacy=Source(str(uuid4()),self.project.id,self.origin+"/landing",self.origin+"/landing","Legacy",datetime.now(timezone.utc).isoformat(),content_text="legacy",content_checksum=sha256(b"legacy").hexdigest())
        self.repo.create(legacy)
        before=self.repo.get_by_id(legacy.id).to_dict()
        historic=Evidence(str(uuid4()),self.project.id,legacy.id,legacy.content_checksum,self.run_id(),"history","legacy","legacy",datetime.now(timezone.utc).isoformat(),source_locator=verify_grounding(source_text="legacy",excerpt="legacy").to_dict(),deduplication_key="historic")
        evidence.create(historic)
        source=self.acquire(run)
        first=service.extract_for_source_ids(context,(source.id,),allow_empty=True)
        second=service.extract_for_source_ids(context,(source.id,),allow_empty=True)
        rows=sorted(evidence.list_for_project(self.project.id,workflow_run_id=run),key=lambda e:e.metadata["observation_period"])
        self.assertEqual(len(rows),3,(first.to_dict(),second.to_dict()))
        self.assertEqual([(r.metadata["observation_period"],r.metadata["numeric_value"]) for r in rows],[("2019",1000),("2020",950),("2021",900)])
        self.assertEqual([r.source_locator["structured"]["cell"] for r in rows],["B2","B3","B4"])
        self.assertEqual(len(qualifying_evidence(design=design_snapshot,evidence=rows,brief=brief,source_repository=self.repo)),3)
        signals=DeterministicSufficiencyEvaluator().evaluate(design=design_snapshot,evidence=rows)
        self.assertEqual(set(signals[0].declared_supported_aspects),{"level","timepoint","geography"})
        fresh=DatabaseSessionFactory(self.engine)
        reread=PostgreSQLEvidenceRepository(fresh)
        for row in rows:
            loaded=reread.get_by_id(row.id)
            self.assertTrue(citation_is_valid(loaded,PostgreSQLSourceRepository(fresh).get_by_id(source.id)))
            self.assertEqual(loaded.source_id,source.id)
            self.assertEqual(loaded.metadata["workbook_provenance"]["raw_workbook_checksum"],source.raw_content_checksum)
        self.assertEqual(self.repo.get_by_id(legacy.id).to_dict(),before)
        self.assertTrue(citation_is_valid(reread.get_by_id(historic.id),self.repo.get_by_id(legacy.id)))
        provider.generate.assert_not_called()

        # Changed content gets separate Evidence; another landing for the same
        # terminal snapshot must not duplicate those new observations.
        import io
        from openpyxl import load_workbook
        book=load_workbook(io.BytesIO(self.body))
        book.active["B3"]=940
        output=io.BytesIO()
        book.save(output)
        self.body=output.getvalue()
        revised=self.acquire(run,acquisition_refresh="1")
        self.assertNotEqual(revised.id,source.id)
        service.extract_for_source_ids(context,(revised.id,),allow_empty=True)
        alias=self.acquire(run,landing="/other")
        self.assertEqual(alias.id,revised.id)
        service.extract_for_source_ids(context,(alias.id,),allow_empty=True)
        self.assertEqual(len(evidence.list_for_project(self.project.id,workflow_run_id=run)),6)
        for old in rows:
            self.assertTrue(citation_is_valid(reread.get_by_id(old.id),self.repo.get_by_id(source.id)))
        reextracted=self.repo.create_immutable_revision(replace(revised,id=str(uuid4()),extraction_revision="xlsx-structured-v3"))
        self.assertEqual(reextracted.content_revision,revised.content_revision)
        service.extract_for_source_ids(context,(reextracted.id,),allow_empty=True)
        all_rows=evidence.list_for_project(self.project.id,workflow_run_id=run)
        self.assertEqual(len(all_rows),9)
        self.assertEqual(len([r for r in all_rows if r.source_id==reextracted.id]),3)

    def test_ambiguous_table_durable_rejection_no_provider_bypass(self):
        run,context,service,evidence,provider,_,_=self.setup_pipeline()
        self.body=workbook_rows([["Year","Population","Unit","Geography"],[2019,999,"persons","Ukraine"],[2020,998,"persons","Ukraine"],[2021,997,"persons","Ukraine"]])
        source=self.acquire(run)
        summary=service.extract_for_source_ids(context,(source.id,),allow_empty=True)
        self.assertEqual(evidence.list_for_project(self.project.id,workflow_run_id=run),[])
        self.assertIn("ambiguous_metric_binding",{r["reason"] for r in summary.diagnostics.structured_rejections})
        provider.generate.assert_not_called()
