from dataclasses import replace
from decimal import Decimal
import ast
import io
import json
import re
import unittest
from unittest.mock import Mock
from openpyxl import Workbook

from domain.ai.llm_response import LLMResponse
from domain.planning.derivation import DerivationContract, DerivationOperation, InformationNeedKind
from domain.planning.research_design import InformationNeed, ResearchDesign
from domain.research_brief import ResearchBrief
from domain.project import Project
from domain.workflow_template import WorkflowTemplate
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.factories.task_factory import TaskFactory
from runtime.workflow_context import WorkflowContext
from application.config import ApplicationConfig, ApplicationOverrides
from application.analysis.analysis_factory import build_analysis_service
from application.analysis.exceptions import AnalysisError
from application.analysis.derivations import calculate_candidates, dependency_authority, validate_deterministic_derivation, DerivationRefused
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.ports.analysis_ports import FindingCandidate
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_insight_repository import InMemoryInsightRepository
from tests.application.evidence.test_structured_production import design as acquired_design, source as workbook_source


ARITHMETIC=tuple(op for op in DerivationOperation if op.deterministic)


def derived_design(*,operations=ARITHMETIC,dependency="in-pop"):
    base=acquired_design()
    derived=tuple(InformationNeed("derived-"+op.value,"rq-pop",op.value,kind=InformationNeedKind.DERIVED,
        depends_on_information_need_ids=(dependency,),derivation=DerivationContract(op,"Population","persons","Ukraine",
            required_periods=("2019","2020","2021"),method="Describe only the confirmed population observations." if not op.deterministic else "")) for op in operations)
    return replace(base,information_needs=(*base.information_needs,*derived,InformationNeed("table","rq-pop","Presentation table",kind=InformationNeedKind.OUTPUT,depends_on_information_need_ids=(dependency,))))


class ProviderFixture:
    """External LLM boundary only; production parser and entailment stay real."""
    def __init__(self, acquired_id="in-pop"):
        self.acquired_id=acquired_id
        self.semantic_statement="Population observations indicate a decline."
        self.reject_semantic=False
        self.fail_semantic=False
        self.calls=[]

    def generate(self,prompt,**kwargs):
        self.calls.append(prompt.system)
        if "independent entailment validator" in prompt.system:
            verdicts=[]
            for block in prompt.user.split("candidate_id=")[1:]:
                candidate_id=block.splitlines()[0].strip()
                refs=ast.literal_eval(re.search(r"evidence_refs=(\[[^\n]+\])",block)[1])
                status="UNSUPPORTED" if self.reject_semantic and candidate_id.startswith("derived-") else "SUPPORTED"
                verdicts.append(dict(candidate_id=candidate_id,status=status,supported_evidence_ids=refs if status=="SUPPORTED" else [],unsupported_claim_parts=[],rationale="Synthetic boundary verdict"))
            return LLMResponse(json.dumps({"verdicts":verdicts}))
        if "An Insight" in prompt.system:
            refs=re.findall(r"^- id=(\S+) statement=",prompt.user,re.M)
            return LLMResponse(json.dumps({"insights":[{"statement":"Population results require context.","implication":"Interpret the validated observations.","finding_refs":refs}]}))
        refs=re.findall(r"^- id=(\S+) statement=",prompt.user,re.M)
        target=self.acquired_id
        statement="Population observations are documented for Ukraine."
        if "explicit_derivation_contracts:" in prompt.user:
            if self.fail_semantic:
                raise RuntimeError("Synthetic provider outage")
            payload=json.loads(next(line.split(": ",1)[1] for line in prompt.user.splitlines() if line.startswith("explicit_derivation_contracts:")))
            target=payload[0]["id"]
            statement=self.semantic_statement
        return LLMResponse(json.dumps({"findings":[{"statement":statement,"rationale":"Supported population observations.","evidence_refs":refs,"information_need_refs":[target]}]}))


