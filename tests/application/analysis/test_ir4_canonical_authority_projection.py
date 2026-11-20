from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import Mock

from application.analysis.analysis_service import AnalysisService
from application.analysis.exceptions import AnalysisError
from application.analysis.numeric_integrity import project_numeric_evidence_for_design
from application.config import ApplicationConfig, ApplicationOverrides
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.evidence.temporal_scope import qualify_evidence_with_temporal_decisions
from application.ports.analysis_ports import FindingCandidate, InsightCandidate
from application.research_quality.deterministic_research_sufficiency_evaluator import (
    DeterministicResearchSufficiencyEvaluator,
)
from application.research_quality.research_readiness_service import (
    ResearchReadinessService,
    SHARED_STATE_KEY,
)
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.planning.derivation import (
    DerivationContract,
    DerivationOperation,
    InformationNeedKind,
)
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_insight_repository import InMemoryInsightRepository
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from runtime.workflow_context import WorkflowContext
from tests.application.evidence.test_ir3_structured_numeric_closure import (
    YEARS,
    ir3_design,
    ir3_source,
    ir3_zip,
)


def ir4_design(*, minimum_independent_sources: int = 1):
    base = ir3_design()
    acquired = replace(
        base.information_needs[0],
        evidence_coverage=replace(
            base.information_needs[0].evidence_coverage,
            minimum_independent_sources=minimum_independent_sources,
        ),
    )
    derived = InformationNeed(
        "change",
        "rq",
        "Cumulative resident population change",
        kind=InformationNeedKind.DERIVED,
        depends_on_information_need_ids=("in",),
        derivation=DerivationContract(
            DerivationOperation.CUMULATIVE_ABSOLUTE_CHANGE,
            "Resident population",
            "persons",
            "Ukraine",
            required_periods=YEARS,
        ),
    )
    return replace(base, information_needs=(acquired, derived))


class CanonicalAnalysisEngine:
    method_name = "ir4-canonical-fixture"

    def __init__(self, *, invalid_evidence_ref: bool = False):
        self.invalid_evidence_ref = invalid_evidence_ref
        self.finding_batches: list[tuple[str, ...]] = []
        self.insight_finding_ids: tuple[str, ...] = ()

    def analyze_findings(self, analysis_input):
        ids = tuple(sorted(item.id for item in analysis_input.evidence_batch))
        self.finding_batches.append(ids)
        return [FindingCandidate(
            statement="Resident population observations are documented for Ukraine.",
            rationale="The statement is grounded in the selected annual observations.",
            evidence_refs=("foreign-evidence",) if self.invalid_evidence_ref else ids,
            research_question_refs=("rq",),
            information_need_refs=("in",),
            finding_type="observation",
        )]

    def analyze_insights(self, analysis_input):
        self.insight_finding_ids = tuple(sorted(item.id for item in analysis_input.persisted_findings))
        return [InsightCandidate(
            statement="The validated population series shows a measurable change.",
            implication="Interpret the change using the validated annual series.",
            finding_refs=self.insight_finding_ids,
            research_question_refs=("rq",),
        )]


def setup_pipeline(*, raw=None, model=None, invalid_evidence_ref=False):
    model = model or ir4_design()
    source = ir3_source(raw)
    sources = InMemorySourceRepository()
    evidence = InMemoryEvidenceRepository()
    findings = InMemoryFindingRepository()
    insights = InMemoryInsightRepository()
    sources.create(source)
    brief = ResearchBrief(
        title="Resident population",
        business_question="Resident population of Ukraine",
        timeframe="2015–2021",
    )
    template = WorkflowTemplate(
        "template",
        "IR-4 canonical authority",
        (),
        research_design_snapshot=model,
        research_brief_snapshot=brief,
    )
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(
        template=template, run_id="run", project_id="project",
    )
    context = WorkflowContext(
        project=Project("project", "IR-4 fixture"),
        workflow_template=template,
        workflow_run=run,
    )
    extraction_provider = Mock()
    extraction_provider.generate.side_effect = AssertionError(
        "structured extraction must not call a provider",
    )
    extraction = build_evidence_extraction_service(
        config=ApplicationConfig(evidence_extractor="llm"),
        overrides=ApplicationOverrides(),
        evidence_repository=evidence,
        source_repository=sources,
        llm_client=extraction_provider,
    )
    extraction.extract_for_source_ids(context, (source.id,), allow_empty=True)
    extraction_provider.generate.assert_not_called()
    engine = CanonicalAnalysisEngine(invalid_evidence_ref=invalid_evidence_ref)
    analysis = AnalysisService(
        analysis_engine=engine,
        evidence_repository=evidence,
        finding_repository=findings,
        insight_repository=insights,
        max_evidence_per_batch=100,
        max_chars_per_batch=1_000_000,
        source_repository=sources,
    )
    readiness = ResearchReadinessService(
        evaluator=DeterministicResearchSufficiencyEvaluator(),
        evidence_repository=evidence,
        source_repository=sources,
    )
    return context, readiness, analysis, evidence, findings, insights, sources, engine


