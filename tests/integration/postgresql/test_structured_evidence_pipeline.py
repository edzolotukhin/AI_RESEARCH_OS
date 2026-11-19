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
from application.evidence.temporal_scope import qualify_evidence_with_temporal_decisions
from application.analysis.numeric_integrity import project_numeric_evidence_for_design
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
from infrastructure.retrieval.xlsx_text_extractor import extract_xlsx_text
from pathlib import Path


class StructuredEvidencePipelineTests(CapabilityAcquisitionTests):
    def test_real_official_archive_persists_reloads_and_qualifies_complete_series(self):
        path = (Path(__file__).resolve().parents[3] / "artifacts" / "acceptance" /
            "live_e2e_post_p1_real_source" / "population_1990_2021_official.zip")
        if not path.is_file():
            self.skipTest("optional real-source fixture missing: official population archive")
        raw = path.read_bytes()
        self.assertEqual(sha256(raw).hexdigest(),
            "8ebec6377cdd6e1c5856ae f97f91e8e89e36b0038b4a6498c05e2b626821fcc4".replace(" ", ""))
        parsed=extract_xlsx_text(raw,content_type="application/zip")
        self.assertTrue(parsed.ok)
        metric="Чисельність постійного населення/Total resident population / всього/total"
        unit="(на 1 січня; тис. осіб/as of 1 January; thsd.)"
        geography="Excluding the temporarily occupied territories of the Autonomous Republic of Crimea, and the city of Sevastopol."
        base=design(); need=base.information_needs[0]
        need=replace(need,geography=geography,
            evidence_expectation=replace(need.evidence_expectation,geography=geography),
            evidence_coverage=replace(need.evidence_coverage,required_metric=metric,
                required_unit=unit,required_periods=tuple(str(year) for year in range(2015,2022)),
                geography=geography))
        snapshot=replace(base,information_needs=(need,))
        brief=ResearchBrief(title="Resident population",business_question="Resident population",
            timeframe="2015–2021")
        run=self.run_id()
        template=WorkflowTemplate(id="official",name="Official population",task_definitions=(),
            research_design_snapshot=snapshot,research_brief_snapshot=brief)
        workflow=WorkflowRunFactory(task_factory=TaskFactory()).create(
            template=template,run_id=run,project_id=self.project.id)
        context=WorkflowContext(project=self.project,workflow_template=template,workflow_run=workflow)
        source=Source(str(uuid4()),self.project.id,
            "https://stat.gov.ua/sites/default/files/2023-10/population.zip",
            "https://stat.gov.ua/sites/default/files/2023-10/population.zip",
            "Населення (1990-2021)",datetime.now(timezone.utc).isoformat(),
            content_type="application/zip",content_text=parsed.text,
            content_checksum=sha256(parsed.text.encode()).hexdigest(),metadata=parsed.metadata,
            raw_content_checksum=sha256(raw).hexdigest(),raw_checksum_kind="sha256-bytes",
            extraction_revision="xlsx-structured-v2",workflow_run_refs=(run,),
            research_design_refs=(snapshot.id,),information_need_refs=(need.id,),
            research_question_refs=(need.research_question_id,))
        self.repo.create(source)
        evidence=PostgreSQLEvidenceRepository(self.session_factory)
        provider=Mock(); provider.generate.side_effect=AssertionError("Official structured rows must not call an LLM")
        service=build_evidence_extraction_service(
            config=postgresql_application_config(evidence_extractor="llm"),overrides=ApplicationOverrides(),
            evidence_repository=evidence,source_repository=self.repo,llm_client=provider)

        summary=service.extract_for_source_ids(context,(source.id,),allow_empty=True)
        rows=tuple(evidence.list_for_project(self.project.id,workflow_run_id=run))
        temporal=qualify_evidence_with_temporal_decisions(
            design=snapshot,evidence=rows,brief=brief,source_repository=self.repo)
        projection=project_numeric_evidence_for_design(
            design=snapshot,evidence=temporal.evidence,source_repository=self.repo,
            temporal_decisions=temporal.decisions,allowed_workflow_run_ids=(run,))
        qualification=projection.qualifications[need.id]

        self.assertEqual(summary.evidence_extracted,7)
        self.assertEqual(len(temporal.evidence),7)
        self.assertTrue(qualification.available)
        self.assertEqual(tuple(sorted(item.period for item in qualification.observations)),
            tuple(str(year) for year in range(2015,2022)))
        self.assertEqual(qualification.rejection_reason_counts,{})
        fresh=DatabaseSessionFactory(self.engine)
        reread=PostgreSQLEvidenceRepository(fresh)
        self.assertTrue(all(reread.get_by_id(item.id) is not None for item in rows))
        self.assertTrue(all(citation_is_valid(reread.get_by_id(item.id),
            PostgreSQLSourceRepository(fresh).get_by_id(source.id)) for item in rows))
        provider.generate.assert_not_called()

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