def setup_memory(model=None,series=((2019,1000),(2020,950),(2021,900)),unit="persons"):
    model=model or derived_design()
    book=Workbook()
    book.active.append(["Year","Population","Unit","Geography"])
    for year,value in series:
        book.active.append([year,value,unit,"Ukraine"])
    output=io.BytesIO(); book.save(output)
    source=workbook_source(output.getvalue())
    sources=InMemorySourceRepository(); sources.create(source)
    evidence=InMemoryEvidenceRepository()
    findings=InMemoryFindingRepository(); insights=InMemoryInsightRepository()
    brief=ResearchBrief(title="Population",business_question="Population",timeframe="2019–2021")
    template=WorkflowTemplate("template","Fixture",(),research_design_snapshot=model,research_brief_snapshot=brief)
    run=WorkflowRunFactory(task_factory=TaskFactory()).create(template=template,run_id="run",project_id="project")
    context=WorkflowContext(project=Project("project","Fixture"),workflow_template=template,workflow_run=run)
    config=ApplicationConfig(evidence_extractor="llm",analysis_engine="llm")
    provider=ProviderFixture()
    build_evidence_extraction_service(config=config,overrides=ApplicationOverrides(),evidence_repository=evidence,source_repository=sources,llm_client=Mock()).extract_for_source_ids(context,(source.id,),allow_empty=True)
    analysis=build_analysis_service(config=config,overrides=ApplicationOverrides(),evidence_repository=evidence,finding_repository=findings,insight_repository=insights,source_repository=sources,llm_client=provider)
    return context,analysis,findings,evidence,sources,provider


class DerivationContractTests(unittest.TestCase):
    def test_roundtrip_and_legacy_serialization(self):
        model=derived_design()
        self.assertEqual(ResearchDesign.from_dict(model.to_dict()).to_dict(),model.to_dict())
        legacy=acquired_design().to_dict()
        self.assertNotIn("kind",legacy["information_needs"][0])
        self.assertEqual(ResearchDesign.from_dict(legacy).to_dict(),legacy)
        self.assertEqual(ResearchDesign.from_dict(legacy).information_needs[0].kind,InformationNeedKind.ACQUIRED)

    def test_invalid_graphs_and_operations(self):
        model=derived_design()
        target=model.information_needs[1]
        for dependencies in ((target.id,),("foreign",)):
            with self.assertRaises(ValueError):
                replace(model,information_needs=(model.information_needs[0],replace(target,depends_on_information_need_ids=dependencies)))
        second=replace(target,id="second",depends_on_information_need_ids=(target.id,))
        with self.assertRaises(ValueError):
            replace(model,information_needs=(replace(target,depends_on_information_need_ids=("second",)),second))
        with self.assertRaises(ValueError):
            DerivationContract("UNKNOWN","Population","persons","Ukraine",("2019","2020"))
        with self.assertRaises(ValueError):
            DerivationContract(DerivationOperation.YEAR_OVER_YEAR_ABSOLUTE_CHANGE,"Population","persons","Ukraine",("2019","2021"))
        with self.assertRaises(ValueError):
            InformationNeed("broken","rq-pop","Broken",kind="DERIVED")