def acquired_assessment(result):
    return next(
        item
        for rq in result.research_question_assessments
        for item in rq.information_need_assessments
        if item.information_need_id == "in"
    )


class IR4CanonicalAuthorityProjectionTests(unittest.TestCase):
    def test_positive_evidence_id_parity_through_readiness_findings_and_insights(self):
        context, readiness, analysis, evidence, findings, insights, sources, engine = setup_pipeline()
        persisted_ids = tuple(sorted(item.id for item in evidence.list_for_project("project")))
        temporal, projection = readiness.qualification_for_context(context)
        accepted_ids = tuple(sorted(
            item.id for item in projection.qualifications["in"].accepted_evidence
        ))
        self.assertEqual(accepted_ids, persisted_ids)
        self.assertEqual(
            tuple(sorted(item.id for item in projection.evidence)), persisted_ids,
        )

        ready = readiness.assess_and_apply(context)
        self.assertTrue(ready.ready_for_analysis)
        assessment = acquired_assessment(ready)
        self.assertEqual(
            tuple(assessment.prerequisite_diagnostics["qualifying_evidence_ids"]),
            persisted_ids,
        )
        summary = analysis.analyze_for_context(context)
        self.assertTrue(summary.finding_ids)
        self.assertTrue(summary.insight_ids)
        self.assertTrue(engine.finding_batches)
        self.assertTrue(all(batch == persisted_ids for batch in engine.finding_batches))

        finding_rows = findings.list_for_project("project", workflow_run_id="run")
        acquired = next(item for item in finding_rows if item.information_need_refs == ("in",))
        derived = next(item for item in finding_rows if item.information_need_refs == ("change",))
        self.assertEqual(tuple(acquired.evidence_refs), persisted_ids)
        self.assertEqual(tuple(derived.evidence_refs), persisted_ids)
        self.assertEqual(
            tuple(derived.metadata["derivation"]["input_evidence_ids"]), persisted_ids,
        )
        insight = insights.list_for_project("project", workflow_run_id="run")[0]
        self.assertEqual(tuple(sorted(insight.finding_refs)), tuple(sorted(item.id for item in finding_rows)))
        self.assertEqual(engine.insight_finding_ids, tuple(sorted(item.id for item in finding_rows)))

    def test_f1_rejected_evidence_never_reaches_analysis_engine(self):
        context, readiness, analysis, evidence, findings, _, _, engine = setup_pipeline()
        accepted = tuple(evidence.list_for_project("project"))
        rejected = replace(
            accepted[0],
            id="rejected-subject",
            deduplication_key="rejected-subject",
            metadata={
                **accepted[0].metadata,
                "semantic_assignment": {
                    **accepted[0].metadata["semantic_assignment"],
                    "subject_fingerprint": "forged",
                },
            },
        )
        evidence.create(rejected)
        readiness.assess_and_apply(context)

        analysis.analyze_for_context(context)

        accepted_ids = tuple(sorted(item.id for item in accepted))
        self.assertTrue(engine.finding_batches)
        self.assertTrue(all(batch == accepted_ids for batch in engine.finding_batches))
        self.assertNotIn(rejected.id, {
            ref for item in findings.list_for_project("project") for ref in item.evidence_refs
        })

    def test_missing_prerequisite_period_blocks_acquired_and_derived_readiness(self):
        years = YEARS[:-1]
        context, readiness, _, _, _, _, _, _ = setup_pipeline(raw=ir3_zip(years=years))
        result = readiness.evaluate_for_context(context)
        assessments = {
            item.information_need_id: item
            for rq in result.research_question_assessments
            for item in rq.information_need_assessments
        }
        self.assertFalse(result.ready_for_analysis)
        self.assertNotIn("in", result.analysis_eligible_information_need_ids)
        self.assertNotIn("change", result.analysis_eligible_information_need_ids)
        self.assertIn("missing_required_numeric_periods", assessments["in"].reason)
        self.assertEqual(assessments["change"].prerequisite_diagnostics["status"], "not_ready")

    def test_partial_scope_is_honest_when_unrelated_mandatory_need_is_missing(self):
        base = ir4_design()
        qualitative = InformationNeed(
            "context",
            "rq",
            "Methodological context",
            evidence_expectation=EvidenceExpectation(EvidenceNature.QUALITATIVE),
        )
        model = replace(base, information_needs=(*base.information_needs, qualitative))
        context, readiness, _, _, _, _, _, _ = setup_pipeline(model=model)
        result = readiness.evaluate_for_context(context)
        assessments = {
            item.information_need_id: item
            for rq in result.research_question_assessments
            for item in rq.information_need_assessments
        }
        self.assertFalse(result.ready_for_analysis)
        self.assertTrue(result.analysis_ready)
        self.assertEqual(assessments["context"].status.value, "missing")
        self.assertIn("in", result.analysis_eligible_information_need_ids)
        self.assertIn("change", result.analysis_eligible_information_need_ids)
        self.assertNotIn("context", result.analysis_eligible_information_need_ids)

    def test_rejected_numeric_qualification_is_insufficient(self):
        context, readiness, analysis, _, findings, insights, _, engine = setup_pipeline(
            raw=ir3_zip(unit="thousands"),
        )
        result = readiness.evaluate_for_context(context)
        assessment = acquired_assessment(result)
        self.assertFalse(result.analysis_ready)
        self.assertEqual(assessment.prerequisite_diagnostics["qualifying_evidence_ids"], [])
        self.assertIn(
            "missing_qualifying_evidence",
            assessment.prerequisite_diagnostics["reasons"],
        )
        summary = analysis.analyze_for_context(context)
        self.assertTrue(summary.methodological_zero_findings)
        self.assertEqual(engine.finding_batches, [])
        self.assertEqual(findings.list_for_project("project"), [])
        self.assertEqual(insights.list_for_project("project"), [])

    def test_insufficient_independent_sources_is_not_ready(self):
        context, readiness, _, _, _, _, _, _ = setup_pipeline(
            model=ir4_design(minimum_independent_sources=2),
        )
        result = readiness.evaluate_for_context(context)
        assessment = acquired_assessment(result)
        self.assertFalse(result.ready_for_analysis)
        self.assertEqual(assessment.independent_source_count, 1)
        self.assertIn("insufficient_source_diversity", assessment.reason)

    def test_derived_calculation_with_missing_input_persists_no_derived_finding(self):
        context, _, analysis, _, findings, _, _, _ = setup_pipeline(
            raw=ir3_zip(years=YEARS[:-1]),
        )
        analysis.analyze_for_context(context)
        self.assertFalse(any(
            item.information_need_refs == ("change",)
            for item in findings.list_for_project("project")
        ))
        assessment = context.read_shared("analysis_derivations")["assessments"][0]
        self.assertEqual(assessment["status"], "insufficient")
        self.assertEqual(assessment["reason"], "missing_required_observation")

    def test_invalid_evidence_reference_produces_no_finding_or_insight(self):
        context, _, analysis, _, findings, insights, _, _ = setup_pipeline(
            invalid_evidence_ref=True,
        )
        summary = analysis.analyze_for_context(context)
        self.assertTrue(summary.methodological_zero_findings)
        self.assertEqual(findings.list_for_project("project"), [])
        self.assertEqual(insights.list_for_project("project"), [])


if __name__ == "__main__":
    unittest.main()