class ExecutableDerivationTests(unittest.TestCase):
    def test_recomputation_rejects_tampering_and_foreign_authority(self):
        context,analysis,findings,evidence,sources,provider=setup_memory()
        analysis.analyze_for_context(context)
        need=context.workflow_template.research_design_snapshot.information_needs[1]
        scope=dict(design=context.workflow_template.research_design_snapshot,project_id="project",workflow_run_id="run",allowed_runs=("run",),source_repository=sources)
        deps,inputs=dependency_authority(need,findings.list_for_project("project"),evidence.list_for_project("project"),brief=context.workflow_template.research_brief_snapshot,**scope)
        candidate=calculate_candidates(need,inputs,deps,**scope)[0]
        altered=replace(candidate,metadata={**candidate.metadata,"derivation":{**candidate.metadata["derivation"],"raw_result":"42"}})
        with self.assertRaises(DerivationRefused):
            validate_deterministic_derivation(altered,need,inputs,deps,brief=context.workflow_template.research_brief_snapshot,**scope)
        for field in ("project_id","workflow_run_id","research_design_id","source_content_checksum"):
            foreign=tuple(replace(e,**{field:"foreign"}) for e in inputs)
            with self.assertRaises(DerivationRefused):
                validate_deterministic_derivation(candidate,need,foreign,deps,brief=context.workflow_template.research_brief_snapshot,**scope)

    def test_conflicting_confirmed_observations_refuse_arithmetic(self):
        context,analysis,findings,evidence,sources,provider=setup_memory()
        other=workbook_source()
        # A distinct real workbook revision disagrees about the 2019 cell.
        book=Workbook(); book.active.append(["Year","Population","Unit","Geography"])
        for year,value in ((2019,1001),(2020,950),(2021,900)):
            book.active.append([year,value,"persons","Ukraine"])
        stream=io.BytesIO(); book.save(stream)
        other=replace(workbook_source(stream.getvalue()),id="other",url="https://example.org/other.xlsx",canonical_url="https://example.org/other.xlsx")
        sources.create(other)
        build_evidence_extraction_service(config=ApplicationConfig(evidence_extractor="llm"),overrides=ApplicationOverrides(),evidence_repository=evidence,source_repository=sources,llm_client=Mock()).extract_for_source_ids(context,(other.id,),allow_empty=True)
        analysis.analyze_for_context(context)
        assessments=context.read_shared("analysis_derivations")["assessments"]
        self.assertTrue(all(a["status"]=="insufficient" and a["reason"].startswith("conflicting_values") for a in assessments))

    def test_all_calculations_lineage_rounding_and_idempotency(self):
        context,analysis,findings,evidence,sources,provider=setup_memory()
        first=analysis.analyze_for_context(context)
        rows=findings.list_for_project("project",workflow_run_id="run")
        calculated=[f for f in rows if f.metadata.get("derivation")]
        self.assertEqual(len(calculated),6)
        results={(f.metadata["derivation"]["operation_type"],f.metadata["derivation"]["parameters"]["to_period"]):f.metadata["derivation"] for f in calculated}
        self.assertEqual(Decimal(results[("YEAR_OVER_YEAR_ABSOLUTE_CHANGE","2020")]["raw_result"]),-50)
        self.assertEqual(Decimal(results[("YEAR_OVER_YEAR_ABSOLUTE_CHANGE","2021")]["raw_result"]),-50)
        self.assertEqual(Decimal(results[("YEAR_OVER_YEAR_PERCENT_CHANGE","2020")]["raw_result"]),-5)
        self.assertEqual(results[("YEAR_OVER_YEAR_PERCENT_CHANGE","2021")]["rounded_result"],"-5.263158")
        self.assertEqual(Decimal(results[("CUMULATIVE_ABSOLUTE_CHANGE","2021")]["raw_result"]),-100)
        self.assertEqual(Decimal(results[("CUMULATIVE_PERCENT_CHANGE","2021")]["raw_result"]),-10)
        for finding in calculated:
            data=finding.metadata["derivation"]
            self.assertTrue(data["dependency_finding_ids"])
            self.assertEqual(set(finding.evidence_refs),{e.id for e in evidence.list_for_project("project")})
            self.assertEqual(len(data["source_revision_lineage"]),3)
            self.assertEqual(data["rounding"]["mode"],"ROUND_HALF_EVEN")
        second=analysis.analyze_for_context(context)
        self.assertEqual(first.finding_ids,second.finding_ids)
        self.assertEqual(len(findings.list_for_project("project")),7)

    def test_missing_year_zero_denominator_and_unit_geography_mismatch(self):
        cases=[dict(series=((2019,1000),(2021,900))),dict(series=((2019,0),(2020,950),(2021,900))),dict(unit="thousands")]
        for case in cases:
            context,analysis,findings,*_=setup_memory(**case)
            analysis.analyze_for_context(context)
            assessments=context.read_shared("analysis_derivations")["assessments"]
            self.assertTrue(any(a["status"]=="insufficient" for a in assessments))
            if case.get("unit") or len(case.get("series",()))==2:
                self.assertFalse(any(f.metadata.get("derivation") for f in findings.list_for_project("project")))
        model=derived_design()
        model=replace(model,information_needs=tuple(replace(n,derivation=replace(n.derivation,geography="Poland")) if n.derivation else n for n in model.information_needs))
        context,analysis,findings,*_=setup_memory(model)
        analysis.analyze_for_context(context)
        self.assertFalse(any(f.metadata.get("derivation") for f in findings.list_for_project("project")))

    def test_semantic_synthesis_uses_provenance_and_entailment(self):
        for reject in (False,True):
            model=derived_design(operations=(DerivationOperation.TREND_CHARACTERIZATION,))
            context,analysis,findings,evidence,sources,provider=setup_memory(model)
            provider.reject_semantic=reject
            analysis.analyze_for_context(context)
            derived=[f for f in findings.list_for_project("project") if f.metadata.get("derivation")]
            self.assertEqual(len(derived),0 if reject else 1)
            self.assertEqual(context.read_shared("analysis_derivations")["assessments"][0]["provider_attempts"],1)

    def test_cross_source_and_bounded_attempt_contract(self):
        model=derived_design(operations=(DerivationOperation.CROSS_SOURCE_COMPARISON,))
        context,analysis,findings,evidence,sources,provider=setup_memory(model)
        analysis.analyze_for_context(context)
        self.assertEqual(context.read_shared("analysis_derivations")["assessments"][0]["reason"],"cross_source_requires_distinct_resources")
        book=Workbook(); book.active.append(["Year","Population","Unit","Geography"])
        for year,value in ((2019,1000),(2020,950),(2021,900)):
            book.active.append([year,value,"persons","Ukraine"])
        book.active.append([]); book.active.append(["Second synthetic source notes"])
        stream=io.BytesIO(); book.save(stream)
        other=replace(workbook_source(stream.getvalue()),id="other",url="https://example.org/second",canonical_url="https://example.org/second")
        sources.create(other)
        build_evidence_extraction_service(config=ApplicationConfig(evidence_extractor="llm"),overrides=ApplicationOverrides(),evidence_repository=evidence,source_repository=sources,llm_client=Mock()).extract_for_source_ids(context,(other.id,),allow_empty=True)
        provider.semantic_statement="Population observations agree across the supplied sources."
        analysis.analyze_for_context(context)
        self.assertEqual(context.read_shared("analysis_derivations")["assessments"][0]["status"],"validated")
        context,analysis,findings,evidence,sources,provider=setup_memory(derived_design(operations=(DerivationOperation.TREND_CHARACTERIZATION,)))
        target=context.workflow_template.research_design_snapshot.information_needs[1]
        updated=replace(context.workflow_template.research_design_snapshot,information_needs=tuple(replace(n,derivation=replace(n.derivation,max_provider_attempts=2)) if n.id==target.id else n for n in context.workflow_template.research_design_snapshot.information_needs))
        context.workflow_template=replace(context.workflow_template,research_design_snapshot=updated)
        provider.reject_semantic=True
        analysis.analyze_for_context(context)
        self.assertEqual(context.read_shared("analysis_derivations")["assessments"][0]["provider_attempts"],2)

    def test_semantic_fabrication_and_technical_failure_are_distinct(self):
        model=derived_design(operations=(DerivationOperation.LIMITATION_SYNTHESIS,))
        context,analysis,findings,evidence,sources,provider=setup_memory(model)
        provider.semantic_statement="Population declined by 999999 persons."
        analysis.analyze_for_context(context)
        self.assertEqual(context.read_shared("analysis_derivations")["assessments"][0]["status"],"insufficient")
        context,analysis,findings,evidence,sources,provider=setup_memory(model)
        provider.fail_semantic=True
        with self.assertRaises(AnalysisError):
            analysis.analyze_for_context(context)
        self.assertEqual(context.read_shared("analysis_derivations")["assessments"][0]["status"],"technical_error")
